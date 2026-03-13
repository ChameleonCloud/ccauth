"""CLI entrypoint for the `ccauth` package.

This module holds argument parsing and the `main()` function so that
`ccauth.auth` remains a library of pure functions.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from .auth import (
    AuthConfig,
    ensure_app_cred,
    write_openrc_file,
    write_clouds_yaml,
    _get_app_cred_id_and_secret,
)

logger = logging.getLogger(__name__)

# Cache default config to avoid redundant metadata fetches
_default_config = AuthConfig()


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for cc-login CLI."""
    p = argparse.ArgumentParser(
        prog="cc-login-dev",
        description="Device auth + app cred caching + openrc/clouds.yaml generation.",
    )

    p.add_argument("--auth-url", default=_default_config.auth_url, help="Keystone auth URL")
    p.add_argument("--identity-provider", default=_default_config.identity_provider)
    p.add_argument("--protocol", default=_default_config.protocol)
    p.add_argument("--client-id", default=None, help="Keycloak device token client ID")
    p.add_argument("--keycloak-url", default=None, help="Keycloak URL")
    p.add_argument("--keycloak-realm", default=_default_config.keycloak_realm)

    p.add_argument("--project-id", default="", help="OpenStack project ID from vendordata or manual entry")
    p.add_argument("--region-name", default=_default_config.region_name)
    p.add_argument(
        "--metadata-url",
        default="http://169.254.169.254/openstack/latest/vendor_data2.json",
        help="Metadata service URL for vendordata (default: http://169.254.169.254/openstack/latest/vendor_data2.json)",
    )

    p.add_argument("--app-cred-name", default=_default_config.app_cred_name)
    p.add_argument(
        "--app-cred-expires-hours",
        type=int,
        default=_default_config.app_cred_expires_in_hours,
        help="App credential expiry in hours (default 24)",
    )

    p.add_argument(
        "--app-cred-cache-path",
        default=str(_default_config.app_cred_cache_path),
        help="Path to cached app credential JSON (default ~/.cache/ccauth/chameleon-app-cred.json)",
    )
    p.add_argument(
        "--ttl-seconds",
        type=int,
        default=_default_config.ttl_seconds,
        help="Local cache TTL in seconds (default 24h)",
    )
    p.add_argument(
        "--force-refresh",
        action="store_true",
        help="Ignore cache and force new device auth + new app cred",
    )

    p.add_argument(
        "--output-openrc",
        help="Write openrc-style file for this app credential",
    )
    p.add_argument(
        "--output-clouds-yaml",
        help="Write clouds.yaml with this app credential",
    )
    p.add_argument(
        "--cloud-name",
        default="chameleon",
        help="Cloud name for clouds.yaml (default: chameleon)",
    )
    p.add_argument(
        "--force-clouds-yaml",
        action="store_true",
        help="Overwrite existing cloud entry in clouds.yaml",
    )
    p.add_argument(
        "--force-openrc",
        action="store_true",
        help="Overwrite existing openrc file",
    )
    p.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    return p


def main(argv: Optional[list[str]] = None) -> int:
    """Main entrypoint: parse args, perform auth, and write output files."""

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(levelname)s: %(message)s" if args.debug else "%(message)s",
        stream=sys.stderr,
    )

    config = AuthConfig(
        auth_url=args.auth_url,
        identity_provider=args.identity_provider,
        protocol=args.protocol,
        client_id=args.client_id,
        keycloak_url=args.keycloak_url,
        keycloak_realm=args.keycloak_realm,
        project_id=args.project_id,
        region_name=args.region_name,
        metadata_url=args.metadata_url,
        app_cred_name=args.app_cred_name,
        app_cred_expires_in_hours=args.app_cred_expires_hours,
        app_cred_cache_path=Path(args.app_cred_cache_path).expanduser(),
        ttl_seconds=args.ttl_seconds,
    )

    if not getattr(config, '_vendordata_available', True):
        if config.region_name == _default_config.region_name and config.auth_url == _default_config.auth_url:
            logger.warning(
                "Could not reach metadata service. Using dev environment defaults. "
                "For production, provide explicit values for: "
                "--auth-url, --region-name, --project-id, --client-id, --keycloak-url"
            )

    app_cred = ensure_app_cred(config, force_refresh=args.force_refresh)

    app_cred_id, _ = _get_app_cred_id_and_secret(app_cred)
    cred_name = app_cred.get('name')
    expires_at = app_cred.get("expires_at")

    logger.info("Application credential: %s", cred_name)
    logger.info("Credential ID: %s", app_cred_id)
    if expires_at:
        logger.info("Expires at: %s", expires_at)
        logger.info("To delete this credential, run: openstack application credential delete %s", app_cred_id)

    if args.output_openrc:
        if write_openrc_file(
            app_cred=app_cred,
            output_path=args.output_openrc,
            region_name=config.region_name,
            auth_url=config.auth_url,
            force=args.force_openrc,
        ):
            logger.info("Written openrc to %s", args.output_openrc)

    if args.output_clouds_yaml:
        if write_clouds_yaml(
            app_cred=app_cred,
            output_path=args.output_clouds_yaml,
            cloud_name=args.cloud_name,
            region_name=config.region_name,
            auth_url=config.auth_url,
            force=args.force_clouds_yaml,
        ):
            logger.info("Updated clouds.yaml at %s", args.output_clouds_yaml)

    if not args.output_openrc and not args.output_clouds_yaml:
        logger.info("No output files requested. To use these credentials, generate a configuration file:")
        logger.info("  cc-login --output-openrc ~/openrc")
        logger.info("  cc-login --output-clouds-yaml ~/clouds.yaml")

    logger.info("Credential will expire, please consider deleting %s (%s) once it does.", cred_name, app_cred_id)

    return 0
