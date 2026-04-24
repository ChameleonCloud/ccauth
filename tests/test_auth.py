import json
import stat
import sys
from io import StringIO
from unittest.mock import MagicMock

import yaml

from ccauth.appcred import (
    AppCredConfig,
    _read_cache,
    _write_cache,
    ensure_app_cred,
    write_clouds_yaml as write_appcred_clouds_yaml,
    write_openrc as write_appcred_openrc,
)
from ccauth.config import SiteConfig
from ccauth.plugin import _load_refresh_token, _save_refresh_token
from ccauth.writers import write_clouds_yaml, write_openrc_file


SITE = SiteConfig(
    auth_url="https://chi.uc.chameleoncloud.org:5000",
    region_name="CHI@UC",
    project_id="proj123",
    cloud_name="chi_uc",
    client_id="chi-cli-device-token",
    discovery_endpoint="https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
)

APP_CRED = {
    "id": "cred-abc123",
    "name": "chi-device-flow-auth-20240101120000",
    "secret": "sup3rs3cr3t",
    "expires_at": "2099-01-01T00:00:00Z",
}


def _mock_session(monkeypatch, new_cred):
    import ccauth.appcred as appcred_mod

    mock_access = MagicMock()
    mock_access.user_id = "user-xyz"

    mock_post_resp = MagicMock()
    mock_post_resp.json.return_value = {"application_credential": new_cred}

    mock_get_resp = MagicMock()
    mock_get_resp.json.return_value = {"application_credentials": []}

    mock_sess = MagicMock()
    mock_sess.auth.get_access.return_value = mock_access
    mock_sess.post.return_value = mock_post_resp
    mock_sess.get.return_value = mock_get_resp

    monkeypatch.setattr(appcred_mod, "Session", MagicMock(return_value=mock_sess))
    monkeypatch.setattr(appcred_mod, "ChameleonDeviceAuth", MagicMock())
    return mock_sess


def test_save_and_load_refresh_token(tmp_path):
    cache = tmp_path / "refresh_token.json"
    _save_refresh_token(cache, "tok123")
    assert _load_refresh_token(cache) == "tok123"


def test_save_refresh_token_mode(tmp_path):
    cache = tmp_path / "refresh_token.json"
    _save_refresh_token(cache, "tok")
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600


def test_load_refresh_token_missing(tmp_path):
    assert _load_refresh_token(tmp_path / "nonexistent.json") is None


def test_load_refresh_token_corrupt(tmp_path):
    cache = tmp_path / "refresh_token.json"
    cache.write_text("not json")
    assert _load_refresh_token(cache) is None


def test_write_clouds_yaml(tmp_path):
    path = tmp_path / "clouds.yaml"
    assert write_clouds_yaml([SITE], path) is True

    data = yaml.safe_load(path.read_text())
    cloud = data["clouds"]["chi_uc"]
    assert cloud["auth_type"] == "v3chameleonoidc"
    assert cloud["auth"]["auth_url"] == SITE.auth_url
    assert cloud["auth"]["project_id"] == SITE.project_id
    assert cloud["region_name"] == SITE.region_name


def test_write_clouds_yaml_mode(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_clouds_yaml_skip_existing(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    assert write_clouds_yaml([SITE], path) is False


def test_write_clouds_yaml_force_overwrites(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    site2 = SiteConfig(
        auth_url="https://new.example.com:5000",
        region_name="NEW",
        project_id="proj999",
        cloud_name="chi_uc",
        client_id=SITE.client_id,
        discovery_endpoint=SITE.discovery_endpoint,
    )
    assert write_clouds_yaml([site2], path, force=True) is True
    data = yaml.safe_load(path.read_text())
    assert data["clouds"]["chi_uc"]["auth"]["auth_url"] == "https://new.example.com:5000"


def test_write_openrc(tmp_path):
    path = tmp_path / "openrc.sh"
    assert write_openrc_file(SITE, path) is True

    content = path.read_text()
    assert 'OS_AUTH_TYPE="v3chameleonoidc"' in content
    assert f'OS_AUTH_URL="{SITE.auth_url}"' in content
    assert f'OS_PROJECT_ID="{SITE.project_id}"' in content


def test_write_openrc_mode(tmp_path):
    path = tmp_path / "openrc.sh"
    write_openrc_file(SITE, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_openrc_skip_existing(tmp_path):
    path = tmp_path / "openrc.sh"
    write_openrc_file(SITE, path)
    assert write_openrc_file(SITE, path) is False


def test_discover_from_reference_api_parses_response(monkeypatch):
    from ccauth import discover

    api_response = json.dumps({
        "items": [
            {"uid": "uc", "name": "CHI@UC", "web": "https://chi.uc.chameleoncloud.org"},
            {"uid": "tacc", "name": "CHI@TACC", "web": "https://chi.tacc.chameleoncloud.org"},
        ]
    })

    mock_resp = MagicMock()
    mock_resp.read.return_value = api_response.encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(discover.urllib.request, "urlopen", MagicMock(return_value=mock_resp))

    sites = discover.from_reference_api(project_id="proj123")
    assert len(sites) == 2
    assert sites[0].auth_url == "https://chi.uc.chameleoncloud.org:5000/v3"
    assert sites[0].region_name == "CHI@UC"
    assert sites[0].cloud_name == "uc"
    assert sites[1].auth_url == "https://chi.tacc.chameleoncloud.org:5000/v3"
    assert sites[1].cloud_name == "tacc"


def test_appcred_write_cache_and_read(tmp_path):
    cache = tmp_path / "app-cred.json"
    _write_cache(cache, APP_CRED)
    result = _read_cache(cache, ttl_seconds=86400)
    assert result["id"] == APP_CRED["id"]
    assert result["secret"] == APP_CRED["secret"]


def test_appcred_cache_mode(tmp_path):
    cache = tmp_path / "app-cred.json"
    _write_cache(cache, APP_CRED)
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600


def test_appcred_cache_miss(tmp_path):
    assert _read_cache(tmp_path / "nonexistent.json", ttl_seconds=86400) is None


def test_appcred_cache_expired_ttl(tmp_path):
    cache = tmp_path / "app-cred.json"
    _write_cache(cache, APP_CRED)
    assert _read_cache(cache, ttl_seconds=0) is None


def test_appcred_cache_expired_cred(tmp_path):
    cache = tmp_path / "app-cred.json"
    _write_cache(cache, {**APP_CRED, "expires_at": "2000-01-01T00:00:00Z"})
    assert _read_cache(cache, ttl_seconds=86400) is None


def test_v3_base_appends_v3_when_missing():
    from ccauth.appcred import _v3_base
    assert _v3_base("https://chi.uc.chameleoncloud.org:5000") == "https://chi.uc.chameleoncloud.org:5000/v3"
    assert _v3_base("https://chi.uc.chameleoncloud.org:5000/") == "https://chi.uc.chameleoncloud.org:5000/v3"
    assert _v3_base("https://chi.uc.chameleoncloud.org:5000/v3") == "https://chi.uc.chameleoncloud.org:5000/v3"
    assert _v3_base("https://chi.uc.chameleoncloud.org:5000/v3/") == "https://chi.uc.chameleoncloud.org:5000/v3"


def test_create_app_cred_uses_v3_url(tmp_path, monkeypatch):
    """Ensure app cred POST goes to /v3/users/... even when auth_url has no /v3."""
    new_cred = {"id": "cred-1", "name": "chi-device-flow-auth-20240101", "secret": "s"}
    mock_sess = _mock_session(monkeypatch, new_cred)

    config = AppCredConfig(
        auth_url="https://chi.uc.chameleoncloud.org:5000",  # no /v3
        app_cred_cache_path=tmp_path / "app-cred.json",
    )
    ensure_app_cred(config)

    posted_url = mock_sess.post.call_args[0][0]
    assert "/v3/users/" in posted_url


def test_appcred_cache_corrupt(tmp_path):
    cache = tmp_path / "app-cred.json"
    cache.write_text("not json")
    assert _read_cache(cache, ttl_seconds=86400) is None


def test_appcred_write_openrc(tmp_path):
    path = tmp_path / "openrc"
    result = write_appcred_openrc(
        APP_CRED, path,
        auth_url="https://chi.uc.chameleoncloud.org:5000/v3",
        region_name="CHI@UC",
    )
    assert result is True
    content = path.read_text()
    assert 'OS_AUTH_TYPE="v3applicationcredential"' in content
    assert 'OS_AUTH_URL="https://chi.uc.chameleoncloud.org:5000/v3"' in content
    assert f'OS_APPLICATION_CREDENTIAL_ID="{APP_CRED["id"]}"' in content
    assert f'OS_APPLICATION_CREDENTIAL_SECRET="{APP_CRED["secret"]}"' in content
    assert 'OS_REGION_NAME="CHI@UC"' in content


def test_appcred_write_openrc_mode(tmp_path):
    path = tmp_path / "openrc"
    write_appcred_openrc(APP_CRED, path, auth_url="https://example.com")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_appcred_write_openrc_skip_existing(tmp_path):
    path = tmp_path / "openrc"
    write_appcred_openrc(APP_CRED, path, auth_url="https://example.com")
    assert write_appcred_openrc(APP_CRED, path, auth_url="https://example.com") is False


def test_appcred_write_openrc_force(tmp_path):
    path = tmp_path / "openrc"
    write_appcred_openrc(APP_CRED, path, auth_url="https://example.com")
    assert write_appcred_openrc(APP_CRED, path, auth_url="https://example.com", force=True) is True


def test_appcred_write_clouds_yaml(tmp_path):
    path = tmp_path / "clouds.yaml"
    result = write_appcred_clouds_yaml(
        APP_CRED, path,
        cloud_name="chi_uc",
        auth_url="https://chi.uc.chameleoncloud.org:5000/v3",
        region_name="CHI@UC",
    )
    assert result is True
    data = yaml.safe_load(path.read_text())
    cloud = data["clouds"]["chi_uc"]
    assert cloud["auth_type"] == "v3applicationcredential"
    assert cloud["auth"]["application_credential_id"] == APP_CRED["id"]
    assert cloud["auth"]["application_credential_secret"] == APP_CRED["secret"]
    assert cloud["region_name"] == "CHI@UC"


def test_appcred_write_clouds_yaml_mode(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_appcred_clouds_yaml(APP_CRED, path, auth_url="https://example.com")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_appcred_write_clouds_yaml_skip_existing(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_appcred_clouds_yaml(APP_CRED, path, cloud_name="chi_uc", auth_url="https://example.com")
    assert write_appcred_clouds_yaml(APP_CRED, path, cloud_name="chi_uc", auth_url="https://example.com") is False


def test_appcred_write_clouds_yaml_force(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_appcred_clouds_yaml(APP_CRED, path, cloud_name="chi_uc", auth_url="https://example.com")
    assert write_appcred_clouds_yaml(APP_CRED, path, cloud_name="chi_uc", auth_url="https://example.com", force=True) is True


def test_ensure_app_cred_from_cache(tmp_path):
    cache = tmp_path / "app-cred.json"
    _write_cache(cache, APP_CRED)
    config = AppCredConfig(
        auth_url="https://chi.uc.chameleoncloud.org:5000/v3",
        app_cred_cache_path=cache,
    )
    assert ensure_app_cred(config)["id"] == APP_CRED["id"]


def test_ensure_app_cred_creates_new(tmp_path, monkeypatch):
    new_cred = {"id": "new-id", "name": "chi-device-flow-auth-20240101", "secret": "newsecret"}
    _mock_session(monkeypatch, new_cred)

    cache = tmp_path / "app-cred.json"
    config = AppCredConfig(
        auth_url="https://chi.uc.chameleoncloud.org:5000/v3",
        app_cred_cache_path=cache,
    )
    result = ensure_app_cred(config)
    assert result["id"] == "new-id"
    assert cache.exists()


def test_ensure_app_cred_force_refresh(tmp_path, monkeypatch):
    new_cred = {"id": "refreshed-id", "name": "chi-device-flow-auth-20240102", "secret": "newsecret2"}
    _mock_session(monkeypatch, new_cred)

    cache = tmp_path / "app-cred.json"
    _write_cache(cache, APP_CRED)

    config = AppCredConfig(
        auth_url="https://chi.uc.chameleoncloud.org:5000/v3",
        app_cred_cache_path=cache,
    )
    assert ensure_app_cred(config, force_refresh=True)["id"] == "refreshed-id"


def test_cc_login_compat_help():
    from ccauth.cli import main

    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = StringIO()
        sys.stderr = StringIO()
        main(["--help"], use_cc_login_compat=True)
    except SystemExit:
        output = sys.stdout.getvalue() + sys.stderr.getvalue()
        assert "cc-login" in output
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


def test_cc_login_compat_output_openrc(tmp_path, monkeypatch):
    new_cred = {"id": "cred-abc", "name": "chi-device-flow-auth-20240101", "secret": "s3cr3t"}
    _mock_session(monkeypatch, new_cred)

    from ccauth.cli import main

    output = tmp_path / "openrc"
    result = main(
        [
            "--output-openrc", str(output),
            "--auth-url", "https://chi.uc.chameleoncloud.org:5000/v3",
            "--app-cred-cache-path", str(tmp_path / "app-cred.json"),
        ],
        use_cc_login_compat=True,
    )
    assert result == 0
    content = output.read_text()
    assert 'OS_AUTH_TYPE="v3applicationcredential"' in content
    assert 'OS_APPLICATION_CREDENTIAL_ID="cred-abc"' in content
    assert 'OS_APPLICATION_CREDENTIAL_SECRET="s3cr3t"' in content


def test_cc_login_compat_output_clouds_yaml(tmp_path, monkeypatch):
    new_cred = {"id": "cred-xyz", "name": "chi-device-flow-auth-20240101", "secret": "abc123"}
    _mock_session(monkeypatch, new_cred)

    from ccauth.cli import main

    output = tmp_path / "clouds.yaml"
    result = main(
        [
            "--output-clouds-yaml", str(output),
            "--auth-url", "https://chi.uc.chameleoncloud.org:5000/v3",
            "--app-cred-cache-path", str(tmp_path / "app-cred.json"),
        ],
        use_cc_login_compat=True,
    )
    assert result == 0
    data = yaml.safe_load(output.read_text())
    cloud = data["clouds"]["chameleon"]
    assert cloud["auth_type"] == "v3applicationcredential"
    assert cloud["auth"]["application_credential_id"] == "cred-xyz"


def test_cc_login_compat_force_flags_accepted(tmp_path, monkeypatch):
    new_cred = {"id": "cred-force", "name": "chi-device-flow-auth-20240101", "secret": "secret"}
    _mock_session(monkeypatch, new_cred)

    from ccauth.cli import main

    output = tmp_path / "openrc"
    output.write_text("old content")
    result = main(
        [
            "--output-openrc", str(output),
            "--auth-url", "https://chi.uc.chameleoncloud.org:5000/v3",
            "--app-cred-cache-path", str(tmp_path / "app-cred.json"),
            "--force-refresh",
            "--force-openrc",
        ],
        use_cc_login_compat=True,
    )
    assert result == 0
    assert 'OS_AUTH_TYPE="v3applicationcredential"' in output.read_text()
