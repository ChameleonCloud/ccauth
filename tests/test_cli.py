"""Tests for cli.py."""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
import yaml

from ccauth.cli import (
    _build_sites,
    _collect_all_projects,
    _discover_projects,
    _enrich_project_ids,
    _list_projects_at,
    main,
)
from ccauth.config import SiteConfig
from ccauth._urlutils import auth_url_base as base_url
from ccauth.discover import (
    DEFAULT_CLIENT_ID,
    DEFAULT_DISCOVERY_ENDPOINT,
    SITES_API_URL,
    list_projects_at,
    VENDORDATA_URL,
    from_vendordata,
)



def _args(**kwargs):
    """Argparse Namespace with sensible defaults for all _add_site_args fields."""
    defaults = dict(
        auth_url=None,
        region_name=None,
        project_id=None,
        identity_provider="chameleon",
        protocol="openid",
        cloud_name="chameleon",
        client_id=DEFAULT_CLIENT_ID,
        discovery_endpoint=DEFAULT_DISCOVERY_ENDPOINT,
        sites_api_url=SITES_API_URL,
        metadata_url=VENDORDATA_URL,
        all_sites=False,
        no_vendordata=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _site(auth_url, region, cloud_name="chameleon", project_id=""):
    return SiteConfig(
        auth_url=auth_url,
        region_name=region,
        cloud_name=cloud_name,
        client_id=DEFAULT_CLIENT_ID,
        discovery_endpoint=DEFAULT_DISCOVERY_ENDPOINT,
        project_id=project_id,
    )


TACC = _site("https://chi.tacc.chameleoncloud.org:5000/v3", "CHI@TACC", "tacc")
UC   = _site("https://chi.uc.chameleoncloud.org:5000/v3",   "CHI@UC",   "uc")
KVM  = _site("https://kvm.tacc.chameleoncloud.org:5000/v3", "KVM@TACC", "kvm", "proj-kvm")


def test_base_url_strips_v3():
    assert base_url("https://example.com:5000/v3") == "https://example.com:5000"

def test_base_url_strips_trailing_slash():
    assert base_url("https://example.com:5000/") == "https://example.com:5000"

def test_base_url_strips_v3_and_trailing_slash():
    assert base_url("https://example.com:5000/v3/") == "https://example.com:5000"



def test_build_sites_explicit_auth_url():
    args = _args(auth_url="https://example.com:5000/v3", region_name="TEST",
                 project_id="p1", cloud_name="test")
    sites = _build_sites(args)
    assert len(sites) == 1
    assert sites[0].auth_url == "https://example.com:5000/v3"
    assert sites[0].project_id == "p1"
    assert sites[0].cloud_name == "test"



def test_build_sites_default_uses_vendordata_only(monkeypatch):
    ref_api = MagicMock()
    monkeypatch.setattr("ccauth.cli.from_reference_api", ref_api)
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [replace(KVM)])
    sites = _build_sites(_args())
    assert len(sites) == 1
    assert sites[0].cloud_name == "kvm"
    ref_api.assert_not_called()


def test_build_sites_default_no_vendordata_returns_none(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    assert _build_sites(_args()) is None


def test_build_sites_default_project_id_from_vendordata(monkeypatch):
    vd = _site("https://chi.tacc.chameleoncloud.org:5000", "CHI@TACC", "tacc", "vd-proj")
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args())
    assert sites[0].project_id == "vd-proj"


def test_build_sites_no_vendordata_flag_errors():
    assert _build_sites(_args(no_vendordata=True)) is None


def test_build_sites_no_vendordata_flag_with_auth_url():
    sites = _build_sites(_args(
        auth_url="https://example.com:5000/v3",
        no_vendordata=True,
    ))
    assert len(sites) == 1



def _fresh_ref(*names):
    """Return a lambda that produces fresh copies of named site constants."""
    lookup = {"tacc": TACC, "uc": UC, "kvm": KVM}
    return lambda **_: [replace(lookup[n]) for n in names]


def test_build_sites_all_sites_reference_api(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    sites = _build_sites(_args(all_sites=True))
    assert [s.cloud_name for s in sites] == ["tacc", "uc"]


def test_build_sites_all_sites_no_sources_returns_none(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: [])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    assert _build_sites(_args(all_sites=True)) is None


def test_build_sites_all_sites_deduplicates_same_auth_url(monkeypatch):
    vd = _site("https://chi.tacc.chameleoncloud.org:5000", "CHI@TACC", "tacc", "proj1")
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args(all_sites=True))
    assert len(sites) == 2
    tacc = next(s for s in sites if s.cloud_name == "tacc")
    assert tacc.project_id == "proj1"


def test_build_sites_all_sites_stamps_auth_config(monkeypatch):
    bare = [SiteConfig(auth_url=TACC.auth_url, region_name=TACC.region_name, cloud_name="tacc")]
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: bare)
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    sites = _build_sites(_args(all_sites=True))
    assert sites[0].client_id == DEFAULT_CLIENT_ID
    assert sites[0].discovery_endpoint == DEFAULT_DISCOVERY_ENDPOINT


def test_build_sites_all_sites_appends_vendordata_site_not_in_ref_api(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [replace(KVM)])
    sites = _build_sites(_args(all_sites=True))
    assert len(sites) == 3
    assert sites[-1].cloud_name == "kvm"


def test_build_sites_all_sites_prefers_non_chameleon_cloud_name(monkeypatch):
    ref = _site("https://kvm.tacc.chameleoncloud.org:5000/v3", "KVM@TACC", "chameleon")
    vd  = _site("https://kvm.tacc.chameleoncloud.org:5000",    "KVM@TACC", "kvm", "p1")
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: [ref])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args(all_sites=True))
    assert len(sites) == 1
    assert sites[0].cloud_name == "kvm"


def test_build_sites_all_sites_keeps_ref_api_name_when_better(monkeypatch):
    vd = _site("https://chi.uc.chameleoncloud.org:5000", "CHI@UC", "chameleon", "p1")
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: [replace(UC)])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args(all_sites=True))
    assert sites[0].cloud_name == "uc"


def test_build_sites_all_sites_project_id_from_vendordata_applied_to_current_site_only(monkeypatch):
    vd = _site("https://chi.tacc.chameleoncloud.org:5000", "CHI@TACC", "tacc", "vd-proj")
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args(all_sites=True))
    tacc = next(s for s in sites if s.cloud_name == "tacc")
    uc   = next(s for s in sites if s.cloud_name == "uc")
    assert tacc.project_id == "vd-proj"
    assert uc.project_id == ""


def test_build_sites_all_sites_explicit_project_id_overrides_vendordata(monkeypatch):
    vd = _site("https://chi.tacc.chameleoncloud.org:5000", "CHI@TACC", "tacc", "vd-proj")
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args(all_sites=True, project_id="explicit-proj"))
    tacc = next(s for s in sites if s.cloud_name == "tacc")
    assert tacc.project_id == "explicit-proj"


def test_build_sites_all_sites_explicit_project_id_no_vendordata_seeds_first_site(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    sites = _build_sites(_args(all_sites=True, project_id="seed-proj"))
    assert sites[0].project_id == "seed-proj"
    assert all(s.project_id == "" for s in sites[1:])


def test_build_sites_all_sites_no_vendordata_flag_skips_vendordata(monkeypatch):
    vd_mock = MagicMock()
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", vd_mock)
    sites = _build_sites(_args(all_sites=True, no_vendordata=True))
    assert len(sites) == 2
    vd_mock.assert_not_called()



def test_list_projects_at_returns_projects():
    projects = [{"id": "p1", "name": "CHI-240042"}, {"id": "p2", "name": "CHI-240099"}]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"projects": projects}
    mock_sess = MagicMock()
    mock_sess.auth.auth_url = TACC.auth_url
    mock_sess.get.return_value = mock_resp
    assert list_projects_at(mock_sess) == projects


def test_list_projects_at_normalizes_url():
    """URL sent to Keystone should include /v3 even if auth_url omits it."""
    captured = {}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"projects": []}
    mock_sess = MagicMock()
    mock_sess.auth.auth_url = "https://example.com:5000"  # no /v3

    def fake_get(url, **_):
        captured["url"] = url
        return mock_resp

    mock_sess.get.side_effect = fake_get
    list_projects_at(mock_sess)
    assert captured["url"] == "https://example.com:5000/v3/auth/projects"


def test_list_projects_at_wrapper_returns_projects():
    projects = [{"id": "p1", "name": "CHI-240042"}]
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli.Session", MagicMock())
        mp.setattr("ccauth.cli.ChameleonDeviceAuth", MagicMock())
        mp.setattr("ccauth.cli.list_projects_at", MagicMock(return_value=projects))
        result = _list_projects_at(TACC)
    assert result == projects


def test_list_projects_at_wrapper_returns_empty_on_exception():
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli.Session", MagicMock())
        mp.setattr("ccauth.cli.ChameleonDeviceAuth", MagicMock())
        mp.setattr("ccauth.cli.list_projects_at", MagicMock(side_effect=Exception("fail")))
        result = _list_projects_at(TACC)
    assert result == []



def test_enrich_skips_when_no_seeded_site():
    sites = [_site("https://a.com:5000/v3", "A")]  # no project_id
    mock_list = MagicMock()
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        _enrich_project_ids(sites)
    mock_list.assert_not_called()


def test_enrich_fills_missing_project_ids():
    seeded = _site("https://a.com:5000/v3", "A", project_id="p1")
    other  = _site("https://b.com:5000/v3", "B")

    def mock_list(site):
        if site is seeded:
            return [{"id": "p1", "name": "CHI-240042"}]
        if site is other:
            return [{"id": "p2", "name": "CHI-240042"}]
        return []

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        _enrich_project_ids([seeded, other])

    assert other.project_id == "p2"


def test_enrich_does_not_overwrite_existing_project_id():
    seeded = _site("https://a.com:5000/v3", "A", project_id="p1")
    other  = _site("https://b.com:5000/v3", "B", project_id="already-set")

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock(
            return_value=[{"id": "p1", "name": "CHI-240042"}]
        ))
        _enrich_project_ids([seeded, other])

    assert other.project_id == "already-set"


def test_enrich_leaves_empty_when_project_not_found_at_site():
    seeded = _site("https://a.com:5000/v3", "A", project_id="p1")
    other  = _site("https://b.com:5000/v3", "B")

    def mock_list(site):
        if site is seeded:
            return [{"id": "p1", "name": "CHI-240042"}]
        return []

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        _enrich_project_ids([seeded, other])

    assert other.project_id == ""



def test_discover_projects_groups_by_name():
    def mock_list(site):
        return [{"id": f"p-{site.cloud_name}", "name": "CHI-240042"}]

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        result = _discover_projects([TACC, UC])

    assert "CHI-240042" in result
    assert len(result["CHI-240042"]) == 2
    ids = {s.project_id for s in result["CHI-240042"]}
    assert ids == {"p-tacc", "p-uc"}


def test_discover_projects_multiple_projects_per_site():
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock(return_value=[
            {"id": "p1", "name": "CHI-240042"},
            {"id": "p2", "name": "CHI-240099"},
        ]))
        result = _discover_projects([TACC])

    assert set(result.keys()) == {"CHI-240042", "CHI-240099"}


def test_discover_projects_site_with_no_projects_is_excluded():
    def mock_list(site):
        return [{"id": "p1", "name": "CHI-240042"}] if site is TACC else []

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        result = _discover_projects([TACC, UC])

    assert len(result["CHI-240042"]) == 1
    assert result["CHI-240042"][0].cloud_name == "tacc"



def test_collect_all_projects_slugged_names():
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock(return_value=[
            {"id": "p1", "name": "CHI-240042"}
        ]))
        result = _collect_all_projects([TACC])

    assert len(result) == 1
    assert result[0].cloud_name == "tacc_chi_240042"
    assert result[0].project_id == "p1"


def test_collect_all_projects_one_entry_per_site_project_pair():
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock(return_value=[
            {"id": "p1", "name": "CHI-240042"}
        ]))
        result = _collect_all_projects([TACC, UC])

    assert len(result) == 2
    names = {r.cloud_name for r in result}
    assert names == {"tacc_chi_240042", "uc_chi_240042"}



def _mock_vendordata(monkeypatch, data: dict):
    import ccauth.discover as discover_mod
    monkeypatch.setattr(discover_mod, "_metadata_reachable", lambda: True)
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        discover_mod.urllib.request, "urlopen", MagicMock(return_value=mock_resp)
    )


def test_vendordata_kvm_region_gets_kvm_cloud_name(monkeypatch):
    _mock_vendordata(monkeypatch, {"chameleon": {
        "auth_url": "https://kvm.tacc.chameleoncloud.org:5000",
        "region": "KVM@TACC",
        "project_id": "proj1",
    }})
    sites = from_vendordata()
    assert sites[0].cloud_name == "kvm"
    assert sites[0].project_id == "proj1"


def test_vendordata_non_kvm_region_gets_chameleon_cloud_name(monkeypatch):
    _mock_vendordata(monkeypatch, {"chameleon": {
        "auth_url": "https://chi.uc.chameleoncloud.org:5000",
        "region": "CHI@UC",
        "project_id": "proj2",
    }})
    sites = from_vendordata()
    assert sites[0].cloud_name == "chameleon"


def test_vendordata_edge_region_gets_chameleon_cloud_name(monkeypatch):
    _mock_vendordata(monkeypatch, {"chameleon": {
        "auth_url": "https://edge.tacc.chameleoncloud.org:5000",
        "region": "CHI@Edge",
        "project_id": "proj3",
    }})
    sites = from_vendordata()
    assert sites[0].cloud_name == "chameleon"


def test_vendordata_returns_empty_on_network_error(monkeypatch):
    import ccauth.discover as discover_mod
    monkeypatch.setattr(
        discover_mod.urllib.request, "urlopen",
        MagicMock(side_effect=OSError("no network"))
    )
    assert from_vendordata() == []


def test_vendordata_returns_empty_when_no_auth_url(monkeypatch):
    _mock_vendordata(monkeypatch, {"chameleon": {"region": "CHI@UC", "project_id": "p1"}})
    assert from_vendordata() == []


def test_vendordata_returns_empty_when_no_chameleon_key(monkeypatch):
    _mock_vendordata(monkeypatch, {"other": {}})
    assert from_vendordata() == []



def test_cmd_login_success(monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC])
    monkeypatch.setattr("ccauth.cli._trigger_auth", lambda site: None)
    assert main(["login"]) == 0


def test_cmd_login_auth_failure(monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC])
    monkeypatch.setattr("ccauth.cli._trigger_auth", MagicMock(side_effect=Exception("bad auth")))
    assert main(["login"]) == 1


def test_cmd_login_no_sites(monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: None)
    assert main(["login"]) == 1


def test_cmd_login_uses_first_site(monkeypatch):
    used = []
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._trigger_auth", lambda site: used.append(site))
    main(["login"])
    assert used[0].cloud_name == "kvm"


def test_cmd_login_falls_back_to_first_site(monkeypatch):
    used = []
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC])
    monkeypatch.setattr("ccauth.cli._trigger_auth", lambda site: used.append(site))
    main(["login"])
    assert used[0].cloud_name == "tacc"



def test_cmd_logout_clears_token(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text('{"refresh_token": "tok"}')
    import ccauth.plugin as plugin_mod
    monkeypatch.setattr(plugin_mod, "REFRESH_TOKEN_CACHE", cache)
    assert main(["logout"]) == 0
    assert not cache.exists()


def test_cmd_logout_no_token_is_ok(tmp_path, monkeypatch):
    import ccauth.plugin as plugin_mod
    monkeypatch.setattr(plugin_mod, "REFRESH_TOKEN_CACHE", tmp_path / "nonexistent.json")
    assert main(["logout"]) == 0



def test_cmd_clouds_yaml_default_single_site(tmp_path, monkeypatch):
    site = replace(TACC, project_id="proj-tacc")
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [site])
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output)]) == 0
    data = yaml.safe_load(output.read_text())
    assert "chameleon" in data["clouds"]


def test_cmd_clouds_yaml_default_kvm_site_gets_chameleon_name(tmp_path, monkeypatch):
    site = replace(KVM, project_id="proj-kvm")
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [site])
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output)]) == 0
    data = yaml.safe_load(output.read_text())
    assert "chameleon" in data["clouds"]
    assert "kvm" not in data["clouds"]


def test_cmd_clouds_yaml_all_sites_calls_enrich(tmp_path, monkeypatch):
    sites = [replace(TACC, project_id="proj-tacc"), replace(UC, project_id="proj-uc")]
    enriched = []
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: sites)
    monkeypatch.setattr("ccauth.cli._enrich_project_ids", lambda s: enriched.append(s))
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output), "--all-sites"]) == 0
    assert enriched  # enrich was called


def test_cmd_clouds_yaml_default_does_not_call_enrich(tmp_path, monkeypatch):
    site = replace(TACC, project_id="proj-tacc")
    enriched = []
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [site])
    monkeypatch.setattr("ccauth.cli._enrich_project_ids", lambda s: enriched.append(s))
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output)]) == 0
    assert not enriched  # enrich was NOT called for default single-site mode


def test_cmd_clouds_yaml_all_projects_flag(tmp_path, monkeypatch):
    all_sites = [
        _site("https://chi.tacc.chameleoncloud.org:5000/v3", "CHI@TACC", "tacc_chi_240042", "p1"),
        _site("https://chi.uc.chameleoncloud.org:5000/v3",   "CHI@UC",   "uc_chi_240042",   "p2"),
    ]
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC, UC])
    monkeypatch.setattr("ccauth.cli._collect_all_projects", lambda sites: all_sites)
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output), "--all-projects"]) == 0
    data = yaml.safe_load(output.read_text())
    assert "tacc_chi_240042" in data["clouds"]
    assert "uc_chi_240042" in data["clouds"]


def test_cmd_clouds_yaml_all_sites_all_projects(tmp_path, monkeypatch):
    all_sites = [
        _site("https://chi.tacc.chameleoncloud.org:5000/v3", "CHI@TACC", "tacc_chi_240042", "p1"),
        _site("https://chi.uc.chameleoncloud.org:5000/v3",   "CHI@UC",   "uc_chi_240042",   "p2"),
    ]
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC, UC])
    monkeypatch.setattr("ccauth.cli._collect_all_projects", lambda sites: all_sites)
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output), "--all-sites", "--all-projects"]) == 0
    data = yaml.safe_load(output.read_text())
    assert "tacc_chi_240042" in data["clouds"]
    assert "uc_chi_240042" in data["clouds"]


def test_cmd_clouds_yaml_all_projects_empty_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC])
    monkeypatch.setattr("ccauth.cli._collect_all_projects", lambda _: [])
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output), "--all-projects"]) == 1


def test_cmd_clouds_yaml_missing_project_id_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [replace(TACC)])
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output)]) == 1



def test_cmd_openrc_uses_vendordata_site(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [replace(KVM)])
    output = tmp_path / "openrc.sh"
    assert main(["openrc", "--output", str(output)]) == 0
    content = output.read_text()
    assert 'OS_AUTH_TYPE="v3chameleonoidc"' in content
    assert f'OS_AUTH_URL="{KVM.auth_url}"' in content


def test_cmd_openrc_uses_explicit_auth_url(tmp_path):
    output = tmp_path / "openrc.sh"
    assert main(["openrc", "--output", str(output),
                 "--auth-url", TACC.auth_url, "--project-id", "p1"]) == 0
    content = output.read_text()
    assert f'OS_AUTH_URL="{TACC.auth_url}"' in content
    assert 'OS_PROJECT_ID="p1"' in content


def test_cmd_openrc_errors_without_vendordata_or_auth_url(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    assert main(["openrc", "--output", str(tmp_path / "openrc.sh")]) == 1


def test_cmd_openrc_no_vendordata_flag_requires_auth_url(tmp_path):
    assert main(["openrc", "--output", str(tmp_path / "openrc.sh"), "--no-vendordata"]) == 1


def test_cmd_openrc_explicit_project_id_overrides_vendordata(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [replace(KVM)])
    output = tmp_path / "openrc.sh"
    assert main(["openrc", "--output", str(output), "--project-id", "override"]) == 0
    assert 'OS_PROJECT_ID="override"' in output.read_text()



def test_cmd_discover_projects_single_project_uses_bare_site_name(tmp_path, monkeypatch):
    kvm = _site("https://kvm.tacc.chameleoncloud.org:5000/v3", "KVM@TACC", "kvm", "p1")
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {"CHI-240042": [kvm]})
    monkeypatch.setattr("builtins.input", lambda: "1")

    output = tmp_path / "clouds.yaml"
    assert main(["discover-projects", "--output", str(output)]) == 0
    data = yaml.safe_load(output.read_text())
    assert "kvm" in data["clouds"]


def test_cmd_discover_projects_multiple_projects_use_slugged_names(tmp_path, monkeypatch):
    kvm  = _site("https://kvm.tacc.chameleoncloud.org:5000/v3", "KVM@TACC", "kvm",  "p1")
    tacc = _site("https://chi.tacc.chameleoncloud.org:5000/v3", "CHI@TACC", "tacc", "p2")
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM, TACC])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {
        "CHI-240042": [kvm],
        "CHI-240099": [tacc],
    })
    monkeypatch.setattr("builtins.input", lambda: "all")

    output = tmp_path / "clouds.yaml"
    assert main(["discover-projects", "--output", str(output)]) == 0
    data = yaml.safe_load(output.read_text())
    assert "kvm_chi_240042"  in data["clouds"]
    assert "tacc_chi_240099" in data["clouds"]


def test_cmd_discover_projects_invalid_number_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {"CHI-240042": [KVM]})
    monkeypatch.setattr("builtins.input", lambda: "99")
    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1


def test_cmd_discover_projects_non_numeric_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {"CHI-240042": [KVM]})
    monkeypatch.setattr("builtins.input", lambda: "abc")
    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1


def test_cmd_discover_projects_keyboard_interrupt_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {"CHI-240042": [KVM]})
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=KeyboardInterrupt))
    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1


def test_cmd_discover_projects_no_projects_found(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda _: {})
    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1
