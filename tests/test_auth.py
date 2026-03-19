import json
import stat

import yaml

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
        client_id=SITE.client_id,
        discovery_endpoint=SITE.discovery_endpoint,
    )
    result = write_clouds_yaml([site2], path, force=True)
    assert result is True
    data = yaml.safe_load(path.read_text())
    assert (
        data["clouds"]["chi_uc"]["auth"]["auth_url"] == "https://new.example.com:5000"
    )


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


def test_discover_from_reference_api_parses_response(tmp_path, monkeypatch):
    """Test that from_reference_api correctly builds SiteConfigs."""
    from ccauth import discover

    api_response = json.dumps(
        {
            "items": [
                {
                    "uid": "uc",
                    "name": "CHI@UC",
                    "web": "https://chi.uc.chameleoncloud.org",
                },
                {
                    "uid": "tacc",
                    "name": "CHI@TACC",
                    "web": "https://chi.tacc.chameleoncloud.org",
                },
            ]
        }
    )

    def fake_urlopen(url, timeout=None):
        from io import BytesIO

        resp = BytesIO(api_response.encode())
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: None
        return resp

    monkeypatch.setattr(discover.urllib.request, "urlopen", fake_urlopen)

    sites = discover.from_reference_api(project_id="proj123")
    assert len(sites) == 2
    assert sites[0].auth_url == "https://chi.uc.chameleoncloud.org:5000/v3"
    assert sites[0].region_name == "CHI@UC"
    assert sites[0].cloud_name == "uc"
    assert sites[1].auth_url == "https://chi.tacc.chameleoncloud.org:5000/v3"
    assert sites[1].cloud_name == "tacc"
