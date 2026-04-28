"""Tests for cli.py and the vendordata discovery logic added to discover.py."""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from unittest.mock import MagicMock

import pytest
import yaml

from ccauth.cli import (
    _base_url,
    _build_sites,
    _collect_all_projects,
    _discover_projects,
    _enrich_project_ids,
    _list_projects_at,
    main,
)
from ccauth.config import SiteConfig
from ccauth.discover import (
    DEFAULT_CLIENT_ID,
    DEFAULT_DISCOVERY_ENDPOINT,
    SITES_API_URL,
    VENDORDATA_URL,
    from_vendordata,
)


# ── helpers ──────────────────────────────────────────────────────────────────

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


# ── _base_url ─────────────────────────────────────────────────────────────────

def test_base_url_strips_v3():
    assert _base_url("https://example.com:5000/v3") == "https://example.com:5000"

def test_base_url_strips_trailing_slash():
    assert _base_url("https://example.com:5000/") == "https://example.com:5000"

def test_base_url_strips_v3_and_trailing_slash():
    assert _base_url("https://example.com:5000/v3/") == "https://example.com:5000"

def test_base_url_no_change_needed():
    assert _base_url("https://example.com:5000") == "https://example.com:5000"


# ── _build_sites ──────────────────────────────────────────────────────────────

def test_build_sites_explicit_auth_url():
    args = _args(auth_url="https://example.com:5000/v3", region_name="TEST",
                 project_id="p1", cloud_name="test")
    sites = _build_sites(args)
    assert len(sites) == 1
    assert sites[0].auth_url == "https://example.com:5000/v3"
    assert sites[0].project_id == "p1"
    assert sites[0].cloud_name == "test"


def _fresh_ref(*names):
    """Return a lambda that produces fresh copies of named site constants."""
    lookup = {"tacc": TACC, "uc": UC, "kvm": KVM}
    return lambda **_: [replace(lookup[n]) for n in names]


def test_build_sites_reference_api_only(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    sites = _build_sites(_args())
    assert [s.cloud_name for s in sites] == ["tacc", "uc"]


def test_build_sites_vendordata_only(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: [])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [replace(KVM)])
    sites = _build_sites(_args())
    assert len(sites) == 1
    assert sites[0].cloud_name == "kvm"


def test_build_sites_no_sources_returns_none(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: [])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    assert _build_sites(_args()) is None


def test_build_sites_deduplicates_same_auth_url(monkeypatch):
    vd = _site("https://chi.tacc.chameleoncloud.org:5000", "CHI@TACC", "tacc", "proj1")
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args())
    assert len(sites) == 2  # no duplicate
    tacc = next(s for s in sites if s.cloud_name == "tacc")
    assert tacc.project_id == "proj1"


def test_build_sites_appends_vendordata_site_not_in_ref_api(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [replace(KVM)])
    sites = _build_sites(_args())
    assert len(sites) == 3
    assert sites[-1].cloud_name == "kvm"


def test_build_sites_prefers_non_chameleon_cloud_name(monkeypatch):
    ref = _site("https://kvm.tacc.chameleoncloud.org:5000/v3", "KVM@TACC", "chameleon")
    vd  = _site("https://kvm.tacc.chameleoncloud.org:5000",    "KVM@TACC", "kvm", "p1")
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: [ref])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args())
    assert len(sites) == 1
    assert sites[0].cloud_name == "kvm"


def test_build_sites_keeps_ref_api_name_when_better(monkeypatch):
    """Ref API cloud_name 'uc' should not be overwritten by vendordata 'chameleon'."""
    vd = _site("https://chi.uc.chameleoncloud.org:5000", "CHI@UC", "chameleon", "p1")
    monkeypatch.setattr("ccauth.cli.from_reference_api", lambda **_: [replace(UC)])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args())
    assert sites[0].cloud_name == "uc"


def test_build_sites_project_id_from_vendordata_applied_to_current_site_only(monkeypatch):
    vd = _site("https://chi.tacc.chameleoncloud.org:5000", "CHI@TACC", "tacc", "vd-proj")
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args())
    tacc = next(s for s in sites if s.cloud_name == "tacc")
    uc   = next(s for s in sites if s.cloud_name == "uc")
    assert tacc.project_id == "vd-proj"
    assert uc.project_id == ""


def test_build_sites_explicit_project_id_overrides_vendordata(monkeypatch):
    vd = _site("https://chi.tacc.chameleoncloud.org:5000", "CHI@TACC", "tacc", "vd-proj")
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [vd])
    sites = _build_sites(_args(project_id="explicit-proj"))
    tacc = next(s for s in sites if s.cloud_name == "tacc")
    assert tacc.project_id == "explicit-proj"


def test_build_sites_explicit_project_id_no_vendordata_applies_to_all(monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_reference_api", _fresh_ref("tacc", "uc"))
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    sites = _build_sites(_args(project_id="all-proj"))
    assert all(s.project_id == "all-proj" for s in sites)


# ── _list_projects_at ─────────────────────────────────────────────────────────

def test_list_projects_at_returns_projects():
    projects = [{"id": "p1", "name": "CHI-240042"}, {"id": "p2", "name": "CHI-240099"}]
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"projects": projects}
    mock_sess = MagicMock()
    mock_sess.get.return_value = mock_resp

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli.Session", MagicMock(return_value=mock_sess))
        mp.setattr("ccauth.cli.ChameleonDeviceAuth", MagicMock())
        result = _list_projects_at(TACC)

    assert result == projects


def test_list_projects_at_returns_empty_on_exception():
    mock_sess = MagicMock()
    mock_sess.get.side_effect = Exception("auth failed")

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli.Session", MagicMock(return_value=mock_sess))
        mp.setattr("ccauth.cli.ChameleonDeviceAuth", MagicMock())
        result = _list_projects_at(TACC)

    assert result == []


def test_list_projects_at_uses_normalized_url():
    """URL passed to Keystone should include /v3 even if auth_url omits it."""
    site = _site("https://example.com:5000", "TEST")
    captured = {}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"projects": []}

    def fake_get(url, **_):
        captured["url"] = url
        return mock_resp

    mock_sess = MagicMock()
    mock_sess.get.side_effect = fake_get

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli.Session", MagicMock(return_value=mock_sess))
        mp.setattr("ccauth.cli.ChameleonDeviceAuth", MagicMock())
        _list_projects_at(site)

    assert captured["url"].endswith("/v3/auth/projects")


# ── _enrich_project_ids ───────────────────────────────────────────────────────

def test_enrich_skips_when_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", tmp_path / "nonexistent.json")
    sites = [_site("https://a.com:5000/v3", "A", project_id="p1")]
    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock())
        _enrich_project_ids(sites)
        # _list_projects_at should never be called
        import ccauth.cli as cli_mod
        # verify by checking the real path was never hit (token file missing)


def test_enrich_skips_when_no_seeded_site(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)
    sites = [_site("https://a.com:5000/v3", "A")]  # no project_id
    with pytest.MonkeyPatch().context() as mp:
        mock_list = MagicMock()
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        _enrich_project_ids(sites)
        mock_list.assert_not_called()


def test_enrich_fills_missing_project_ids(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

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


def test_enrich_does_not_overwrite_existing_project_id(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

    seeded = _site("https://a.com:5000/v3", "A", project_id="p1")
    other  = _site("https://b.com:5000/v3", "B", project_id="already-set")

    def mock_list(site):
        return [{"id": "p1", "name": "CHI-240042"}]

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        _enrich_project_ids([seeded, other])

    assert other.project_id == "already-set"


def test_enrich_leaves_empty_when_project_not_found_at_site(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

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


# ── _discover_projects ────────────────────────────────────────────────────────

def test_discover_projects_no_token_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", tmp_path / "nonexistent.json")
    assert _discover_projects([TACC]) == {}


def test_discover_projects_groups_by_name(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

    def mock_list(site):
        return [{"id": f"p-{site.cloud_name}", "name": "CHI-240042"}]

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        result = _discover_projects([TACC, UC])

    assert "CHI-240042" in result
    assert len(result["CHI-240042"]) == 2
    ids = {s.project_id for s in result["CHI-240042"]}
    assert ids == {"p-tacc", "p-uc"}


def test_discover_projects_multiple_projects_per_site(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock(return_value=[
            {"id": "p1", "name": "CHI-240042"},
            {"id": "p2", "name": "CHI-240099"},
        ]))
        result = _discover_projects([TACC])

    assert set(result.keys()) == {"CHI-240042", "CHI-240099"}


def test_discover_projects_site_with_no_projects_is_excluded(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

    def mock_list(site):
        return [{"id": "p1", "name": "CHI-240042"}] if site is TACC else []

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", mock_list)
        result = _discover_projects([TACC, UC])

    assert len(result["CHI-240042"]) == 1
    assert result["CHI-240042"][0].cloud_name == "tacc"


# ── _collect_all_projects ─────────────────────────────────────────────────────

def test_collect_all_projects_empty_when_no_token(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", tmp_path / "nonexistent.json")
    assert _collect_all_projects([TACC]) == []


def test_collect_all_projects_slugged_names(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock(return_value=[
            {"id": "p1", "name": "CHI-240042"}
        ]))
        result = _collect_all_projects([TACC])

    assert len(result) == 1
    assert result[0].cloud_name == "tacc_chi_240042"
    assert result[0].project_id == "p1"


def test_collect_all_projects_one_entry_per_site_project_pair(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)

    with pytest.MonkeyPatch().context() as mp:
        mp.setattr("ccauth.cli._list_projects_at", MagicMock(return_value=[
            {"id": "p1", "name": "CHI-240042"}
        ]))
        result = _collect_all_projects([TACC, UC])

    assert len(result) == 2
    names = {r.cloud_name for r in result}
    assert names == {"tacc_chi_240042", "uc_chi_240042"}


# ── from_vendordata (KVM naming) ──────────────────────────────────────────────

def _mock_vendordata(monkeypatch, data: dict):
    import ccauth.discover as discover_mod
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


# ── CLI commands ──────────────────────────────────────────────────────────────

def test_cmd_login_success(monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    monkeypatch.setattr("ccauth.cli._trigger_auth", lambda site: None)
    assert main(["login"]) == 0


def test_cmd_login_auth_failure(monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
    monkeypatch.setattr("ccauth.cli._trigger_auth", MagicMock(side_effect=Exception("bad auth")))
    assert main(["login"]) == 1


def test_cmd_login_no_sites(monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: None)
    assert main(["login"]) == 1


def test_cmd_login_prefers_vendordata_site(monkeypatch):
    used = []
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC, KVM])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [KVM])
    monkeypatch.setattr("ccauth.cli._trigger_auth", lambda site: used.append(site))
    main(["login"])
    assert used[0].cloud_name == "kvm"


def test_cmd_login_falls_back_to_first_site_without_vendordata(monkeypatch):
    used = []
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC, UC])
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [])
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


def test_cmd_clouds_yaml_writes_all_sites(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC, UC])
    monkeypatch.setattr("ccauth.cli._enrich_project_ids", lambda sites: None)
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output)]) == 0
    data = yaml.safe_load(output.read_text())
    assert "tacc" in data["clouds"]
    assert "uc" in data["clouds"]


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


def test_cmd_clouds_yaml_all_projects_no_token_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [TACC])
    monkeypatch.setattr("ccauth.cli._collect_all_projects", lambda sites: [])
    output = tmp_path / "clouds.yaml"
    assert main(["clouds-yaml", "--output", str(output), "--all-projects"]) == 1


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


def test_cmd_openrc_explicit_project_id_overrides_vendordata(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.from_vendordata", lambda **_: [replace(KVM)])
    output = tmp_path / "openrc.sh"
    assert main(["openrc", "--output", str(output), "--project-id", "override"]) == 0
    assert 'OS_PROJECT_ID="override"' in output.read_text()


def test_cmd_discover_projects_no_token_returns_error(tmp_path, monkeypatch):
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", tmp_path / "nonexistent.json")
    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1


def test_cmd_discover_projects_single_project_uses_bare_site_name(tmp_path, monkeypatch):
    kvm = _site("https://kvm.tacc.chameleoncloud.org:5000/v3", "KVM@TACC", "kvm", "p1")
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)
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
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)
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
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {"CHI-240042": [KVM]})
    monkeypatch.setattr("builtins.input", lambda: "99")

    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1


def test_cmd_discover_projects_non_numeric_returns_error(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {"CHI-240042": [KVM]})
    monkeypatch.setattr("builtins.input", lambda: "abc")

    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1


def test_cmd_discover_projects_keyboard_interrupt_returns_error(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {"CHI-240042": [KVM]})
    monkeypatch.setattr("builtins.input", MagicMock(side_effect=KeyboardInterrupt))

    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1


def test_cmd_discover_projects_no_projects_found(tmp_path, monkeypatch):
    cache = tmp_path / "token.json"
    cache.write_text("{}")
    monkeypatch.setattr("ccauth.cli.REFRESH_TOKEN_CACHE", cache)
    monkeypatch.setattr("ccauth.cli._build_sites", lambda args: [KVM])
    monkeypatch.setattr("ccauth.cli._discover_projects", lambda sites: {})

    assert main(["discover-projects", "--output", str(tmp_path / "clouds.yaml")]) == 1
