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


@pytest.fixture
def fixture_release_layout(tmp_path):
    """Write fixture parquet files for FIXTURE_RELEASE under tmp_path.

    Returns (base_uri, release, dataset_rows) where base_uri is a
    file:// URI whose <release>/output/<dataset>/*.parquet layout mirrors
    the real S3 bucket layout.
    """
    conn = duckdb.connect()
    try:
        for dataset, rows in FIXTURE_DATASET_ROWS.items():
            dataset_dir = tmp_path / FIXTURE_RELEASE / "output" / dataset
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

    base_uri = f"file://{tmp_path}"
    return base_uri, FIXTURE_RELEASE, FIXTURE_DATASET_ROWS
