"""Chameleon OIDC device flow plugin for keystoneauth1.

Subclasses OidcDeviceAuthorization to add refresh token caching.
On first use, runs the interactive device flow and caches the refresh token.
On subsequent use, silently refreshes without user interaction.
Registers as 'v3chameleonoidc' entry point so any openstack tool can use it.
"""
import json
import logging
import os
import stat
import time
from pathlib import Path
from urllib.parse import urlencode

from keystoneauth1 import access, exceptions
from keystoneauth1.identity.v3.oidc import OidcDeviceAuthorization
from keystoneauth1 import session as ks_session

LOG = logging.getLogger(__name__)

REFRESH_TOKEN_CACHE = Path("~/.cache/ccauth/refresh_token.json")


class ChameleonDeviceAuth(OidcDeviceAuthorization):
    """OIDC device flow + refresh token caching for Chameleon.

    First call runs the interactive device flow and caches the refresh token.
    Subsequent calls use the cached refresh token silently.
    Falls back to device flow when the refresh token expires.
    """

    def __init__(self, auth_url, identity_provider, protocol, client_id, **kwargs):
        super().__init__(
            auth_url=auth_url,
            identity_provider=identity_provider,
            protocol=protocol,
            client_id=client_id,
            **kwargs,
        )
        self._last_token_response = None

    def _get_access_token(
        self, session: ks_session.Session, payload: dict
    ) -> str:
        """Exchange grant for an access token, capturing the full response.

        Dispatches between a simple POST (refresh_token grant) and the
        device flow polling loop (device_code grant). Always stashes the
        full response on self._last_token_response so callers can read
        the refresh_token from it.
        """
        if payload.get("grant_type") == "refresh_token":
            return self._single_token_request(session, payload)
        return self._poll_device_flow(session, payload)

    def _single_token_request(self, session: ks_session.Session, payload: dict) -> str:
        """Single POST to the token endpoint (for refresh_token grant).

        Adapted from _OidcBase._get_access_token.
        """
        if self.client_secret:
            client_auth = (self.client_id, self.client_secret)
        else:
            client_auth = None
            payload.setdefault("client_id", self.client_id)

        endpoint = self._get_access_token_endpoint(session)
        op_response = session.post(
            endpoint,
            requests_auth=client_auth,
            data=payload,
            log=False,
            authenticated=False,
        )
        response = op_response.json()
        self._last_token_response = response
        return response[self.access_token_type]

    def _poll_device_flow(self, session: ks_session.Session, payload: dict) -> str:
        """Poll the token endpoint until user approves the device flow.

        Adapted from OidcDeviceAuthorization._get_access_token, with the
        addition of stashing the full response on self._last_token_response.
        """
        if self.verification_uri_complete:
            LOG.warning(
                "To authenticate please go to: %s", self.verification_uri_complete
            )
        else:
            LOG.warning(
                "To authenticate please go to %s and enter the code %s",
                self.verification_uri,
                self.user_code,
            )

        if self.client_secret:
            client_auth = (self.client_id, self.client_secret)
        else:
            client_auth = None
            payload.setdefault("client_id", self.client_id)

        endpoint = self._get_access_token_endpoint(session)
        encoded_payload = urlencode(payload)
        error = None

        while time.time() < self.timeout:
            try:
                op_response = session.post(
                    endpoint,
                    requests_auth=client_auth,
                    data=encoded_payload,
                    headers=self.HEADER_X_FORM,
                    log=False,
                    authenticated=False,
                )
            except exceptions.http.BadRequest as exc:
                if exc.response is None:
                    raise
                error = exc.response.json().get("error")
                if error != "authorization_pending":
                    raise
                time.sleep(self.interval)
                continue
            break
        else:
            if error == "authorization_pending":
                raise exceptions.oidc.OidcDeviceAuthorizationTimeOut()

        response = op_response.json()
        self._last_token_response = response
        return response[self.access_token_type]

    def get_unscoped_auth_ref(
        self, session: ks_session.Session
    ) -> access.AccessInfoV3:
        """Authenticate, trying cached refresh token before device flow.

        1. If a cached refresh token exists, try it silently.
        2. On failure (expired, revoked), fall back to interactive device flow.
        3. Always cache the (possibly rotated) refresh token on success.
        """
        cached = _load_refresh_token(REFRESH_TOKEN_CACHE)
        if cached:
            try:
                payload = {
                    "grant_type": "refresh_token",
                    "refresh_token": cached,
                    "scope": self.scope,
                }
                access_token = self._get_access_token(session, payload)
                _save_refresh_token(
                    REFRESH_TOKEN_CACHE,
                    self._last_token_response.get("refresh_token", cached),
                )
                resp = self._get_keystone_token(session, access_token)
                auth_ref = access.create(resp=resp)
                assert isinstance(auth_ref, access.AccessInfoV3)  # nosec B101
                return auth_ref
            except Exception:
                LOG.debug("Refresh token failed, falling back to device flow")

        # Device flow — calls our _get_access_token which stashes _last_token_response
        auth_ref = super().get_unscoped_auth_ref(session)
        if self._last_token_response:
            _save_refresh_token(
                REFRESH_TOKEN_CACHE,
                self._last_token_response.get("refresh_token"),
            )
        return auth_ref


def _load_refresh_token(path: Path):
    """Read cached refresh token. Returns None if missing or unreadable."""
    p = path.expanduser()
    if not p.exists():
        return None
    try:
        with p.open() as f:
            return json.load(f).get("refresh_token")
    except (OSError, json.JSONDecodeError):
        return None


def _save_refresh_token(path: Path, refresh_token: str | None) -> None:
    """Write refresh token to cache file with mode 0600."""
    if not refresh_token:
        return
    p = path.expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with tmp.open("w") as f:
        json.dump({"refresh_token": refresh_token, "cached_at": time.time()}, f)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, p)
    LOG.debug("Cached refresh token to %s", p)
