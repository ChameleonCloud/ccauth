"""Core OIDC authentication for OpenStack on Chameleon.

Provides AuthConfig and build_session for constructing keystoneauth1 sessions
via the OIDC device flow. Suitable for direct library use or as a foundation
for higher-level workflows (app credentials, project discovery, etc.).

    from ccauth.auth import AuthConfig, build_session
    config = AuthConfig(auth_url="https://chi.uc.chameleoncloud.org:5000/v3")
    session = build_session(config)
"""
from dataclasses import dataclass

from keystoneauth1.session import Session

from .discover import DEFAULT_CLIENT_ID, DEFAULT_DISCOVERY_ENDPOINT
from .plugin import ChameleonDeviceAuth


@dataclass
class AuthConfig:
    """Configuration for OIDC device flow authentication."""

    auth_url: str
    identity_provider: str = "chameleon"
    protocol: str = "openid"
    client_id: str = DEFAULT_CLIENT_ID
    discovery_endpoint: str = DEFAULT_DISCOVERY_ENDPOINT
    project_id: str = ""
    region_name: str = ""


def build_session(config: AuthConfig) -> Session:
    """Return a keystoneauth1 Session authenticated via OIDC device flow.

    On first call, displays a URL for the user to visit and approve. Subsequent
    calls exchange the cached refresh token silently.
    """
    plugin = ChameleonDeviceAuth(
        auth_url=config.auth_url,
        identity_provider=config.identity_provider,
        protocol=config.protocol,
        client_id=config.client_id,
        discovery_endpoint=config.discovery_endpoint,
        scope="openid",
        project_id=config.project_id,
    )
    return Session(auth=plugin)
