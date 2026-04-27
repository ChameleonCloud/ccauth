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
from .appcred import (
    AppCredConfig,
    ensure_app_cred,
    write_clouds_yaml as _write_clouds_yaml_appcred,
    write_openrc as _write_openrc_appcred,
)
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
        return [
            SiteConfig(
                auth_url=args.auth_url,
                region_name=args.region_name or "",
                project_id=args.project_id or "",
                identity_provider=args.identity_provider,
                protocol=args.protocol,
                cloud_name=args.cloud_name,
                client_id=args.client_id,
                discovery_endpoint=args.discovery_endpoint,
            )
        ]

    # Collect sites from both sources independently
    sites = list(
        from_reference_api(
            api_url=args.sites_api_url,
            client_id=args.client_id,
            discovery_endpoint=args.discovery_endpoint,
        )
    )

    vd_sites = from_vendordata(
        metadata_url=args.metadata_url,
        client_id=args.client_id,
        discovery_endpoint=args.discovery_endpoint,
    )

    # If the vendordata site isn't in the reference API (e.g. KVM, edge), append it
    if vd_sites:
        vd = vd_sites[0]
        if not any(s.auth_url == vd.auth_url for s in sites):
            sites.append(vd)

    if not sites:
        logger.error(
            "No site config found. Provide --auth-url or ensure the "
            "reference API or vendordata is accessible."
        )
        return None

    # Apply project_id: explicit flag wins, otherwise use vendordata
    project_id = args.project_id or (vd_sites[0].project_id if vd_sites else "")
    if project_id:
        for site in sites:
            site.project_id = project_id

    return sites


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
    # Prefer the current site (vendordata) for login — it's guaranteed to work
    # for the user's account. Fall back to sites[0] when not on an instance.
    vd_sites = from_vendordata(
        metadata_url=args.metadata_url,
        client_id=args.client_id,
        discovery_endpoint=args.discovery_endpoint,
    )
    if vd_sites:
        vd_auth_url = vd_sites[0].auth_url
        login_site = next((s for s in sites if s.auth_url == vd_auth_url), sites[0])
    else:
        login_site = sites[0]
    try:
        _trigger_auth(login_site)
    except KeyboardInterrupt:
        logger.error("\nAuthentication cancelled.")
        return 1
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Authentication failed: %s", e)
        logger.debug("Details:", exc_info=True)
        return 1
    logger.info("Authenticated successfully. Refresh token cached.")
    clouds_yaml = Path("~/.config/openstack/clouds.yaml").expanduser()
    if not clouds_yaml.exists():
        logger.info(
            "Next: run 'ccauth clouds-yaml --output %s' to set up OpenStack credentials.",
            clouds_yaml,
        )
    else:
        logger.info("Run 'openstack <command>' to interact with Chameleon.")
    return 0


def _cmd_logout(_args) -> int:
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


def _cmd_cc_login(args) -> int:
    """cc-login: device flow → app credential → openrc/clouds.yaml."""
    auth_url = args.auth_url
    region_name = args.region_name or ""
    project_id = args.project_id or ""

    if not auth_url:
        sites = from_vendordata(
            metadata_url=args.metadata_url,
            client_id=args.client_id,
            discovery_endpoint=args.discovery_endpoint,
        )
        if sites:
            site = sites[0]
            auth_url = site.auth_url
            region_name = region_name or site.region_name
            project_id = project_id or site.project_id
        else:
            logger.error(
                "No site config found. Provide --auth-url or run on a Chameleon instance."
            )
            return 1

    config = AppCredConfig(
        auth_url=auth_url,
        region_name=region_name,
        project_id=project_id,
        identity_provider=args.identity_provider,
        protocol=args.protocol,
        client_id=args.client_id,
        discovery_endpoint=args.discovery_endpoint,
        app_cred_name=args.app_cred_name,
        app_cred_expires_in_hours=args.app_cred_expires_hours,
        app_cred_cache_path=Path(args.app_cred_cache_path).expanduser(),
        ttl_seconds=args.ttl_seconds,
    )

    try:
        app_cred = ensure_app_cred(config, force_refresh=args.force_refresh)
    except KeyboardInterrupt:
        logger.error("\nAuthentication cancelled.")
        return 1
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Authentication failed: %s", e)
        logger.debug("Details:", exc_info=True)
        return 1

    cred_id = app_cred.get("id") or app_cred.get("application_credential_id")
    logger.info("Application credential: %s", app_cred.get("name"))
    logger.info("Credential ID: %s", cred_id)
    if app_cred.get("expires_at"):
        logger.info("Expires at: %s", app_cred["expires_at"])

    if args.output_openrc:
        if _write_openrc_appcred(
            app_cred, args.output_openrc,
            config.auth_url, config.region_name,
            force=args.force_openrc,
        ):
            logger.info("Written openrc to %s", args.output_openrc)

    if args.output_clouds_yaml:
        if _write_clouds_yaml_appcred(
            app_cred, args.output_clouds_yaml, args.cloud_name,
            config.auth_url, config.region_name,
            force=args.force_clouds_yaml,
        ):
            logger.info("Updated clouds.yaml at %s", args.output_clouds_yaml)

    if not args.output_openrc and not args.output_clouds_yaml:
        logger.info("No output files requested. To use these credentials:")
        logger.info("  cc-login --output-openrc ~/openrc")
        logger.info("  cc-login --output-clouds-yaml ~/clouds.yaml")

    return 0


def _add_site_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--auth-url", help="Keystone auth URL (skips discovery)")
    parser.add_argument("--region-name", help="OpenStack region name")
    parser.add_argument("--project-id", help="OpenStack project ID")
    parser.add_argument("--identity-provider", default="chameleon")
    parser.add_argument("--protocol", default="openid")
    parser.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    parser.add_argument(
        "--discovery-endpoint",
        default=DEFAULT_DISCOVERY_ENDPOINT,
        help="Keycloak OIDC discovery URL (default: %(default)s)",
    )
    parser.add_argument(
        "--cloud-name",
        default="chameleon",
        help="Cloud name in clouds.yaml (default: chameleon)",
    )
    parser.add_argument(
        "--sites-api-url",
        default=SITES_API_URL,
        help="Chameleon reference API URL (default: %(default)s)",
    )
    parser.add_argument(
        "--metadata-url",
        default=VENDORDATA_URL,
        help="Metadata service URL for vendordata (default: %(default)s)",
    )


def _setup_cc_login_parser(parser: argparse.ArgumentParser) -> None:
    """Set up arguments for cc-login compatibility mode."""
    parser.add_argument("--output-openrc", metavar="FILE", help="Write openrc file")
    parser.add_argument(
        "--output-clouds-yaml", metavar="FILE", help="Write clouds.yaml file"
    )
    parser.add_argument(
        "--force-refresh", action="store_true", help="Bypass cache and re-authenticate"
    )
    parser.add_argument(
        "--force-openrc", action="store_true", help="Overwrite existing openrc file"
    )
    parser.add_argument(
        "--force-clouds-yaml",
        action="store_true",
        help="Overwrite existing clouds.yaml entry",
    )
    parser.add_argument(
        "--app-cred-name", default="chi-device-flow-auth", help="App credential name prefix"
    )
    parser.add_argument(
        "--app-cred-expires-hours",
        type=int,
        default=24,
        help="App credential expiry in hours (default: 24)",
    )
    parser.add_argument(
        "--app-cred-cache-path",
        default="~/.cache/ccauth/chameleon-app-cred.json",
        help="Path to app credential cache",
    )
    parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=86400,
        help="Local cache TTL in seconds (default: 86400)",
    )
    _add_site_args(parser)


def _setup_subcommand_parsers(parser: argparse.ArgumentParser) -> None:
    sub = parser.add_subparsers(dest="command")

    login_p = sub.add_parser("login", help="Authenticate via OIDC device flow")
    _add_site_args(login_p)

    sub.add_parser("logout", help="Clear cached refresh tokens")

    clouds_p = sub.add_parser("clouds-yaml", help="Write a clouds.yaml file")
    _add_site_args(clouds_p)
    clouds_p.add_argument("--output", required=True, help="Output file path")
    clouds_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing entries",
    )

    openrc_p = sub.add_parser("openrc", help="Write an openrc file")
    _add_site_args(openrc_p)
    openrc_p.add_argument("--output", required=True, help="Output file path")
    openrc_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing entries",
    )


def _setup_logging(debug: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if debug else logging.INFO,
        format="%(levelname)s: %(message)s" if debug else "%(message)s",
        stream=sys.stderr,
    )


def main(argv=None, use_cc_login_compat=False) -> int:
    """Parse arguments and dispatch to the appropriate subcommand handler."""
    parser = argparse.ArgumentParser(
        prog="ccauth" if not use_cc_login_compat else "cc-login",
        description="Chameleon OIDC device flow authentication.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )

    if use_cc_login_compat:
        _setup_cc_login_parser(parser)
        args = parser.parse_args(argv)
        _setup_logging(args.debug)
        return _cmd_cc_login(args)

    _setup_subcommand_parsers(parser)
    args = parser.parse_args(argv)
    _setup_logging(args.debug)

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


def main_cc_login(argv=None) -> int:
    """Entry point for cc-login command (compatibility wrapper)."""
    return main(argv, use_cc_login_compat=True)
