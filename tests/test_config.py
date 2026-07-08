from pathlib import Path

from otai import config


def test_default_cache_dir_is_under_user_home_cache(monkeypatch):
    monkeypatch.delenv("OTAI_CACHE_DIR", raising=False)
    assert config.get_cache_dir() == Path.home() / ".cache" / "otai"


def test_cache_dir_overridable_via_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("OTAI_CACHE_DIR", str(tmp_path / "custom-cache"))
    assert config.get_cache_dir() == tmp_path / "custom-cache"
