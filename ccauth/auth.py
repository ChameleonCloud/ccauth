"""Vendordata fetching and clouds.yaml/openrc writing for Chameleon.

Provides site configuration (auth_url, project_id, etc.) from the OpenStack
metadata service and writes clouds.yaml / openrc files using the v3chameleonoidc
auth type.
"""
from __future__ import annotations

import json
import logging
import os
import stat
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)


def _fetch_vendordata(metadata_url: str) -> Optional[Dict[str, Any]]:
    """Fetch OpenStack vendordata from metadata service.

    Returns the parsed JSON dict, or None on any error.
    """
    try:
        with urllib.request.urlopen(metadata_url, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError, ValueError):
        logger.debug("Could not fetch vendordata from %s", metadata_url)
        return None


@dataclass
class SiteConfig:
    """Configuration for one Chameleon Keystone site."""

    auth_url: str
    region_name: str
    project_id: str
    identity_provider: str = "chameleon"
    protocol: str = "openid"
    cloud_name: str = "chameleon"

    # Keycloak config (same across all sites)
    client_id: str = "chi-cli-device-token"
    discovery_endpoint: str = (
        "https://auth.chameleoncloud.org/auth/realms/chameleon"
        "/.well-known/openid-configuration"
    )


@dataclass
class AuthConfig:
    """Top-level config: one or more Keystone sites sharing one Keycloak."""

    sites: List[SiteConfig] = field(default_factory=list)
    metadata_url: str = (
        "http://169.254.169.254/openstack/latest/vendor_data2.json"
    )

    @classmethod
    def from_vendordata(cls, metadata_url: str) -> "AuthConfig":
        """Build config by reading OpenStack vendordata from metadata service."""
        vendordata = _fetch_vendordata(metadata_url)
        if not vendordata or not isinstance(vendordata, dict):
            logger.warning(
                "Could not fetch metadata from %s. "
                "Provide site config explicitly via CLI args.",
                metadata_url,
            )
            return cls(metadata_url=metadata_url)

        chi = vendordata.get("chameleon", {})
        if not isinstance(chi, dict):
            return cls(metadata_url=metadata_url)

        sites = []
        auth_url = chi.get("auth_url", "")
        region_name = chi.get("region", "")
        project_id = chi.get("project_id", "")

        if auth_url:
            sites.append(
                SiteConfig(
                    auth_url=auth_url,
                    region_name=region_name,
                    project_id=project_id,
                )
            )

        return cls(sites=sites, metadata_url=metadata_url)


def _backup_file(path: Path) -> None:
    """Move path to path.bak.TIMESTAMP. Raises RuntimeError if it fails."""
    import time
    backup = path.with_stem(path.stem + f".bak.{int(time.time())}")
    try:
        os.replace(path, backup)
        logger.warning("Backed up %s to %s", path, backup)
    except OSError as e:
        raise RuntimeError(
            f"Could not back up {path} to {backup}: {e}"
        ) from e


def _write_secure(path: Path, content: str) -> None:
    """Write content to path via a temp file, chmod 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def write_clouds_yaml(
    sites: List[SiteConfig],
    output_path: Path,
    force: bool = False,
) -> bool:
    """Write or update a clouds.yaml with v3chameleonoidc entries for each site.

    Returns True if the file was written.
    """
    output_path = Path(output_path).expanduser()

    data: Dict[str, Any] = {}
    if output_path.exists():
        try:
            with output_path.open(encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError):
            data = {}

    if "clouds" not in data or not isinstance(data["clouds"], dict):
        data["clouds"] = {}

    written = []
    skipped = []
    for site in sites:
        if site.cloud_name in data["clouds"] and not force:
            skipped.append(site.cloud_name)
            continue

        data["clouds"][site.cloud_name] = {
            "auth_type": "v3chameleonoidc",
            "auth": {
                "auth_url": site.auth_url,
                "identity_provider": site.identity_provider,
                "protocol": site.protocol,
                "project_id": site.project_id,
                "client_id": site.client_id,
                "discovery_endpoint": site.discovery_endpoint,
            },
            "region_name": site.region_name,
        }
        written.append(site.cloud_name)

    if skipped:
        logger.info(
            "Skipped existing clouds: %s. Use --force to overwrite.",
            ", ".join(skipped),
        )

    if not written:
        return False

    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, default_flow_style=False)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, output_path)
    logger.debug("Wrote clouds.yaml to %s", output_path)
    return True


def write_openrc_file(
    site: SiteConfig,
    output_path: Path,
    force: bool = False,
) -> bool:
    """Write a bash-sourceable openrc for a single site using v3chameleonoidc.

    Returns True if the file was written.
    """
    output_path = Path(output_path).expanduser()

    if output_path.exists() and not force:
        logger.info("openrc already exists at %s. Use --force to overwrite.", output_path)
        return False

    if output_path.exists() and force:
        _backup_file(output_path)

    lines = [
        "#!/usr/bin/env bash",
        "",
        f'export OS_AUTH_TYPE="v3chameleonoidc"',
        f'export OS_AUTH_URL="{site.auth_url}"',
        f'export OS_IDENTITY_PROVIDER="{site.identity_provider}"',
        f'export OS_PROTOCOL="{site.protocol}"',
        f'export OS_PROJECT_ID="{site.project_id}"',
        f'export OS_CLIENT_ID="{site.client_id}"',
        f'export OS_DISCOVERY_ENDPOINT="{site.discovery_endpoint}"',
        f'export OS_REGION_NAME="{site.region_name}"',
    ]

    _write_secure(output_path, "\n".join(lines) + "\n")
    logger.debug("Wrote openrc to %s", output_path)
    return True
