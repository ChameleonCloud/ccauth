"""Write v3chameleonoidc clouds.yaml and openrc files from SiteConfig.

Used by the ccauth OIDC plugin workflow. For application credential files
(cc-login), see appcred.write_openrc and appcred.write_clouds_yaml.
"""

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

    if output_path.exists() and not force:
        logger.info(
            "clouds.yaml already exists at %s. Use --force to update.", output_path
        )
        return False

    data = load_yaml(output_path)
    if not isinstance(data.get("clouds"), dict):
        data["clouds"] = {}

    for site in sites:
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

    write_secure(output_path, yaml.safe_dump(data, default_flow_style=False))
    return True


def write_openrc_file(site, output_path, force=False):
    """Write a v3chameleonoidc openrc file for a single site.

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
