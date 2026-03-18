"""Write clouds.yaml and openrc files from SiteConfig."""

import logging
import os
import stat
import time
from pathlib import Path

import yaml


logger = logging.getLogger(__name__)


def write_clouds_yaml(sites, output_path, force=False):
    """Write or update a clouds.yaml with v3chameleonoidc entries.

    Returns True if the file was written.
    """
    output_path = Path(output_path).expanduser()

    data = {}
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

    _write_secure(output_path, yaml.safe_dump(data, default_flow_style=False))
    return True


def write_openrc_file(site, output_path, force=False):
    """Write a bash-sourceable openrc for a single site.

    Returns True if the file was written.
    """
    output_path = Path(output_path).expanduser()

    if output_path.exists() and not force:
        logger.info(
            "openrc already exists at %s. Use --force to overwrite.", output_path
        )
        return False

    if output_path.exists() and force:
        _backup_file(output_path)

    lines = [
        "#!/usr/bin/env bash",
        "",
        'export OS_AUTH_TYPE="v3chameleonoidc"',
        f'export OS_AUTH_URL="{site.auth_url}"',
        f'export OS_IDENTITY_PROVIDER="{site.identity_provider}"',
        f'export OS_PROTOCOL="{site.protocol}"',
        f'export OS_PROJECT_ID="{site.project_id}"',
        f'export OS_CLIENT_ID="{site.client_id}"',
        f'export OS_DISCOVERY_ENDPOINT="{site.discovery_endpoint}"',
        f'export OS_REGION_NAME="{site.region_name}"',
    ]

    _write_secure(output_path, "\n".join(lines) + "\n")
    return True


def _backup_file(path):
    backup = path.with_stem(path.stem + f".bak.{int(time.time())}")
    try:
        os.replace(path, backup)
        logger.warning("Backed up %s to %s", path, backup)
    except OSError as e:
        raise RuntimeError(f"Could not back up {path} to {backup}: {e}") from e


def _write_secure(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)
