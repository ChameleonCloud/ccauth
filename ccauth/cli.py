"""CLI entrypoint for ccauth.

Runs the OIDC device flow to cache a refresh token, then writes
clouds.yaml / openrc files using the v3chameleonoidc auth type.
On subsequent runs the refresh token is used silently.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional

from keystoneauth1.session import Session

from .auth import AuthConfig, SiteConfig, write_clouds_yaml, write_openrc_file
from .plugin import ChameleonDeviceAuth

logger = logging.getLogger(__name__)

DEFAULT_METADATA_URL = "http://169.254.169.254/openstack/latest/vendor_data2.json"
DEFAULT_DISCOVERY_ENDPOINT = (
    "https://auth.chameleoncloud.org/auth/realms/chameleon"
    "/.well-known/openid-configuration"
)
DEFAULT_CLIENT_ID = "chi-cli-device-token"


def _trigger_auth(site: SiteConfig) -> None:
    """Run auth against a site to ensure the refresh token gets cached.

    On first call this triggers the interactive device flow.
    On subsequent calls the cached refresh token is used silently.
    """
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


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="cc-login",
        description=(
            "Authenticate to Chameleon via OIDC device flow and write "
            "clouds.yaml / openrc files. On first run you will be prompted "
            "to visit a URL. Subsequent runs refresh silently."
        ),
    )

    p.add_argument(
        "--metadata-url",
        default=DEFAULT_METADATA_URL,
        help="Metadata service URL for vendordata (default: %(default)s)",
    )

    # Manual site config (overrides vendordata)
    p.add_argument("--auth-url", help="Keystone auth URL")
    p.add_argument("--region-name", help="OpenStack region name")
    p.add_argument("--project-id", help="OpenStack project ID")
    p.add_argument("--identity-provider", default="chameleon")
    p.add_argument("--protocol", default="openid")
    p.add_argument("--client-id", default=DEFAULT_CLIENT_ID)
    p.add_argument(
        "--discovery-endpoint",
        default=DEFAULT_DISCOVERY_ENDPOINT,
        help="Keycloak OIDC discovery URL (default: %(default)s)",
    )
    p.add_argument(
        "--cloud-name",
        default="chameleon",
        help="Cloud name in clouds.yaml (default: chameleon)",
    )

    # Output files
    p.add_argument("--output-clouds-yaml", help="Write clouds.yaml to this path")
    p.add_argument("--output-openrc", help="Write openrc to this path")
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing cloud entries / openrc files",
    )

    p.add_argument("--debug", action="store_true", help="Enable debug logging")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s: %(message)s" if args.debug else "%(message)s",
        stream=sys.stderr,
    )

    # Build site config: CLI args override vendordata
    if args.auth_url:
        sites = [
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
    else:
        logger.warning(
            "No --auth-url provided; fetching site config from vendordata at %s",
            args.metadata_url,
        )
        config = AuthConfig.from_vendordata(args.metadata_url)
        sites = config.sites
        if not sites:
            logger.error(
                "No site config found. Provide --auth-url or ensure "
                "vendordata is accessible at %s",
                args.metadata_url,
            )
            return 1

    # Trigger auth against the first site to seed the refresh token cache.
    # (All sites share one Keycloak so one device flow covers all of them.)
    _trigger_auth(sites[0])

    if args.output_clouds_yaml:
        if write_clouds_yaml(
            sites=sites,
            output_path=Path(args.output_clouds_yaml),
            force=args.force,
        ):
            logger.info("Wrote clouds.yaml to %s", args.output_clouds_yaml)

    if args.output_openrc:
        if write_openrc_file(
            site=sites[0],
            output_path=Path(args.output_openrc),
            force=args.force,
        ):
            logger.info("Wrote openrc to %s", args.output_openrc)

    if not args.output_clouds_yaml and not args.output_openrc:
        logger.info(
            "Authentication cached. To generate config files:\n"
            "  cc-login --output-clouds-yaml ~/.config/openstack/clouds.yaml\n"
            "  cc-login --output-openrc ~/openrc"
        )

    return 0
