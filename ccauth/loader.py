"""keystoneauth1 loader for ChameleonDeviceAuth.

Extends the upstream OidcDeviceAuthorization loader, only overriding
the plugin class. All options are inherited.
"""

from keystoneauth1.loading._plugins.identity.v3 import (
    OpenIDConnectDeviceAuthorization,
)

from ccauth.plugin import ChameleonDeviceAuth


class ChameleonDeviceAuthLoader(OpenIDConnectDeviceAuthorization):
    """keystoneauth1 loader that substitutes ChameleonDeviceAuth as the plugin class."""

    @property
    def plugin_class(self):
        return ChameleonDeviceAuth
