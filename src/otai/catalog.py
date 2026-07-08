"""Shared DuckDB catalog file: attach-or-create, and inspection of which
release schemas have already been materialized locally.

Each Open Targets release gets its own DuckDB schema namespace inside a
single shared catalog file (see PRD §5/§6). This module only knows how to
open that file and enumerate the schemas already present in it; building
the schemas themselves (per release, from croissant.json) is out of scope
for this vertical slice and lands in a later issue.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

CATALOG_FILENAME = "catalog.duckdb"

# Schemas DuckDB creates by default in every database; never "cached releases".
BUILTIN_SCHEMAS = {"main", "information_schema", "pg_catalog"}


def get_catalog_path(cache_dir: Path) -> Path:
    """Return the predefined path of the shared DuckDB catalog file."""
    return Path(cache_dir) / CATALOG_FILENAME


def connect_catalog(cache_dir: Path) -> duckdb.DuckDBPyConnection:
    """Attach the shared catalog file, creating it (and its parent dir) if absent."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = get_catalog_path(cache_dir)
    return duckdb.connect(str(catalog_path))


def list_cached_schemas(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """List release schemas already present in the catalog (built-ins excluded)."""
    rows = conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
    return sorted({row[0] for row in rows} - BUILTIN_SCHEMAS)
