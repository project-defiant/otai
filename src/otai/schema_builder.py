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
    """
    conn.execute(f'CREATE SCHEMA "{release}"')
    for dataset in datasets:
        glob_url = f"{base_uri}/{release}/output/{dataset.file_glob}"
        conn.execute(
            f'CREATE VIEW "{release}"."{dataset.name}" AS '
            f"SELECT * FROM read_parquet('{glob_url}')"
        )
