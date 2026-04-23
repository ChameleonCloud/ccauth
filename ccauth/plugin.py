"""OIDC device flow plugin for keystoneauth1 with refresh token caching.

Subclasses OidcDeviceAuthorization to add local refresh token caching.
On first use, runs the interactive device flow and caches the refresh token.
On subsequent use, silently refreshes without user interaction.
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

LOG = logging.getLogger(__name__)

_STATE_DIR = Path(os.environ.get("CC_LOGIN_STATE", "~/.cache/ccauth"))
REFRESH_TOKEN_CACHE = _STATE_DIR / "refresh_token.json"


class ChameleonDeviceAuth(OidcDeviceAuthorization):
    """OIDC device flow with refresh token caching.

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

    def _get_access_token(self, session, payload):
        """Exchange grant for an access token, capturing the full response.

        Dispatches between a simple POST (refresh_token grant) and the
        device flow polling loop (device_code grant). Stashes the full
        response so callers can extract the refresh_token.
        """
        if payload.get("grant_type") == "refresh_token":
            return self._single_token_request(session, payload)
        return self._poll_device_flow(session, payload)

    def _single_token_request(self, session, payload):
        """Single POST to the token endpoint (for refresh_token grant)."""
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

    def _poll_device_flow(self, session, payload):
        """Poll the token endpoint until user approves the device flow.

        Reimplements the parent to capture the full token response.
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

    def get_unscoped_auth_ref(self, session):
        """Authenticate, trying cached refresh token before device flow."""
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
            except Exception:  # pylint: disable=broad-exception-caught
                LOG.debug("Refresh token failed, falling back to device flow")
            else:
                resp = self._get_keystone_token(session, access_token)
                return access.create(resp=resp)

        auth_ref = super().get_unscoped_auth_ref(session)
        if self._last_token_response:
            _save_refresh_token(
                REFRESH_TOKEN_CACHE,
                self._last_token_response.get("refresh_token"),
            )
        return auth_ref


def clear_cache():
    """Remove cached refresh token. Returns True if a file was removed."""
    p = REFRESH_TOKEN_CACHE.expanduser()
    if p.exists():
        p.unlink()
        return True
    return False


def _load_refresh_token(path):
    """Read cached refresh token. Returns None if missing or unreadable."""
    p = path.expanduser()
    if not p.exists():
        return None
    try:
        with p.open() as f:
            return json.load(f).get("refresh_token")
    except (OSError, json.JSONDecodeError):
        return None


def _save_refresh_token(path, refresh_token):
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
