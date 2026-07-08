from unittest.mock import patch

import pytest

from otai import json_cache


def test_read_json_or_none_returns_none_when_file_absent(tmp_path):
    assert json_cache.read_json_or_none(tmp_path / "missing.json") is None


def test_read_json_or_none_reads_valid_json(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"a": 1}')

    assert json_cache.read_json_or_none(path) == {"a": 1}


def test_read_json_or_none_treats_corrupt_file_as_a_miss(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not json")

    assert json_cache.read_json_or_none(path) is None


def test_write_json_atomic_creates_parent_dir_and_writes(tmp_path):
    path = tmp_path / "nested" / "cache.json"

    json_cache.write_json_atomic(path, {"a": 1})

    assert json_cache.read_json_or_none(path) == {"a": 1}


def test_write_json_atomic_leaves_no_leftover_temp_file(tmp_path):
    path = tmp_path / "cache.json"

    json_cache.write_json_atomic(path, {"a": 1})

    remaining = list(tmp_path.iterdir())
    assert remaining == [path]


def test_failed_write_cleans_up_temp_file_and_leaves_original_untouched(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text('{"original": true}')

    with (
        patch("otai.json_cache.os.replace", side_effect=OSError("disk full")),
        pytest.raises(OSError, match="disk full"),
    ):
        json_cache.write_json_atomic(path, {"new": True})

    remaining = list(path.parent.iterdir())
    assert remaining == [path]
    assert path.read_text() == '{"original": true}'
