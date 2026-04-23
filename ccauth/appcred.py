"""Application credential management for cc-login.

Performs device-flow auth via keystoneauth1, creates a short-lived OpenStack
application credential, caches it, and writes v3applicationcredential
openrc/clouds.yaml files.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from keystoneauth1.session import Session

from ._fileutils import backup_file, load_yaml, write_secure
from .auth import AuthConfig, build_session

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_PATH = Path("~/.cache/ccauth/chameleon-app-cred.json").expanduser()


@dataclass
class AppCredConfig(AuthConfig):  # pylint: disable=too-many-instance-attributes
    """Extends AuthConfig with app credential management fields."""

    app_cred_name: str = "chi-device-flow-auth"
    app_cred_expires_in_hours: int = 24
    app_cred_cache_path: Path = field(default_factory=lambda: _DEFAULT_CACHE_PATH)
    ttl_seconds: int = 86400


def ensure_app_cred(
    config: AppCredConfig, force_refresh: bool = False
) -> Dict[str, Any]:
    """Return a valid app credential, authenticating via device flow if needed.

    Checks cache first (unless force_refresh=True). On cache miss, performs
    device flow, creates a new app cred, caches it, and returns it.
    """
    if not force_refresh:
        cached = _read_cache(config.app_cred_cache_path, config.ttl_seconds)
        if cached is not None:
            return cached

    sess = build_session(config)
    user_id = _get_user_id(sess)

    old_name = _get_cached_name(config.app_cred_cache_path)
    name_to_use = None
    if old_name and _delete_app_cred(sess, config.auth_url, user_id, old_name):
        name_to_use = old_name
        logger.debug("Reusing old app credential name: %s", old_name)
    elif old_name:
        logger.debug("Could not delete old credential '%s'; using new name", old_name)

    app_cred = _create_app_cred(sess, config, user_id, name=name_to_use)
    _write_cache(config.app_cred_cache_path, app_cred)
    return app_cred


def write_openrc(
    app_cred: Dict[str, Any],
    output_path: Path | str,
    auth_url: str,
    region_name: str = "",
    force: bool = False,
) -> bool:
    """Write a v3applicationcredential openrc file. Returns True if written."""
    output_path = Path(output_path).expanduser()
    cred_id, cred_secret = _extract_id_secret(app_cred)

    if output_path.exists() and not force:
        logger.info(
            "openrc already exists at %s. Use --force-openrc to overwrite.", output_path
        )
        return False
    if output_path.exists() and force:
        backup_file(output_path)

    lines = [
        "#!/usr/bin/env bash",
        "# OpenStack application credential environment",
        "",
        'export OS_AUTH_TYPE="v3applicationcredential"',
        f'export OS_AUTH_URL="{auth_url}"',
    ]
    if region_name:
        lines.append(f'export OS_REGION_NAME="{region_name}"')
    lines += [
        f'export OS_APPLICATION_CREDENTIAL_ID="{cred_id}"',
        f'export OS_APPLICATION_CREDENTIAL_SECRET="{cred_secret}"',
    ]

    write_secure(output_path, "\n".join(lines) + "\n")
    return True


def write_clouds_yaml(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    app_cred: Dict[str, Any],
    output_path: Path | str,
    cloud_name: str = "chameleon",
    auth_url: str = "",
    region_name: str = "",
    force: bool = False,
) -> bool:
    """Write or update a clouds.yaml with a v3applicationcredential entry. Returns True if written."""
    output_path = Path(output_path).expanduser()
    cred_id, cred_secret = _extract_id_secret(app_cred)

    data = load_yaml(output_path)
    if not isinstance(data.get("clouds"), dict):
        data["clouds"] = {}

    if cloud_name in data["clouds"] and not force:
        logger.info(
            "Cloud '%s' already exists in %s. Use --force-clouds-yaml to overwrite.",
            cloud_name,
            output_path,
        )
        return False

    cloud: Dict[str, Any] = {
        "auth_type": "v3applicationcredential",
        "auth": {
            "auth_url": auth_url,
            "application_credential_id": cred_id,
            "application_credential_secret": cred_secret,
        },
    }
    if region_name:
        cloud["region_name"] = region_name

    data["clouds"][cloud_name] = cloud
    write_secure(output_path, yaml.safe_dump(data, default_flow_style=False))
    return True



def _extract_id_secret(app_cred: Dict[str, Any]) -> tuple[str, str]:
    cred_id = app_cred.get("id") or app_cred.get("application_credential_id") or ""
    cred_secret = (
        app_cred.get("secret") or app_cred.get("application_credential_secret") or ""
    )
    if not cred_id or not cred_secret:
        raise RuntimeError(
            "App credential missing id or secret. Try --force-refresh to create a new one."
        )
    return cred_id, cred_secret


def _v3_base(auth_url: str) -> str:
    base = auth_url.rstrip("/")
    return base if base.endswith("/v3") else f"{base}/v3"


def _get_user_id(sess: Session) -> str:
    access = sess.auth.get_access(sess)
    user_id = access.user_id
    if not user_id:
        raise RuntimeError("Could not determine user_id from access token")
    return user_id


def _create_app_cred(
    sess: Session, config: AppCredConfig, user_id: str, name: Optional[str] = None
) -> Dict[str, Any]:
    if name is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        name = f"{config.app_cred_name}-{ts}"

    body: Dict[str, Any] = {"name": name, "unrestricted": True}
    if config.app_cred_expires_in_hours > 0:
        exp = datetime.now(timezone.utc) + timedelta(hours=config.app_cred_expires_in_hours)
        body["expires_at"] = exp.strftime("%Y-%m-%dT%H:%M:%SZ")

    url = f"{_v3_base(config.auth_url)}/users/{user_id}/application_credentials"
    resp = sess.post(url, json={"application_credential": body}, authenticated=True)
    result = resp.json()["application_credential"]
    result.setdefault("user_id", user_id)
    return result


def _delete_app_cred(
    sess: Session, auth_url: str, user_id: str, cred_name: str
) -> bool:
    url = f"{_v3_base(auth_url)}/users/{user_id}/application_credentials"
    try:
        resp = sess.get(url, authenticated=True)
        for cred in resp.json().get("application_credentials", []):
            if cred["name"] == cred_name:
                sess.delete(f"{url}/{cred['id']}", authenticated=True)
                logger.debug("Deleted old app credential: %s", cred_name)
                return True
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.debug("Could not delete old app credential '%s': %s", cred_name, e)
    return False


def _read_cache(path: Path, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    path = path.expanduser()
    if not path.exists():
        return None
    try:
        with path.open() as f:
            data = json.load(f)
        if not data.get("created_at") or not data.get("app_cred"):
            raise ValueError("invalid structure")
    except (OSError, json.JSONDecodeError, ValueError):
        backup_file(path)
        return None

    if time.time() - data["created_at"] > ttl_seconds:
        logger.debug("App cred cache expired (TTL)")
        return None

    app_cred = data["app_cred"]
    if "expires_at" in app_cred:
        try:
            dt = datetime.fromisoformat(app_cred["expires_at"].strip().replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            parsed_dt = dt.astimezone(timezone.utc)
        except ValueError:
            parsed_dt = datetime.now(timezone.utc)
        if parsed_dt <= datetime.now(timezone.utc):
            logger.debug("Cached app cred has expired")
            return None

    logger.debug("Using cached app cred")
    return app_cred


def _write_cache(path: Path, app_cred: Dict[str, Any]) -> None:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(
            {
                "created_at": time.time(),
                "app_cred": app_cred,
                "app_cred_name": app_cred.get("name"),
            },
            f,
            indent=2,
            sort_keys=True,
        )
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def _get_cached_name(path: Path) -> Optional[str]:
    path = path.expanduser()
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f).get("app_cred_name")
    except (OSError, json.JSONDecodeError):
        return None
