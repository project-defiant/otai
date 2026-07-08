"""Shared pytest fixtures.

`fixture_release_layout` writes tiny fixture parquet files (via DuckDB's
own COPY, so no extra pyarrow dependency is needed) laid out exactly like
a real release: <base_uri>/<release>/output/<dataset>/*.parquet. Tests
point the schema-builder's injectable base_uri at this local directory
(via a file:// URI) so DuckDB's real read_parquet() runs unmodified
against fixtures, with no S3/mock-S3-server involved (PRD §10).
"""

from __future__ import annotations

import duckdb
import pytest

FIXTURE_RELEASE = "26.06"
OTHER_FIXTURE_RELEASE = "26.03"

# name -> rows (list of dicts, uniform keys per dataset)
FIXTURE_DATASET_ROWS = {
    "target": [
        {"id": "ENSG00000157764", "approvedSymbol": "BRAF"},
        {"id": "ENSG00000141510", "approvedSymbol": "TP53"},
    ],
    "disease": [
        {"id": "EFO_0000305", "name": "breast carcinoma"},
        {"id": "EFO_0000616", "name": "neoplasm"},
    ],
    "association_by_datasource_direct": [
        {"targetId": "ENSG00000157764", "diseaseId": "EFO_0000305", "score": 0.8},
        {"targetId": "ENSG00000141510", "diseaseId": "EFO_0000616", "score": 0.5},
    ],
}

# A second release's fixture data, deliberately distinct from
# FIXTURE_DATASET_ROWS (but with the same table/column shape) so
# cross-release joins in tests have something meaningful to tell apart.
OTHER_FIXTURE_DATASET_ROWS = {
    "target": [
        {"id": "ENSG00000157764", "approvedSymbol": "BRAF_OLD"},
        {"id": "ENSG00000141510", "approvedSymbol": "TP53_OLD"},
    ],
    "disease": [
        {"id": "EFO_0000305", "name": "breast carcinoma (old)"},
        {"id": "EFO_0000616", "name": "neoplasm (old)"},
    ],
    "association_by_datasource_direct": [
        {"targetId": "ENSG00000157764", "diseaseId": "EFO_0000305", "score": 0.1},
        {"targetId": "ENSG00000141510", "diseaseId": "EFO_0000616", "score": 0.2},
    ],
}


def _write_release_fixture(base_dir, release: str, dataset_rows: dict) -> None:
    """Write one release's fixture parquet files under `base_dir`.

    Layout mirrors the real S3 bucket: <base_dir>/<release>/output/<dataset>/*.parquet.
    """
    conn = duckdb.connect()
    try:
        for dataset, rows in dataset_rows.items():
            dataset_dir = base_dir / release / "output" / dataset
            dataset_dir.mkdir(parents=True)
            columns = list(rows[0].keys())
            values_sql = ", ".join(
                "(" + ", ".join(repr(row[c]) for c in columns) + ")" for row in rows
            )
            column_list = ", ".join(columns)
            conn.execute(
                f"COPY (SELECT * FROM (VALUES {values_sql}) AS t({column_list})) "
                f"TO '{dataset_dir / 'part-0.parquet'}' (FORMAT PARQUET)"
            )
    finally:
        conn.close()


@pytest.fixture
def fixture_release_layout(tmp_path):
    """Write fixture parquet files for FIXTURE_RELEASE under tmp_path.

    Returns (base_uri, release, dataset_rows) where base_uri is a
    file:// URI whose <release>/output/<dataset>/*.parquet layout mirrors
    the real S3 bucket layout.
    """
    _write_release_fixture(tmp_path, FIXTURE_RELEASE, FIXTURE_DATASET_ROWS)
    base_uri = f"file://{tmp_path}"
    return base_uri, FIXTURE_RELEASE, FIXTURE_DATASET_ROWS


@pytest.fixture
def fixture_two_release_layout(tmp_path):
    """Write fixture parquet files for two distinct releases under tmp_path.

    Lets tests exercise a real cross-release DuckDB join (issue #5) against
    local fixtures rather than mocking. Returns (base_uri, latest_release,
    other_release, dataset_rows_by_release).
    """
    _write_release_fixture(tmp_path, FIXTURE_RELEASE, FIXTURE_DATASET_ROWS)
    _write_release_fixture(tmp_path, OTHER_FIXTURE_RELEASE, OTHER_FIXTURE_DATASET_ROWS)
    base_uri = f"file://{tmp_path}"
    return (
        base_uri,
        FIXTURE_RELEASE,
        OTHER_FIXTURE_RELEASE,
        {
            FIXTURE_RELEASE: FIXTURE_DATASET_ROWS,
            OTHER_FIXTURE_RELEASE: OTHER_FIXTURE_DATASET_ROWS,
        },
    )
