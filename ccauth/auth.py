"""Device-flow auth and application credential caching for OpenStack.

Provides functions to orchestrate OIDC device flow authentication,
create application credentials, cache them locally, and write configuration files.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.request

import openstack
import yaml
from keystoneauth1.identity.v3.oidc import OidcDeviceAuthorization
from keystoneauth1.session import Session
from keystoneauth1 import exceptions as ks_exceptions

logger = logging.getLogger(__name__)


def _fetch_vendordata(metadata_url: str) -> Optional[Dict[str, Any]]:
    """Fetch OpenStack vendordata from metadata service.

    Returns the parsed JSON if available, None otherwise or on any error.
    """
    try:
        with urllib.request.urlopen(metadata_url, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
            return data
    except (OSError, TimeoutError, json.JSONDecodeError, ValueError):
        logger.debug("Could not fetch or parse vendordata from %s", metadata_url)
        return None


@dataclass
class AuthConfig:  # pylint: disable=too-many-instance-attributes
    """Configuration for device flow auth and app credential creation."""

    auth_url: str = "https://dev.uc.chameleoncloud.org:5000"
    identity_provider: str = "chameleon"
    protocol: str = "openid"
    client_id: Optional[str] = None
    keycloak_url: Optional[str] = None
    keycloak_realm: str = "chameleon"

    project_id: str = ""
    region_name: str = "CHI_DEV_UC"
    metadata_url: str = "http://169.254.169.254/openstack/latest/vendor_data2.json"

    app_cred_name: str = "chi-device-flow-auth"
    app_cred_expires_in_hours: int = 24

    lease_id: Optional[str] = None

    app_cred_cache_path: Path = Path("~/.cache/ccauth/chameleon-app-cred.json").expanduser()
    ttl_seconds: int = 24 * 60 * 60

    def __post_init__(self) -> None:
        """Set region-dependent configuration values and load from vendordata if available."""

        vendordata = _fetch_vendordata(self.metadata_url)
        vendordata_available = vendordata is not None and isinstance(vendordata, dict)

        if vendordata_available:
            chameleon_vd = vendordata.get("chameleon", {})
            if isinstance(chameleon_vd, dict):
                if self.region_name == "CHI_DEV_UC" and "region" in chameleon_vd:
                    self.region_name = chameleon_vd["region"]
                if "auth_url" in chameleon_vd and self.auth_url == "https://dev.uc.chameleoncloud.org:5000":
                    self.auth_url = chameleon_vd["auth_url"]
                if not self.project_id and "project_id" in chameleon_vd:
                    self.project_id = chameleon_vd["project_id"]
                if not self.lease_id and "lease_id" in chameleon_vd:
                    self.lease_id = chameleon_vd["lease_id"]
        else:
            logger.warning(
                "Could not fetch metadata from vendordata. Using defaults for dev environment. "
                "Override with CLI args: --auth-url, --region-name, --project-id, --client-id, --keycloak-url"
            )

        if self.client_id is None:
            self.client_id = (
                "local_dev_device_token" if self.region_name == "CHI_DEV_UC"
                else "chi-cli-device-token"
            )
        if self.keycloak_url is None:
            self.keycloak_url = (
                "https://auth.dev.chameleoncloud.org/auth" if self.region_name == "CHI_DEV_UC"
                else "https://auth.chameleoncloud.org/auth"
            )

        self._vendordata_available = vendordata_available


def _now_utc() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


def _parse_dt(s: str) -> datetime:
    """Parse datetime string (e.g., '2020-01-01T00:00:00Z') to UTC datetime."""
    s = s.strip()
    if s.endswith("Z"):
        try:
            dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return _now_utc()


def _read_app_cred_cache(path: Path, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    """Load app credential from cache if it exists and is within TTL.

    Also checks if the credential itself has expired (expires_at field).
    Returns None if cache is missing or stale.
    """
    path = path.expanduser()
    if not path.exists():
        return None

    try:
        with path.open("r") as f:
            data = json.load(f)
        # Validate cache file structure
        if not data.get("created_at") or not data.get("app_cred"):
            raise ValueError("Invalid cache structure")
    except (IOError, json.JSONDecodeError, ValueError):
        # File isn't valid JSON, can't be read, or lacks expected keys; back it up
        _backup_file(path)
        return None

    created_at = data.get("created_at")
    app_cred = data.get("app_cred")

    if time.time() - created_at > ttl_seconds:
        logger.debug("Cached credential expired after %ss", ttl_seconds)
        return None

    if app_cred and "expires_at" in app_cred:
        expires_at_str = app_cred["expires_at"]
        expires_at_dt = _parse_dt(expires_at_str)
        if expires_at_dt <= _now_utc():
            logger.debug("Cached credential has expired")
            return None

    logger.debug("Using cached credential from %s", path)
    return app_cred


def _backup_file(path: Path) -> None:
    """Back up an existing file.

    Moves the file to path.bak.TIMESTAMP and warns the user.
    Raises RuntimeError if backup fails to prevent data loss.
    """
    timestamp = int(time.time())
    backup_path = path.with_stem(path.stem + f".bak.{timestamp}")
    try:
        os.replace(path, backup_path)
        logger.warning(
            "Found existing file at %s. Backed up to %s. Creating file.",
            path,
            backup_path,
        )
    except OSError as e:
        raise RuntimeError(
            f"Could not back up existing file at {path} to {backup_path}: {e}. "
            f"Please manually rename or remove {path} to proceed."
        ) from e


def _write_app_cred_cache(path: Path, app_cred: Dict[str, Any]) -> None:
    """Write app credential to cache file.

    File is create/readable only by owner (mode 0600).
    """
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "created_at": time.time(),
        "app_cred": app_cred,
    }
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    os.replace(tmp_path, path)
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    logger.debug("Cached credential to %s", path)


def _build_device_flow_session(config: AuthConfig) -> Session:
    """Create a keystoneauth1 Session using OIDC device flow."""
    discovery_endpoint = (
        f"{config.keycloak_url}/realms/"
        f"{config.keycloak_realm}/.well-known/openid-configuration"
    )

    device_auth = OidcDeviceAuthorization(
        auth_url=config.auth_url,
        identity_provider=config.identity_provider,
        protocol=config.protocol,
        client_id=config.client_id,
        discovery_endpoint=discovery_endpoint,
        scope="openid",
        project_id=config.project_id,
    )

    return Session(auth=device_auth)


def _create_openstack_connection(config: AuthConfig) -> openstack.connection.Connection:
    """Build an OpenStack connection with device flow auth."""
    sess = _build_device_flow_session(config)
    conn = openstack.connection.Connection(
        session=sess,
        region_name=config.region_name,
        auth_url=config.auth_url,
    )
    return conn


def _get_current_user_id(conn: openstack.connection.Connection) -> str:
    """Extract the authenticated user_id from the connection's access token."""
    sess: Session = conn.session
    access = sess.auth.get_access(sess)
    user_id = access.user_id
    if not user_id:
        raise RuntimeError("Could not determine user_id from access token; app cred creation requires a user.")
    return user_id


def _create_new_app_cred(conn: openstack.connection.Connection, config: AuthConfig) -> Dict[str, Any]:
    """Create a new application credential with expiry and the lease id and timestamp in the name.

    Returns the full credential dict including the secret.
    """
    identity = conn.identity
    user_id = _get_current_user_id(conn)

    ts = _now_utc().strftime("%Y%m%d%H%M%S")
    if config.lease_id:
        unique_name = f"{config.app_cred_name}-{config.lease_id}_{ts}"
    else:
        unique_name = f"{config.app_cred_name}-{ts}"

    expires_at = None
    if config.app_cred_expires_in_hours > 0:
        exp_dt = _now_utc() + timedelta(hours=config.app_cred_expires_in_hours)
        expires_at = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    params: Dict[str, Any] = {
        "name": unique_name,
        "unrestricted": False,
    }
    if expires_at:
        params["expires_at"] = expires_at

    app_cred = identity.create_application_credential(user=user_id, **params)

    if hasattr(app_cred, "to_dict"):
        app_cred_dict = app_cred.to_dict()
    else:
        app_cred_dict = dict(app_cred)

    app_cred_dict.setdefault("user_id", user_id)
    app_cred_dict.setdefault("name", unique_name)
    if expires_at and "expires_at" not in app_cred_dict:
        app_cred_dict["expires_at"] = expires_at

    return app_cred_dict


def ensure_app_cred(config: AuthConfig, force_refresh: bool = False) -> Dict[str, Any]:
    """Get or create an application credential, using cache if valid.

    On first call or when cache expires, performs device flow auth and creates a new
    credential. Subsequent calls within TTL return the cached credential.
    Pass force_refresh=True to bypass cache and create a new credential.

    If a cached credential is used but the OpenStack call fails (e.g., due to expiry),
    regenerates automatically.
    """
    cache_path = config.app_cred_cache_path

    if not force_refresh:
        cached = _read_app_cred_cache(cache_path, config.ttl_seconds)
        if cached is not None:
            logger.debug("Credential cache valid, skipping refresh")
            return cached

    logger.debug("Creating new application credential")
    try:
        conn = _create_openstack_connection(config)
        app_cred = _create_new_app_cred(conn, config)
    except ks_exceptions.InternalServerError as e:
        # Transient server error during authentication or credential creation
        logger.error("OpenStack server error during device flow auth (HTTP 500): %s", e)
        logger.error("Please retry the command. If it continues to fail, please contact support.")
        raise
    except Exception as e:
        # If credential creation fails, try to use cache as fallback, else re-raise
        cached = _read_app_cred_cache(cache_path, config.ttl_seconds)
        if cached is not None:
            logger.warning("Credential refresh failed (%s); using cached credential", e)
            return cached
        raise

    _write_app_cred_cache(cache_path, app_cred)
    return app_cred


def _get_app_cred_id_and_secret(app_cred: Dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """Extract app credential ID and secret, handling multiple key variants."""
    app_cred_id = app_cred.get("id") or app_cred.get("application_credential_id")
    app_cred_secret = (
        app_cred.get("application_credential_secret")
        or app_cred.get("secret")
    )
    return app_cred_id, app_cred_secret


def _check_config(auth_url: Optional[str], region_name: Optional[str]) -> None:
    """Warn about any missing configuration values.

    These may need to be added manually to fully configure the environment.
    """
    missing = []
    if not auth_url:
        missing.append("auth_url")
    if not region_name:
        missing.append("region_name")

    if missing:
        logger.warning(
            "Missing config values: %s. "
            "You may need to add these manually to the generated files.",
            ", ".join(missing),
        )


def write_openrc_file(
    app_cred: Dict[str, Any],
    output_path: str | Path,
    region_name: Optional[str] = None,
    auth_url: Optional[str] = None,
    force: bool = False,
) -> bool:
    """Write a bash-sourceable openrc file for the app credential.

    Sets OS_AUTH_TYPE=v3applicationcredential and app credential env vars.
    If the file already exists, warns and skips unless force=True.
    File is written with mode 0600 for security.
    Returns True if file was written, False otherwise.
    """
    output_path = Path(output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    app_cred_id, app_cred_secret = _get_app_cred_id_and_secret(app_cred)

    if not app_cred_id or not app_cred_secret:
        raise RuntimeError(
            "Application credential is missing id or secret; cannot write openrc. "
            "Try forcing refresh so a new app credential is created and cached."
        )

    _check_config(auth_url, region_name)

    if output_path.exists() and not force:
        logger.info("openrc file already exists at %s", output_path)
        logger.info("Use --force-openrc to overwrite.")
        return False

    if output_path.exists() and force:
        _backup_file(output_path)

    lines = [
        "#!/usr/bin/env bash",
        "# OpenStack application credential environment",
        "",
        "# Use application credential auth, not password auth",
        "export OS_AUTH_TYPE=v3applicationcredential",
        "",
    ]

    if auth_url:
        lines.append(f'export OS_AUTH_URL="{auth_url}"')

    if region_name:
        lines.append(f'export OS_REGION_NAME="{region_name}"')

    lines.append(f'export OS_APPLICATION_CREDENTIAL_ID="{app_cred_id}"')
    lines.append(f'export OS_APPLICATION_CREDENTIAL_SECRET="{app_cred_secret}"')

    content = "\n".join(lines) + "\n"
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, output_path)
    os.chmod(output_path, stat.S_IRUSR | stat.S_IWUSR)
    logger.debug("Wrote openrc to %s", output_path)

    if force:
        logger.info("Overwrote openrc file at %s", output_path)
    return True

def write_clouds_yaml(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    app_cred: Dict[str, Any],
    output_path: str | Path,
    cloud_name: str = "chameleon",
    region_name: Optional[str] = None,
    auth_url: Optional[str] = None,
    force: bool = False,
) -> bool:
    """Write or update a clouds.yaml file with the app credential.

    Creates or updates an entry in the clouds section using v3applicationcredential auth.
    If the cloud entry already exists, warns and skips unless force=True.
    File is written with mode 0600 for security.
    Returns True if file was written, False otherwise.
    """
    output_path = Path(output_path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    app_cred_id, app_cred_secret = _get_app_cred_id_and_secret(app_cred)

    if not app_cred_id or not app_cred_secret:
        raise RuntimeError(
            "Application credential is missing id or secret; cannot write clouds.yaml. "
            "Try forcing refresh so a new app credential is created and cached."
        )

    data: Dict[str, Any] = {}
    if output_path.exists():
        try:
            with output_path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (IOError, yaml.YAMLError):
            data = {}

    if "clouds" not in data or not isinstance(data["clouds"], dict):
        data["clouds"] = {}

    if cloud_name in data["clouds"] and not force:
        logger.info("cloud '%s' already exists in %s", cloud_name, output_path)
        logger.info("Use --force-clouds-yaml to overwrite.")
        return False

    cloud: Dict[str, Any] = {
        "auth_type": "v3applicationcredential",
        "auth": {
            "application_credential_id": app_cred_id,
            "application_credential_secret": app_cred_secret,
        },
    }
    if auth_url:
        cloud["auth"]["auth_url"] = auth_url
    if region_name:
        cloud["region_name"] = region_name

    data["clouds"][cloud_name] = cloud

    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False)
    os.replace(tmp_path, output_path)
    os.chmod(output_path, stat.S_IRUSR | stat.S_IWUSR)
    logger.debug("Wrote clouds.yaml to %s", output_path)

    _check_config(auth_url, region_name)

    if force:
        logger.info("Updated cloud '%s' in %s", cloud_name, output_path)
    return True
