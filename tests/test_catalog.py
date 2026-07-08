from pathlib import Path

import duckdb

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
