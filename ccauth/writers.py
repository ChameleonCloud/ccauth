"""Write v3chameleonoidc clouds.yaml and openrc files from SiteConfig.

Used by the ccauth OIDC plugin workflow. For application credential files
(cc-login), see appcred.write_openrc and appcred.write_clouds_yaml.
"""

import logging
from pathlib import Path

import yaml

from .config import SiteConfig
from ._fileutils import backup_file, load_yaml, write_secure

logger = logging.getLogger(__name__)

def _build_site_auth(site: SiteConfig):
    """
    Builds auth object for a given site, preferring to specify project_name and project_domain_name
    over project_id as project_ids are not reliably the same across sites.
    """
    auth = {
        "auth_url": site.auth_url,
        "identity_provider": site.identity_provider,
        "protocol": site.protocol,
        "client_id": site.client_id,
        "discovery_endpoint": site.discovery_endpoint,
    }
    if site.project_name:
        auth["project_name"] = site.project_name
        auth["project_domain_name"] = site.project_domain_name
    else:
        auth["project_id"] = site.project_id

    return auth


def write_clouds_yaml(sites: list[SiteConfig], output_path, force=False):
    """Write or update a clouds.yaml with v3chameleonoidc entries.

    Returns True if the file was written.
    """
    output_path = Path(output_path).expanduser()

    if output_path.exists() and not force:
        logger.info(
            "clouds.yaml already exists at %s. Use --force to update.", output_path
        )
        return False

    if output_path.exists() and force:
        backup_file(output_path)

    data = load_yaml(output_path)
    if not isinstance(data.get("clouds"), dict):
        data["clouds"] = {}

    for site in sites:
        data["clouds"][site.cloud_name] = {
            "auth_type": "v3chameleonoidc",
            "auth": _build_site_auth(site),
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
