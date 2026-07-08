"""Shared DuckDB catalog file: attach-or-create, and inspection of which
release schemas have already been materialized locally.

Each Open Targets release gets its own DuckDB schema namespace inside a
single shared catalog file (see PRD §5/§6). This module only knows how to
open that file and enumerate the schemas already present in it; building
the schemas themselves (per release, from croissant.json) lives in
`schema_builder.py`.

DuckDB takes an exclusive lock for any read-write connection to a file,
so two concurrent `otai` invocations (e.g. parallel Claude Code subagents)
against the same catalog would otherwise fail nondeterministically. Two
mitigations, both used by `commands.py`:
- `try_connect_readonly` lets a caller peek at already-built schemas
  without taking the exclusive lock at all - multiple read-only
  connections coexist freely, so callers that find what they need already
  cached never need to fight over the write lock.
- `connect_catalog` (read-write, needed to build a schema) retries briefly
  on lock contention rather than failing on the first collision.
"""

from __future__ import annotations

import time
from pathlib import Path

import duckdb

CATALOG_FILENAME = "catalog.duckdb"

# Schemas DuckDB creates by default in every database; never "cached releases".
BUILTIN_SCHEMAS = {"main", "information_schema", "pg_catalog"}

# A full from-scratch schema build (one CREATE VIEW per dataset, each
# resolving a glob against real S3) measured ~18s for a 55-dataset release -
# the retry budget must comfortably outlast a concurrent writer doing that,
# not just a quick metadata write, or "retry" degrades back to "usually
# still fails" under real contention.
LOCK_RETRY_ATTEMPTS = 15
LOCK_RETRY_DELAY_SECONDS = 3.0


def get_catalog_path(cache_dir: Path) -> Path:
    """Return the predefined path of the shared DuckDB catalog file."""
    return Path(cache_dir) / CATALOG_FILENAME


def connect_catalog(cache_dir: Path) -> duckdb.DuckDBPyConnection:
    """Attach the shared catalog file read-write, creating it if absent.

    Retries briefly on lock contention (`duckdb.IOException`) from a
    concurrent writer before giving up, since most contention resolves
    within one short-lived CLI invocation's lifetime of another.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    catalog_path = str(get_catalog_path(cache_dir))
    last_exc: duckdb.IOException | None = None
    for attempt in range(LOCK_RETRY_ATTEMPTS):
        try:
            return duckdb.connect(catalog_path)
        except duckdb.IOException as exc:  # noqa: PERF203 - retry needs try/except per iteration
            last_exc = exc
            if attempt < LOCK_RETRY_ATTEMPTS - 1:
                time.sleep(LOCK_RETRY_DELAY_SECONDS)
    raise last_exc


def try_connect_readonly(cache_dir: Path) -> duckdb.DuckDBPyConnection | None:
    """Best-effort read-only connection; `None` if there's nothing to read yet
    or a concurrent writer currently holds the lock.

    Returning `None` in the lock-contention case (rather than retrying) is
    intentional: callers use this purely to avoid taking the write lock
    when possible, and fall back to `connect_catalog` (which does retry)
    when they actually need to build something.
    """
    catalog_path = get_catalog_path(Path(cache_dir))
    if not catalog_path.exists():
        return None
    try:
        return duckdb.connect(str(catalog_path), read_only=True)
    except duckdb.IOException:
        return None


def list_cached_schemas(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """List release schemas already present in the catalog (built-ins excluded)."""
    rows = conn.execute(
        "SELECT schema_name FROM information_schema.schemata"
    ).fetchall()
    return sorted({row[0] for row in rows} - BUILTIN_SCHEMAS)
