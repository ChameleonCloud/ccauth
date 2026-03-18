"""Library interface for device-flow auth and app credential caching.

Exports the main public API: AuthConfig, ensure_app_cred, write_openrc_file, write_clouds_yaml.
"""
from .auth import (
	AuthConfig,
	ensure_app_cred,
	write_openrc_file,
	write_clouds_yaml,
)

__all__ = [
	"AuthConfig",
	"ensure_app_cred",
	"write_openrc_file",
	"write_clouds_yaml",
]

__version__ = "0.1.0"
