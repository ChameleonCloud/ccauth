import logging
import stat
import time
from unittest.mock import MagicMock

import pytest
from keystoneauth1 import exceptions

import ccauth.plugin as plugin_mod
from ccauth.plugin import (
    KEYSTONE_TIMEOUT,
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


# --- Keystone exchange: timeout and failure handling ---

AUTH_URL = "https://chi.edge.example.org:5000/v3"


def _polling_plugin():
    p = ChameleonDeviceAuth(
        auth_url=AUTH_URL,
        identity_provider="chameleon",
        protocol="openid",
        client_id="client",
        discovery_endpoint="https://kc.example.org/.well-known/openid-configuration",
    )
    # Skip network discovery / device authorization; go straight to polling.
    p._get_discovery_document = lambda session: {}
    p._get_access_token_endpoint = lambda session: "https://kc.example.org/token"
    p.get_payload = lambda session: {"device_code": "dc"}
    p.verification_uri_complete = "https://kc.example.org/device?code=X"
    p.timeout = time.time() + 60
    return p


def _token_response(refresh_token):
    resp = MagicMock()
    resp.json.return_value = {"access_token": "at", "refresh_token": refresh_token}
    return resp


@pytest.fixture
def cache(state_dir):
    """Per-IdP cache file that _polling_plugin() reads and writes."""
    return _polling_plugin().refresh_token_cache


def test_keystone_call_uses_timeout():
    session = MagicMock()
    _polling_plugin()._get_keystone_token(session, "at")
    kwargs = session.post.call_args.kwargs
    assert kwargs["timeout"] == KEYSTONE_TIMEOUT == 10
    assert kwargs["headers"] == {"Authorization": "Bearer at"}
    assert kwargs["authenticated"] is False


def test_keystone_failure_warns_and_reraises(caplog):
    session = MagicMock()
    session.post.side_effect = exceptions.ConnectTimeout("Request timed out")
    with caplog.at_level(logging.WARNING, logger="ccauth.plugin"), pytest.raises(exceptions.ConnectTimeout):
        _polling_plugin()._get_keystone_token(session, "at")
    assert AUTH_URL in caplog.text
    assert "timed out" in caplog.text


def test_device_flow_caches_refresh_token_when_keystone_fails(cache):
    session = MagicMock()
    session.post.side_effect = [
        _token_response("rt-device"),
        exceptions.ConnectTimeout("Request timed out"),
    ]
    p = _polling_plugin()
    with pytest.raises(exceptions.ConnectTimeout):
        p.get_unscoped_auth_ref(session)
    assert _load_refresh_token(cache) == "rt-device"
    assert p.refresh_token_cached is True


def test_refresh_flow_caches_rotated_token_when_keystone_fails(cache):
    _save_refresh_token(cache, "rt-old")
    session = MagicMock()
    session.post.side_effect = [
        _token_response("rt-new"),
        exceptions.ConnectTimeout("Request timed out"),
    ]
    p = _polling_plugin()
    with pytest.raises(exceptions.ConnectTimeout):
        p.get_unscoped_auth_ref(session)
    assert _load_refresh_token(cache) == "rt-new"
    assert p.refresh_token_cached is True


def test_refresh_token_not_marked_cached_when_keycloak_fails(cache):
    session = MagicMock()
    session.post.side_effect = exceptions.ConnectFailure("keycloak down")
    p = _polling_plugin()
    with pytest.raises(exceptions.ConnectFailure):
        p.get_unscoped_auth_ref(session)
    assert not cache.exists()
    assert p.refresh_token_cached is False
