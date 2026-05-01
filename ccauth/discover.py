"""Site and project discovery for Chameleon.

Builds SiteConfigs by querying the Chameleon reference API or the
OpenStack metadata service (vendordata).
"""

import json
import logging
import socket
import urllib.parse
import urllib.request

from ._urlutils import auth_url_base
from .config import SiteConfig

logger = logging.getLogger(__name__)

SITES_API_URL = "https://api.chameleoncloud.org/sites"
VENDORDATA_URL = "http://169.254.169.254/openstack/latest/vendor_data2.json"

DEFAULT_CLIENT_ID = "chi-cli-device-token"
DEFAULT_DISCOVERY_ENDPOINT = (
    "https://auth.chameleoncloud.org/auth/realms/chameleon"
    "/.well-known/openid-configuration"
)


def from_reference_api(api_url=SITES_API_URL):
    """Fetch available sites from the Chameleon reference API.

    Returns a list of SiteConfigs, one per site. auth config fields
    (client_id, discovery_endpoint) are left as empty strings and should
    be filled in by the caller.
    """
    try:
        with urllib.request.urlopen(api_url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError, ValueError):
        logger.debug("Could not fetch sites from %s", api_url)
        return []

    sites = []
    for item in data.get("items", []):
        web = item.get("web", "")
        name = item.get("name", "")
        uid = item.get("uid", "")
        if not web or not uid:
            continue
        sites.append(
            SiteConfig(
                auth_url=f"{web}:5000/v3",
                region_name=name,
                cloud_name=uid,
            )
        )
    return sites


def _metadata_reachable(host="169.254.169.254", port=80, timeout=1) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def from_vendordata(metadata_url=VENDORDATA_URL):
    """Fetch site config from the OpenStack metadata service.

    Only works when running on a Chameleon instance. Returns a list
    with one SiteConfig, or an empty list on failure.
    """
    parsed = urllib.parse.urlparse(metadata_url)
    host = parsed.hostname or "169.254.169.254"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not _metadata_reachable(host=host, port=port):
        return []
    try:
        with urllib.request.urlopen(metadata_url, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (OSError, TimeoutError, json.JSONDecodeError, ValueError):
        logger.debug("Could not fetch vendordata from %s", metadata_url)
        return []

    if not isinstance(data, dict):
        return []

    chi = data.get("chameleon", {})
    if not isinstance(chi, dict):
        return []

    auth_url = chi.get("auth_url", "")
    if not auth_url:
        return []

    region = chi.get("region", "")
    cloud_name = "kvm" if "kvm" in region.lower() else "chameleon"

    return [
        SiteConfig(
            auth_url=auth_url,
            region_name=region,
            cloud_name=cloud_name,
            client_id=DEFAULT_CLIENT_ID,
            discovery_endpoint=DEFAULT_DISCOVERY_ENDPOINT,
            project_id=chi.get("project_id", ""),
        )
    ]


def list_projects_at(session) -> list[dict]:
    """Return projects the session can scope to via /v3/auth/projects.

    Caller supplies an unscoped keystoneauth Session. Returns the raw
    project dicts from Keystone.
    """
    url = auth_url_base(session.auth.auth_url) + "/v3/auth/projects"
    return session.get(url, authenticated=True).json().get("projects", [])
