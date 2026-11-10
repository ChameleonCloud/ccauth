import stat
from unittest.mock import MagicMock

import pytest

import ccauth.plugin as plugin_mod
from ccauth.plugin import (
    ChameleonDeviceAuth,
    _load_refresh_token,
    _save_refresh_token,
    refresh_token_cache_path,
)

PROD_IDP = "https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration"
DEV_IDP = "https://auth.dev.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration"


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_mod, "_STATE_DIR", tmp_path)
    monkeypatch.setattr(plugin_mod, "LEGACY_REFRESH_TOKEN_CACHE", tmp_path / "refresh_token.json")
    return tmp_path


def _plugin(auth_url, discovery_endpoint, client_id="chi-cli-device-token"):
    return ChameleonDeviceAuth(
        auth_url=auth_url,
        identity_provider="chameleon",
        protocol="openid",
        client_id=client_id,
        discovery_endpoint=discovery_endpoint,
    )


def _mock_refresh(plugin, new_refresh_token, calls):
    """Make the refresh_token grant succeed without network access."""

    def fake_access_token(session, payload):
        calls.append(payload)
        plugin._last_token_response = {"refresh_token": new_refresh_token}
        return "access"

    plugin._get_access_token = fake_access_token
    plugin._get_keystone_token = MagicMock(return_value=MagicMock())


def test_save_and_load_refresh_token(tmp_path):
    cache = tmp_path / "refresh_token.json"
    _save_refresh_token(cache, "tok123")
    assert _load_refresh_token(cache) == "tok123"


def test_save_refresh_token_mode(tmp_path):
    cache = tmp_path / "refresh_token.json"
    _save_refresh_token(cache, "tok")
    mode = stat.S_IMODE(cache.stat().st_mode)
    assert mode == 0o600


def test_load_refresh_token_missing(tmp_path):
    assert _load_refresh_token(tmp_path / "nonexistent.json") is None


def test_load_refresh_token_corrupt(tmp_path):
    cache = tmp_path / "refresh_token.json"
    cache.write_text("not json")
    assert _load_refresh_token(cache) is None


def test_cache_path_differs_per_idp(state_dir):
    assert refresh_token_cache_path(PROD_IDP, "c") != refresh_token_cache_path(DEV_IDP, "c")


def test_cache_path_differs_per_client(state_dir):
    assert refresh_token_cache_path(PROD_IDP, "a") != refresh_token_cache_path(PROD_IDP, "b")


def test_cache_path_shared_across_sites_with_same_idp(state_dir):
    uc = _plugin("https://chi.uc.chameleoncloud.org:5000/v3", PROD_IDP)
    edge = _plugin("https://chi.edge.chameleoncloud.org:5000/v3", PROD_IDP)
    assert uc.refresh_token_cache == edge.refresh_token_cache


def test_different_idps_do_not_overwrite_each_other(state_dir, monkeypatch):
    """Regression test for issue #9."""
    monkeypatch.setattr(plugin_mod.access, "create", MagicMock())
    prod = _plugin("https://chi.edge.chameleoncloud.org:5000/v3", PROD_IDP)
    dev = _plugin("https://dev.edge.chameleoncloud.org:5000/v3", DEV_IDP)
    _save_refresh_token(prod.refresh_token_cache, "prod-tok")
    _save_refresh_token(dev.refresh_token_cache, "dev-tok")

    prod_calls, dev_calls = [], []
    _mock_refresh(prod, "prod-tok-2", prod_calls)
    _mock_refresh(dev, "dev-tok-2", dev_calls)
    prod.get_unscoped_auth_ref(MagicMock())
    dev.get_unscoped_auth_ref(MagicMock())

    assert prod_calls[0]["refresh_token"] == "prod-tok"
    assert dev_calls[0]["refresh_token"] == "dev-tok"
    assert _load_refresh_token(prod.refresh_token_cache) == "prod-tok-2"
    assert _load_refresh_token(dev.refresh_token_cache) == "dev-tok-2"


def test_legacy_cache_is_migrated(state_dir, monkeypatch):
    monkeypatch.setattr(plugin_mod.access, "create", MagicMock())
    legacy = state_dir / "refresh_token.json"
    _save_refresh_token(legacy, "old-tok")
    prod = _plugin("https://chi.uc.chameleoncloud.org:5000/v3", PROD_IDP)
    calls = []
    _mock_refresh(prod, "new-tok", calls)

    prod.get_unscoped_auth_ref(MagicMock())

    assert calls[0]["refresh_token"] == "old-tok"
    assert _load_refresh_token(prod.refresh_token_cache) == "new-tok"
    assert not legacy.exists()
