import json
from io import BytesIO

from ccauth import discover
from ccauth import _urlutils as urlutils


def test_from_reference_api_parses_response(monkeypatch):
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
        resp = BytesIO(api_response.encode())
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: None
        return resp

    monkeypatch.setattr(discover.urllib.request, "urlopen", fake_urlopen)

    sites = discover.from_reference_api()
    assert len(sites) == 2
    assert sites[0].auth_url == "https://chi.uc.chameleoncloud.org:5000/v3"
    assert sites[0].region_name == "CHI@UC"
    assert sites[0].cloud_name == "uc"
    assert sites[1].cloud_name == "tacc"


def test_from_reference_api_skips_incomplete_items(monkeypatch):
    api_response = json.dumps(
        {
            "items": [
                {"uid": "uc", "name": "CHI@UC", "web": "https://chi.uc.example.org"},
                {"uid": "", "name": "no-uid", "web": "https://x.example.org"},
                {"uid": "y", "name": "no-web", "web": ""},
            ]
        }
    )

    def fake_urlopen(url, timeout=None):
        resp = BytesIO(api_response.encode())
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: None
        return resp

    monkeypatch.setattr(discover.urllib.request, "urlopen", fake_urlopen)
    sites = discover.from_reference_api()
    assert len(sites) == 1
    assert sites[0].cloud_name == "uc"


def test_from_reference_api_handles_unreachable(monkeypatch):
    def fake_urlopen(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(discover.urllib.request, "urlopen", fake_urlopen)
    assert discover.from_reference_api() == []


def test_base_url_strips_v3():
    assert urlutils.auth_url_base("https://x:5000/v3") == "https://x:5000"
    assert urlutils.auth_url_base("https://x:5000/v3/") == "https://x:5000"
    assert urlutils.auth_url_base("https://x:5000/") == "https://x:5000"
    assert urlutils.auth_url_base("https://x:5000") == "https://x:5000"


def test_list_projects_at_calls_keystone():
    class FakeAuth:
        auth_url = "https://chi.uc.example.org:5000/v3"

    class FakeResponse:
        @staticmethod
        def json():
            return {"projects": [{"id": "p1", "name": "Chameleon"}]}

    calls = []

    class FakeSession:
        auth = FakeAuth()

        def get(self, url, authenticated):
            calls.append((url, authenticated))
            return FakeResponse()

    projects = discover.list_projects_at(FakeSession())
    assert projects == [{"id": "p1", "name": "Chameleon"}]
    assert calls == [("https://chi.uc.example.org:5000/v3/auth/projects", True)]
