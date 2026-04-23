"""CLI entrypoint for ccauth.

Subcommands:
  login             — Authenticate via OIDC device flow
  logout            — Clear cached refresh tokens
  clouds-yaml       — Write a clouds.yaml file for all sites
  openrc            — Write an openrc file for the current site only
  discover-projects — Interactive project picker and clouds.yaml generator
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

from keystoneauth1.session import Session

from . import __version__
from .appcred import (
    AppCredConfig,
    ensure_app_cred,
    write_clouds_yaml as _write_clouds_yaml_appcred,  # v3applicationcredential (cc-login)
    write_openrc as _write_openrc_appcred,            # v3applicationcredential (cc-login)
)
from .config import SiteConfig
from .discover import (
    DEFAULT_CLIENT_ID,
    DEFAULT_DISCOVERY_ENDPOINT,
    SITES_API_URL,
    VENDORDATA_URL,
    base_url,
    from_reference_api,
    from_vendordata,
    list_projects_at,
)
from .plugin import REFRESH_TOKEN_CACHE, ChameleonDeviceAuth, clear_cache
from .writers import write_clouds_yaml, write_openrc_file  # v3chameleonoidc (ccauth)

logger = logging.getLogger(__name__)


def _current_site(sites: list[SiteConfig], region_name: str, vd_sites: list[SiteConfig]):
    """Return the site matching region_name, vendordata, or None."""
    if region_name:
        return next((s for s in sites if s.region_name == region_name), None)
    if vd_sites:
        return next(
            (s for s in sites if base_url(s.auth_url) == base_url(vd_sites[0].auth_url)),
            None,
        )
    return None


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

    # Collect sites from both sources independently.
    # Reference API sites carry no auth config; stamp it in from args.
    sites = from_reference_api(api_url=args.sites_api_url)
    for site in sites:
        site.client_id = args.client_id
        site.discovery_endpoint = args.discovery_endpoint

    vd_sites = from_vendordata(metadata_url=args.metadata_url)

    # Merge vendordata site. If the site already exists in the reference API,
    # keep one entry and prefer whichever cloud_name isn't "chameleon".
    # If absent (KVM, edge, etc.), append it.
    if vd_sites:
        vd = vd_sites[0]
        match = next((s for s in sites if base_url(s.auth_url) == base_url(vd.auth_url)), None)
        if match is None:
            sites.append(vd)
        elif match.cloud_name == "chameleon" and vd.cloud_name != "chameleon":
            match.cloud_name = vd.cloud_name

    if not sites:
        logger.error(
            "No site config found. Provide --auth-url or ensure the "
            "reference API or vendordata is accessible."
        )
        return None

    # Apply project_id to the current site so _enrich_project_ids can use it
    # as a seed to discover the matching ID at every other site.
    # If no current site can be identified, apply it to all sites.
    project_id = args.project_id or (vd_sites[0].project_id if vd_sites else "")
    if project_id:
        current = _current_site(sites, args.region_name, vd_sites)
        if current:
            current.project_id = project_id
        else:
            for site in sites:
                site.project_id = project_id

    return sites


def _list_projects_at(site: SiteConfig) -> list[dict]:
    """Return Keystone projects available at a site via unscoped OIDC auth."""
    plugin = ChameleonDeviceAuth(
        auth_url=site.auth_url,
        identity_provider=site.identity_provider,
        protocol=site.protocol,
        client_id=site.client_id,
        discovery_endpoint=site.discovery_endpoint,
        scope="openid",
    )
    sess = Session(auth=plugin)
    try:
        return list_projects_at(sess)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Could not list projects at %s: %s", site.auth_url, exc)
        return []


def _enrich_project_ids(sites: list[SiteConfig]) -> None:
    """Discover project_id at each site by matching the current site's project name."""
    if not REFRESH_TOKEN_CACHE.expanduser().exists():
        logger.debug("No cached token; skipping project ID discovery.")
        return

    current = next((s for s in sites if s.project_id), None)
    if not current:
        return

    all_projects = _list_projects_at(current)
    current_project = next((p for p in all_projects if p["id"] == current.project_id), None)
    if not current_project:
        logger.debug("Could not resolve name for project %s", current.project_id)
        return

    project_name = current_project["name"]
    logger.debug("Discovering project '%s' across all sites", project_name)

    for site in sites:
        if site.project_id:
            continue
        match = next(
            (p for p in _list_projects_at(site) if p["name"] == project_name),
            None,
        )
        if match:
            site.project_id = match["id"]
            logger.debug("Found '%s' at %s: %s", project_name, site.region_name, match["id"])
        else:
            logger.debug("Project '%s' not found at %s", project_name, site.region_name)


def _discover_projects(sites: list[SiteConfig]) -> dict[str, list[SiteConfig]]:
    """Return {project_name: [SiteConfig, ...]} for every project at every site.

    SiteConfigs have project_id set and cloud_name left as the site name —
    callers are responsible for setting final cloud_name values.
    """
    if not REFRESH_TOKEN_CACHE.expanduser().exists():
        logger.error("No cached token. Run 'ccauth login' first.")
        return {}

    result: dict[str, list[SiteConfig]] = {}
    for site in sites:
        for project in _list_projects_at(site):
            result.setdefault(project["name"], []).append(SiteConfig(
                auth_url=site.auth_url,
                region_name=site.region_name,
                cloud_name=site.cloud_name,
                client_id=site.client_id,
                discovery_endpoint=site.discovery_endpoint,
                project_id=project["id"],
                identity_provider=site.identity_provider,
                protocol=site.protocol,
            ))
    return result


def _collect_all_projects(sites: list[SiteConfig]) -> list[SiteConfig]:
    """Return one SiteConfig per (site, project) pair with slugged cloud names."""
    by_project = _discover_projects(sites)
    if not by_project:
        return []
    result = []
    for project_name, project_sites in by_project.items():
        for site in project_sites:
            slug = re.sub(r"[^a-z0-9]+", "_", f"{site.cloud_name}_{project_name}".lower()).strip("_")
            result.append(SiteConfig(
                auth_url=site.auth_url,
                region_name=site.region_name,
                cloud_name=slug,
                client_id=site.client_id,
                discovery_endpoint=site.discovery_endpoint,
                project_id=site.project_id,
                identity_provider=site.identity_provider,
                protocol=site.protocol,
            ))
    return result


def _parse_selection(raw: str, project_names: list[str]) -> list[str] | None:
    """Parse user input into a list of selected project names, or None on error."""
    if raw.lower() == "all":
        return list(project_names)
    selected = []
    for token in raw.split():
        try:
            idx = int(token) - 1
        except ValueError:
            logger.error("Invalid input: %s", token)
            return None
        if 0 <= idx < len(project_names):
            selected.append(project_names[idx])
        else:
            logger.error("Invalid selection: %s", token)
            return None
    if not selected:
        logger.error("No projects selected.")
        return None
    return selected


def _build_output_sites(
    selected: list[str], by_project: dict[str, list[SiteConfig]]
) -> list[SiteConfig]:
    """Build the final SiteConfig list for writing, with appropriate cloud names."""
    multi = len(selected) > 1
    result = []
    for project_name in selected:
        for site in by_project[project_name]:
            if multi:
                slug = f"{site.cloud_name}_{project_name}".lower()
                cloud_name = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
            else:
                cloud_name = site.cloud_name
            result.append(SiteConfig(
                auth_url=site.auth_url,
                region_name=site.region_name,
                cloud_name=cloud_name,
                client_id=site.client_id,
                discovery_endpoint=site.discovery_endpoint,
                project_id=site.project_id,
                identity_provider=site.identity_provider,
                protocol=site.protocol,
            ))
    return result


def _cmd_discover_projects(args) -> int:
    """Interactive project picker: discover available projects and write a clouds.yaml."""
    if not REFRESH_TOKEN_CACHE.expanduser().exists():
        logger.error("Not logged in. Run 'ccauth login' first.")
        return 1

    sites = _build_sites(args)
    if not sites:
        return 1

    logger.info("Discovering projects across all sites...")
    by_project = _discover_projects(sites)
    if not by_project:
        logger.error("No projects found.")
        return 1

    project_names = sorted(by_project)
    print("\nAvailable projects:")
    for i, name in enumerate(project_names, 1):
        site_names = ", ".join(s.cloud_name for s in by_project[name])
        print(f"  {i}. {name}  [{site_names}]")

    print("\nEnter number(s) to include (e.g. '1', '1 2'), or 'all': ", end="", flush=True)
    try:
        raw = input().strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return 1

    selected = _parse_selection(raw, project_names)
    if selected is None:
        return 1

    output_sites = _build_output_sites(selected, by_project)
    output_path = Path(args.output).expanduser()
    if write_clouds_yaml(output_sites, output_path, force=args.force):
        suffix = "y" if len(output_sites) == 1 else "ies"
        logger.info("Wrote %d cloud entr%s to %s", len(output_sites), suffix, output_path)
        logger.info("Set OS_CLOUD and run 'openstack <command>' to interact with Chameleon.")
        logger.info("Verify no other OS_ environment variables are set that might interfere with authentication.")
    return 0


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
    vd_sites = [] if args.region_name else from_vendordata(metadata_url=args.metadata_url)
    login_site = _current_site(sites, args.region_name, vd_sites) or sites[0]
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
        logger.info("Set OS_CLOUD and run 'openstack <command>' to interact with Chameleon.")
        logger.info("Verify no other OS_ environment variables are set that might interfere with authentication.")
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
    if args.all_projects:
        sites = _collect_all_projects(sites)
        if not sites:
            return 1
    else:
        _enrich_project_ids(sites)
    if write_clouds_yaml(sites, Path(args.output), force=args.force):
        logger.info("Wrote clouds.yaml to %s", args.output)
        logger.info("Set OS_CLOUD and run 'openstack <command>' to interact with Chameleon.")
        logger.info("Verify no other OS_ environment variables are set that might interfere with authentication.")
    return 0


def _cmd_openrc(args) -> int:
    if args.auth_url:
        site = SiteConfig(
            auth_url=args.auth_url,
            region_name=args.region_name or "",
            project_id=args.project_id or "",
            identity_provider=args.identity_provider,
            protocol=args.protocol,
            cloud_name=args.cloud_name,
            client_id=args.client_id,
            discovery_endpoint=args.discovery_endpoint,
        )
    else:
        vd_sites = from_vendordata(metadata_url=args.metadata_url)
        if not vd_sites:
            logger.error(
                "Could not determine current site. "
                "Provide --auth-url or run on a Chameleon instance."
            )
            return 1
        site = vd_sites[0]
        if args.project_id:
            site.project_id = args.project_id

    if write_openrc_file(site, Path(args.output), force=args.force):
        logger.info("Wrote openrc to %s (current site only).", args.output)
        logger.info("Source this file to set credentials. For multi-site, use 'ccauth clouds-yaml'.")
    return 0


def _cmd_cc_login(args) -> int:
    """cc-login: device flow → app credential → openrc/clouds.yaml."""
    auth_url = args.auth_url
    region_name = args.region_name or ""
    project_id = args.project_id or ""

    if not auth_url:
        sites = from_vendordata(metadata_url=args.metadata_url)
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
    parser.add_argument(
        "--auth-url",
        help="Keystone auth URL. Skips site discovery and targets this site only.",
    )
    parser.add_argument(
        "--region-name",
        help=(
            "OpenStack region name. With --auth-url, sets the region on that site. "
            "Without --auth-url, identifies the current site for login/project seeding "
            "(does not filter the site list for clouds-yaml)."
        ),
    )
    parser.add_argument(
        "--project-id",
        help=(
            "OpenStack project ID. With --auth-url, applies to that site directly. "
            "Without --auth-url, seeds cross-site project discovery for clouds-yaml "
            "(ignored when --all-projects is used)."
        ),
    )
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
        help=(
            "Cloud name written to clouds.yaml. Only applies when --auth-url is used "
            "(single-site mode). Ignored when discovering all sites. (default: chameleon)"
        ),
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

    clouds_p = sub.add_parser("clouds-yaml", help="Write a clouds.yaml file for all sites")
    _add_site_args(clouds_p)
    clouds_p.add_argument("--output", required=True, help="Output file path")
    clouds_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing entries",
    )
    clouds_p.add_argument(
        "--all-projects",
        action="store_true",
        help=(
            "Generate an entry for every project at every site, named <site>_<project>. "
            "Requires a cached token. Overrides --project-id and --cloud-name."
        ),
    )

    discover_p = sub.add_parser(
        "discover-projects",
        help="Interactively discover projects and write a clouds.yaml file",
    )
    _add_site_args(discover_p)
    discover_p.add_argument(
        "--output",
        default="~/.config/openstack/clouds.yaml",
        help="Output file path (default: %(default)s)",
    )
    discover_p.add_argument("--force", action="store_true", help="Overwrite existing entries")

    openrc_p = sub.add_parser(
        "openrc",
        help="Write an openrc file for the current site only",
        description=(
            "Write a bash-sourceable openrc file for a single site. "
            "Unlike clouds-yaml, openrc only supports one site at a time. "
            "Run this on each site you want credentials for, or use "
            "clouds-yaml to configure all sites at once."
        ),
    )
    _add_site_args(openrc_p)
    openrc_p.add_argument("--output", required=True, help="Output file path (single site only)")
    openrc_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing file",
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
        "discover-projects": _cmd_discover_projects,
    }
    return commands[args.command](args)


def main_cc_login(argv=None) -> int:
    """Entry point for cc-login command (compatibility wrapper)."""
    return main(argv, use_cc_login_compat=True)
