"""Lazy DuckDB schema/view construction for a single release.

Implements PRD §6 step 3b of the implicit initialization pipeline: given a
release's parsed croissant dataset list, create that release's DuckDB
schema and one view per dataset, backed by `read_parquet()` over the
dataset's file glob.

The base URI is injectable (defaults to the real S3 bucket in production)
so tests can point it at a local directory of fixture parquet files via a
file:// URI, exercising DuckDB's real read_parquet() unmodified against
fixtures rather than mocking DuckDB itself (PRD §10).
"""

from __future__ import annotations

import duckdb

from otai.config import DEFAULT_BASE_URI
from otai.croissant import DatasetInfo

__all__ = ["DEFAULT_BASE_URI", "build_release_schema"]


def _ensure_httpfs(conn: duckdb.DuckDBPyConnection, base_uri: str) -> None:
    """Install/load `httpfs` when `base_uri` is a real S3 URL (PRD §3).

    Explicit rather than relying on DuckDB's autoinstall/autoload defaults,
    which are runtime-configurable and not guaranteed. Gated on scheme so
    tests pointing `base_uri` at a local `file://` fixture (PRD §10) never
    trigger a network call for the extension itself.
    """
    if base_uri.startswith("s3://"):
        conn.execute("INSTALL httpfs")
        conn.execute("LOAD httpfs")


def build_release_schema(
    conn: duckdb.DuckDBPyConnection,
    release: str,
    datasets: list[DatasetInfo],
    base_uri: str = DEFAULT_BASE_URI,
) -> None:
    """Create `"<release>"` schema plus one view per dataset (PRD §6).

    Each view is `CREATE VIEW "<release>"."<dataset>" AS SELECT * FROM
    read_parquet('<base_uri>/<release>/output/<dataset-fileset-glob>')`.
    Assumes the release schema does not already exist; callers are
    responsible for the exists-check (see commands.list_datasets).

    Runs as a single transaction: DuckDB DDL is transactional, so a
    mid-loop failure (e.g. one dataset's glob resolving to nothing) rolls
    back the `CREATE SCHEMA` too, instead of leaving a partially-built
    schema that `list_cached_schemas` would then mistake for "already
    initialized" on the next call.
    """
    _ensure_httpfs(conn, base_uri)
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute(f'CREATE SCHEMA "{release}"')
        for dataset in datasets:
            glob_url = f"{base_uri}/{release}/output/{dataset.file_glob}"
            # release/dataset names come from trusted S3/croissant data, not
            # user input; DuckDB has no parameterized-identifier syntax to
            # use instead.
            create_view_sql = (
                f'CREATE VIEW "{release}"."{dataset.name}" AS '  # noqa: S608
                f"SELECT * FROM read_parquet('{glob_url}')"
            )
            conn.execute(create_view_sql)
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")
