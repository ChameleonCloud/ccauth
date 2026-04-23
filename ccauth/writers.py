"""Write clouds.yaml and openrc files from SiteConfig."""

import logging
from pathlib import Path

import yaml

from ._fileutils import backup_file, load_yaml, write_secure

logger = logging.getLogger(__name__)


def write_clouds_yaml(sites, output_path, force=False):
    """Write or update a clouds.yaml with v3chameleonoidc entries.

    Returns True if the file was written.
    """
    output_path = Path(output_path).expanduser()
    data = load_yaml(output_path)

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

    write_secure(output_path, yaml.safe_dump(data, default_flow_style=False))
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
        backup_file(output_path)

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

    write_secure(output_path, "\n".join(lines) + "\n")
    return True
