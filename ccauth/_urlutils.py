"""URL helpers for Keystone auth endpoints."""


def auth_url_base(url: str) -> str:
    """Strip trailing /v3 and slashes from a Keystone auth URL."""
    return url.rstrip("/").removesuffix("/v3").rstrip("/")
