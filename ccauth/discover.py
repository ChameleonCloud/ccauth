"""Site and project discovery for Chameleon."""

import json
import logging
import urllib.request

from .config import SiteConfig

logger = logging.getLogger(__name__)

SITES_API_URL = "https://api.chameleoncloud.org/sites"


def from_reference_api(api_url=SITES_API_URL):
    """Fetch available sites from the Chameleon reference API.

    Returns a list of SiteConfigs, one per site.
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


def list_projects_at(session) -> list[dict]:
    """Return projects the session can scope to via /v3/auth/projects.

    Caller supplies an unscoped (or scoped) keystoneauth Session — typically
    via openstack.connect(cloud=...).session. Returns the raw project dicts.
    """
    url = _base_url(session.auth.auth_url) + "/v3/auth/projects"
    return session.get(url, authenticated=True).json().get("projects", [])


def _base_url(url: str) -> str:
    """Strip trailing /v3 and slashes from an auth URL."""
    return url.rstrip("/").removesuffix("/v3").rstrip("/")
