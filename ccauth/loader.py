"""keystoneauth1 loader for ChameleonDeviceAuth.

Registers the plugin options so 'auth_type: v3chameleonoidc' works in
clouds.yaml and is recognized by any openstack tool using keystoneauth1.
"""
from keystoneauth1 import exceptions, loading

from ccauth.plugin import ChameleonDeviceAuth


class ChameleonDeviceAuthLoader(loading.BaseFederationLoader):
    """Loader for ChameleonDeviceAuth.

    Defines the options that map to ChameleonDeviceAuth constructor params.
    BaseFederationLoader already provides: auth_url, identity_provider,
    protocol, project_id, domain_id, and the other V3 scoping options.
    """

    @property
    def plugin_class(self):
        return ChameleonDeviceAuth

    def get_options(self):
        options = super().get_options()
        options.extend(
            [
                loading.Opt("client-id", help="OAuth 2.0 Client ID", required=True),
                loading.Opt(
                    "openid-scope",
                    default="openid",
                    dest="scope",
                    help="OpenID Connect scope (default: openid)",
                ),
                loading.Opt(
                    "discovery-endpoint",
                    help="OpenID Connect Discovery Document URL",
                ),
                loading.Opt(
                    "access-token-endpoint",
                    help="Token endpoint URL (overrides discovery)",
                ),
                loading.Opt(
                    "access-token-type",
                    default="access_token",
                    help="Token type to send to Keystone: access_token or id_token",
                ),
            ]
        )
        return options

    def load_from_options(self, **kwargs):
        if not (
            kwargs.get("access_token_endpoint") or kwargs.get("discovery_endpoint")
        ):
            raise exceptions.OptionError(
                "Provide either access-token-endpoint or discovery-endpoint."
            )
        return super().load_from_options(**kwargs)
