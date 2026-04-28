import stat

from ccauth.plugin import _load_refresh_token, _save_refresh_token


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
