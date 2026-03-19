"""Site configuration dataclass."""

from dataclasses import dataclass


@dataclass
class SiteConfig:
    """Everything needed to authenticate to one OpenStack site via OIDC."""

    auth_url: str
    region_name: str
    cloud_name: str
    client_id: str
    discovery_endpoint: str
    project_id: str = ""
    identity_provider: str = "chameleon"
    protocol: str = "openid"
