from pathlib import Path

from otai import config


def test_default_cache_dir_is_under_user_home_cache(monkeypatch):
    monkeypatch.delenv("OTAI_CACHE_DIR", raising=False)
    assert config.get_cache_dir() == Path.home() / ".cache" / "otai"


def test_cache_dir_overridable_via_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("OTAI_CACHE_DIR", str(tmp_path / "custom-cache"))
    assert config.get_cache_dir() == tmp_path / "custom-cache"


def test_default_base_uri_is_the_public_s3_bucket(monkeypatch):
    monkeypatch.delenv("OTAI_BASE_URI", raising=False)
    assert config.get_base_uri() == "s3://open-targets-public-data-releases/platform"


def test_base_uri_overridable_via_env_var(monkeypatch):
    monkeypatch.setenv("OTAI_BASE_URI", "file:///tmp/fixtures")
    assert config.get_base_uri() == "file:///tmp/fixtures"


def test_default_log_level_is_info(monkeypatch):
    monkeypatch.delenv("OTAI_LOG_LEVEL", raising=False)
    assert config.get_log_level() == "INFO"


def test_log_level_overridable_via_env_var(monkeypatch):
    monkeypatch.setenv("OTAI_LOG_LEVEL", "DEBUG")
    assert config.get_log_level() == "DEBUG"
