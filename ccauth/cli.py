"""CLI entrypoint for ccauth.

Subcommands:
  login       — Authenticate via OIDC device flow
  logout      — Clear cached refresh tokens
  clouds-yaml — Write a clouds.yaml file
  openrc      — Write an openrc file
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from keystoneauth1.session import Session

from . import __version__
from .config import SiteConfig
from .discover import (
    DEFAULT_CLIENT_ID,
    DEFAULT_DISCOVERY_ENDPOINT,
    SITES_API_URL,
    VENDORDATA_URL,
    from_reference_api,
    from_vendordata,
)
from .plugin import ChameleonDeviceAuth, clear_cache
from .writers import write_clouds_yaml, write_openrc_file

logger = logging.getLogger(__name__)


def _build_sites(args) -> list[SiteConfig] | None:
    """Build site list from CLI args, reference API, or vendordata."""
    if args.auth_url:
        return [SiteConfig(
            auth_url=args.auth_url,
            region_name=args.region_name or "",
            project_id=args.project_id or "",
            identity_provider=args.identity_provider,
            protocol=args.protocol,
            cloud_name=args.cloud_name,
            client_id=args.client_id,
            discovery_endpoint=args.discovery_endpoint,
        )]

    # Try reference API first, then vendordata
    sites = from_reference_api(
        api_url=args.sites_api_url,
        client_id=args.client_id,
        discovery_endpoint=args.discovery_endpoint,
        project_id=args.project_id or "",
    )
    if sites:
        return sites

    logger.debug("Reference API unavailable, trying vendordata")
    sites = from_vendordata(
        metadata_url=args.metadata_url,
        client_id=args.client_id,
        discovery_endpoint=args.discovery_endpoint,
    )
    if sites:
        return sites

    logger.error(
        "No site config found. Provide --auth-url or ensure the "
        "reference API or vendordata is accessible."
    )
    return None


def _trigger_auth(site: SiteConfig) -> None:
    plugin = ChameleonDeviceAuth(
        auth_url=site.auth_url,
        identity_provider=site.identity_provider,
        protocol=site.protocol,
        client_id=site.client_id,
        discovery_endpoint=site.discovery_endpoint,
        scope="openid",
        project_id=site.project_id,
    )
    sess = Session(auth=plugin)
    sess.get_token()


def _cmd_login(args) -> int:
    sites = _build_sites(args)
    if not sites:
        return 1
    try:
        _trigger_auth(sites[0])
    except KeyboardInterrupt:
        logger.error("\nAuthentication cancelled.")
        return 1
    except Exception as e:
        logger.error("Authentication failed: %s", e)
        logger.debug("Details:", exc_info=True)
        return 1
    return 0


def _cmd_logout(args) -> int:
    if clear_cache():
        logger.info("Cleared cached refresh token.")
    else:
        logger.info("No cached token found.")
    return 0


def _cmd_clouds_yaml(args) -> int:
    sites = _build_sites(args)
    if not sites:
        return 1
    if write_clouds_yaml(sites, Path(args.output), force=args.force):
        logger.info("Wrote clouds.yaml to %s", args.output)
    return 0


def _cmd_openrc(args) -> int:
    sites = _build_sites(args)
    if not sites:
        return 1
    if write_openrc_file(sites[0], Path(args.output), force=args.force):
        logger.info("Wrote openrc to %s", args.output)
    return 0


def _add_site_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auth-url", help="Keystone auth URL (skips discovery)")
    parser.add_argument("--region-name", help="OpenStack region name")
    parser.add_argument("--project-id", help="OpenStack project ID")
    parser.add_argument("--identity-provider", default="chameleon")
    parser.add_argument("--protocol", default="openid")
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    parser.add_argument(
        "--discovery-endpoint", default=DEFAULT_DISCOVERY_ENDPOINT,
        help="Keycloak OIDC discovery URL (default: %(default)s)",
    )
    parser.add_argument(
        "--cloud-name", default="chameleon",
        help="Cloud name in clouds.yaml (default: chameleon)",
    )
    parser.add_argument(
        "--sites-api-url", default=SITES_API_URL,
        help="Chameleon reference API URL (default: %(default)s)",
    )
    parser.add_argument(
        "--metadata-url", default=VENDORDATA_URL,
        help="Metadata service URL for vendordata (default: %(default)s)",
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="ccauth",
        description="Chameleon OIDC device flow authentication.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    sub = parser.add_subparsers(dest="command")

    login_p = sub.add_parser("login", help="Authenticate via OIDC device flow")
    _add_site_args(login_p)

    sub.add_parser("logout", help="Clear cached refresh tokens")

    clouds_p = sub.add_parser("clouds-yaml", help="Write a clouds.yaml file")
    _add_site_args(clouds_p)
    clouds_p.add_argument("--output", required=True, help="Output file path")
    clouds_p.add_argument(
        "--force", action="store_true", help="Overwrite existing entries",
    )

    openrc_p = sub.add_parser("openrc", help="Write an openrc file")
    _add_site_args(openrc_p)
    openrc_p.add_argument("--output", required=True, help="Output file path")
    openrc_p.add_argument(
        "--force", action="store_true", help="Overwrite existing entries",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s: %(message)s" if args.debug else "%(message)s",
        stream=sys.stderr,
    )

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "login": _cmd_login,
        "logout": _cmd_logout,
        "clouds-yaml": _cmd_clouds_yaml,
        "openrc": _cmd_openrc,
    }
    return commands[args.command](args)
