from unittest.mock import patch

import duckdb
import pytest

from otai import catalog


def test_catalog_path_is_under_cache_dir(tmp_path):
    assert catalog.get_catalog_path(tmp_path) == tmp_path / "catalog.duckdb"


def test_connect_creates_catalog_file_when_absent(tmp_path):
    catalog_path = catalog.get_catalog_path(tmp_path)
    assert not catalog_path.exists()

    conn = catalog.connect_catalog(tmp_path)
    try:
        assert catalog_path.exists()
    finally:
        conn.close()


def test_connect_reuses_existing_catalog_file(tmp_path):
    conn1 = catalog.connect_catalog(tmp_path)
    conn1.execute('CREATE SCHEMA "26.06"')
    conn1.close()

    conn2 = catalog.connect_catalog(tmp_path)
    try:
        schemas = catalog.list_cached_schemas(conn2)
        assert "26.06" in schemas
    finally:
        conn2.close()


def test_list_cached_schemas_excludes_builtin_schemas(tmp_path):
    conn = catalog.connect_catalog(tmp_path)
    try:
        assert catalog.list_cached_schemas(conn) == []
    finally:
        conn.close()


def test_connect_creates_parent_cache_dir_if_missing(tmp_path):
    nested = tmp_path / "does" / "not" / "exist"
    assert not nested.exists()

    conn = catalog.connect_catalog(nested)
    try:
        assert nested.exists()
        assert (nested / "catalog.duckdb").exists()
    finally:
        conn.close()


def test_connect_catalog_retries_then_succeeds_on_lock_contention(tmp_path):
    real_connect = duckdb.connect
    calls = []

    def flaky_connect(path, *args, **kwargs):
        calls.append(path)
        if len(calls) < 3:
            raise duckdb.IOException("Could not set lock on file (simulated)")
        return real_connect(path, *args, **kwargs)

    with (
        patch("otai.catalog.duckdb.connect", side_effect=flaky_connect),
        patch("otai.catalog.time.sleep"),
    ):
        conn = catalog.connect_catalog(tmp_path)
    try:
        assert len(calls) == 3
    finally:
        conn.close()


def test_connect_catalog_raises_after_exhausting_retries(tmp_path):
    def always_locked(path, *args, **kwargs):
        raise duckdb.IOException("Could not set lock on file (simulated)")

    with (
        patch("otai.catalog.duckdb.connect", side_effect=always_locked),
        patch("otai.catalog.time.sleep"),
        pytest.raises(duckdb.IOException),
    ):
        catalog.connect_catalog(tmp_path)


def test_try_connect_readonly_returns_none_when_catalog_does_not_exist(tmp_path):
    assert catalog.try_connect_readonly(tmp_path) is None


def test_try_connect_readonly_reads_existing_schemas(tmp_path):
    conn = catalog.connect_catalog(tmp_path)
    conn.execute('CREATE SCHEMA "26.06"')
    conn.close()

    ro_conn = catalog.try_connect_readonly(tmp_path)
    assert ro_conn is not None
    try:
        assert "26.06" in catalog.list_cached_schemas(ro_conn)
    finally:
        ro_conn.close()


def test_try_connect_readonly_returns_none_on_lock_contention(tmp_path):
    catalog.connect_catalog(tmp_path).close()  # ensure the file exists

    def always_locked(path, *args, **kwargs):
        raise duckdb.IOException("Could not set lock on file (simulated)")

    with patch("otai.catalog.duckdb.connect", side_effect=always_locked):
        assert catalog.try_connect_readonly(tmp_path) is None
