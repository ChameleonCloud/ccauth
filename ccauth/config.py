"""Site identity dataclass."""

from dataclasses import dataclass


@dataclass
class SiteConfig:
    """Keystone auth info fetchable from ReferenceApi."""

    auth_url: str
    region_name: str
    cloud_name: str