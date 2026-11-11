import logging
import stat
import time
from unittest.mock import MagicMock

import pytest
from keystoneauth1 import exceptions

from ccauth import plugin as plugin_mod
from ccauth.plugin import (
    KEYSTONE_TIMEOUT,
    ChameleonDeviceAuth,
    _load_refresh_token,
    _save_refresh_token,
)


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


# --- Keystone exchange: timeout and failure handling ---

AUTH_URL = "https://chi.edge.example.org:5000/v3"


def _plugin():
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
def cache(tmp_path, monkeypatch):
    path = tmp_path / "refresh_token.json"
    monkeypatch.setattr(plugin_mod, "REFRESH_TOKEN_CACHE", path)
    return path


def test_keystone_call_uses_timeout():
    session = MagicMock()
    _plugin()._get_keystone_token(session, "at")
    kwargs = session.post.call_args.kwargs
    assert kwargs["timeout"] == KEYSTONE_TIMEOUT == 10
    assert kwargs["headers"] == {"Authorization": "Bearer at"}
    assert kwargs["authenticated"] is False


def test_keystone_failure_warns_and_reraises(caplog):
    session = MagicMock()
    session.post.side_effect = exceptions.ConnectTimeout("Request timed out")
    with caplog.at_level(logging.WARNING, logger="ccauth.plugin"), pytest.raises(exceptions.ConnectTimeout):
        _plugin()._get_keystone_token(session, "at")
    assert AUTH_URL in caplog.text
    assert "timed out" in caplog.text


def test_device_flow_caches_refresh_token_when_keystone_fails(cache):
    session = MagicMock()
    session.post.side_effect = [
        _token_response("rt-device"),
        exceptions.ConnectTimeout("Request timed out"),
    ]
    p = _plugin()
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
    p = _plugin()
    with pytest.raises(exceptions.ConnectTimeout):
        p.get_unscoped_auth_ref(session)
    assert _load_refresh_token(cache) == "rt-new"
    assert p.refresh_token_cached is True


def test_refresh_token_not_marked_cached_when_keycloak_fails(cache):
    session = MagicMock()
    session.post.side_effect = exceptions.ConnectFailure("keycloak down")
    p = _plugin()
    with pytest.raises(exceptions.ConnectFailure):
        p.get_unscoped_auth_ref(session)
    assert not cache.exists()
    assert p.refresh_token_cached is False
