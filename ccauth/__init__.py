"""ccauth: OIDC device flow authentication for OpenStack on Chameleon.

Library usage:

  Core OIDC auth:
    from ccauth import AuthConfig, build_session

  OIDC plugin workflow (ccauth clouds-yaml / openrc):
    from ccauth import SiteConfig, from_reference_api, write_clouds_yaml

The application credential flow (cc-login) is not recommended, and support
for it will be dropped soon.
"""
from importlib.metadata import PackageNotFoundError, version

from .auth import AuthConfig, build_session
from .appcred import AppCredConfig, ensure_app_cred
from .config import SiteConfig
from .discover import from_reference_api, from_vendordata, list_projects_at
from .plugin import ChameleonDeviceAuth, clear_cache
from .writers import write_clouds_yaml, write_openrc_file

try:
    __version__ = version("ccauth")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

__all__ = [
    "AuthConfig",
    "build_session",
    "AppCredConfig",
    "ensure_app_cred",
    "SiteConfig",
    "from_reference_api",
    "from_vendordata",
    "list_projects_at",
    "ChameleonDeviceAuth",
    "clear_cache",
    "write_clouds_yaml",
    "write_openrc_file",
]
