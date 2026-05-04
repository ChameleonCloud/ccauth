"""URL helpers for Keystone auth endpoints."""


def auth_url_base(url: str) -> str:
    """Strip trailing /v3 and slashes from a Keystone auth URL."""
    return url.rstrip("/").removesuffix("/v3").rstrip("/")


def auth_url_v3(url: str) -> str:
    """Ensure a Keystone auth URL ends with /v3."""
    base = url.rstrip("/")
    return base if base.endswith("/v3") else f"{base}/v3"
