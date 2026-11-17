"""Tests for auth.py (AuthConfig, build_session) and writers.py."""
import stat
from unittest.mock import MagicMock

import yaml

from ccauth.auth import AuthConfig, build_session
from ccauth.config import SiteConfig
from ccauth.discover import DEFAULT_CLIENT_ID, DEFAULT_DISCOVERY_ENDPOINT
from ccauth.writers import write_clouds_yaml, write_openrc_file


SITE = SiteConfig(
    auth_url="https://chi.uc.chameleoncloud.org:5000",
    region_name="CHI@UC",
    project_id="proj123",
    cloud_name="chi_uc",
    client_id="chi-cli-device-token",
    discovery_endpoint="https://auth.chameleoncloud.org/auth/realms/chameleon/.well-known/openid-configuration",
)


def test_auth_config_defaults():
    config = AuthConfig(auth_url="https://chi.uc.chameleoncloud.org:5000/v3")
    assert config.identity_provider == "chameleon"
    assert config.protocol == "openid"
    assert config.client_id == DEFAULT_CLIENT_ID
    assert config.discovery_endpoint == DEFAULT_DISCOVERY_ENDPOINT
    assert config.project_id == ""
    assert config.region_name == ""


def test_build_session_uses_chameleon_device_auth(monkeypatch):
    import ccauth.auth as auth_mod

    mock_plugin = MagicMock()
    mock_session = MagicMock()
    monkeypatch.setattr(auth_mod, "ChameleonDeviceAuth", MagicMock(return_value=mock_plugin))
    monkeypatch.setattr(auth_mod, "Session", MagicMock(return_value=mock_session))

    config = AuthConfig(auth_url="https://chi.uc.chameleoncloud.org:5000/v3", project_id="p1")
    result = build_session(config)

    assert result is mock_session
    auth_mod.ChameleonDeviceAuth.assert_called_once()
    kwargs = auth_mod.ChameleonDeviceAuth.call_args.kwargs
    assert kwargs["auth_url"] == config.auth_url
    assert kwargs["project_id"] == "p1"
    assert kwargs["scope"] == "openid"



def test_write_clouds_yaml(tmp_path):
    path = tmp_path / "clouds.yaml"
    assert write_clouds_yaml([SITE], path) is True

    data = yaml.safe_load(path.read_text())
    cloud = data["clouds"]["chi_uc"]
    assert cloud["auth_type"] == "v3chameleonoidc"
    assert cloud["auth"]["auth_url"] == SITE.auth_url
    assert cloud["auth"]["project_id"] == SITE.project_id
    assert "project_domain_id" not in cloud["auth"]
    assert cloud["region_name"] == SITE.region_name


def test_write_clouds_yaml_mode(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_write_clouds_yaml_refuses_existing_file_without_force(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    # second call — same or different cloud names — is refused without --force
    other = SiteConfig(
        auth_url="https://new.example.com:5000",
        region_name="NEW",
        project_id="proj999",
        cloud_name="other_site",
        client_id=SITE.client_id,
        discovery_endpoint=SITE.discovery_endpoint,
    )
    assert write_clouds_yaml([SITE], path) is False
    assert write_clouds_yaml([other], path) is False


def test_write_clouds_yaml_force_updates_file(tmp_path):
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
