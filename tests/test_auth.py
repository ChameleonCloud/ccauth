import json
import stat
from pathlib import Path

import yaml

from ccauth.auth import SiteConfig, write_clouds_yaml, write_openrc_file
from ccauth.plugin import _load_refresh_token, _save_refresh_token, REFRESH_TOKEN_CACHE


SITE = SiteConfig(
    auth_url="https://chi.uc.chameleoncloud.org:5000",
    region_name="CHI@UC",
    project_id="proj123",
    cloud_name="chi_uc",
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


def test_write_clouds_yaml(tmp_path):
    path = tmp_path / "clouds.yaml"
    result = write_clouds_yaml([SITE], path)
    assert result is True

    data = yaml.safe_load(path.read_text())
    cloud = data["clouds"]["chi_uc"]
    assert cloud["auth_type"] == "v3chameleonoidc"
    assert cloud["auth"]["auth_url"] == SITE.auth_url
    assert cloud["auth"]["project_id"] == SITE.project_id
    assert cloud["region_name"] == SITE.region_name


def test_write_clouds_yaml_mode(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_write_clouds_yaml_skip_existing(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    # Second write without force should skip
    result = write_clouds_yaml([SITE], path)
    assert result is False


def test_write_clouds_yaml_force_overwrites(tmp_path):
    path = tmp_path / "clouds.yaml"
    write_clouds_yaml([SITE], path)
    site2 = SiteConfig(
        auth_url="https://new.example.com:5000",
        region_name="NEW",
        project_id="proj999",
        cloud_name="chi_uc",
    )
    result = write_clouds_yaml([site2], path, force=True)
    assert result is True
    data = yaml.safe_load(path.read_text())
    assert data["clouds"]["chi_uc"]["auth"]["auth_url"] == "https://new.example.com:5000"


def test_write_openrc(tmp_path):
    path = tmp_path / "openrc.sh"
    result = write_openrc_file(SITE, path)
    assert result is True

    content = path.read_text()
    assert 'OS_AUTH_TYPE="v3chameleonoidc"' in content
    assert f'OS_AUTH_URL="{SITE.auth_url}"' in content
    assert f'OS_PROJECT_ID="{SITE.project_id}"' in content


def test_write_openrc_mode(tmp_path):
    path = tmp_path / "openrc.sh"
    write_openrc_file(SITE, path)
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_write_openrc_skip_existing(tmp_path):
    path = tmp_path / "openrc.sh"
    write_openrc_file(SITE, path)
    result = write_openrc_file(SITE, path)
    assert result is False
