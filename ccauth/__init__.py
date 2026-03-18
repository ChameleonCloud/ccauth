"""ccauth — Chameleon OIDC device flow plugin for keystoneauth1."""
from .plugin import ChameleonDeviceAuth
from .auth import AuthConfig, SiteConfig, write_clouds_yaml, write_openrc_file

__all__ = [
    "ChameleonDeviceAuth",
    "AuthConfig",
    "SiteConfig",
    "write_clouds_yaml",
    "write_openrc_file",
]

__version__ = "0.2.0"
