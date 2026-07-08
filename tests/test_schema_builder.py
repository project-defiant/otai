import duckdb

from otai import schema_builder
from otai.croissant import DatasetInfo


def _datasets_for(dataset_rows):
    return [
        DatasetInfo(
            name=name, description=f"{name} dataset", file_glob=f"{name}/*.parquet"
        )
        for name in dataset_rows
    ]


def test_build_release_schema_creates_schema_and_queryable_views(
    fixture_release_layout,
):
    base_uri, release, dataset_rows = fixture_release_layout
    conn = duckdb.connect()
    try:
        schema_builder.build_release_schema(
            conn, release, _datasets_for(dataset_rows), base_uri=base_uri
        )

        schemas = {
            row[0]
            for row in conn.execute(
                "SELECT schema_name FROM information_schema.schemata"
            ).fetchall()
        }
        assert release in schemas

        target_rows = conn.execute(
            f'SELECT * FROM "{release}".target ORDER BY id'
        ).fetchall()
        assert len(target_rows) == len(dataset_rows["target"])
        assert target_rows[0][0] == "ENSG00000141510"  # TP53 sorts before BRAF's id
    finally:
        conn.close()


def test_build_release_schema_creates_one_view_per_dataset(fixture_release_layout):
    base_uri, release, dataset_rows = fixture_release_layout
    conn = duckdb.connect()
    try:
        schema_builder.build_release_schema(
            conn, release, _datasets_for(dataset_rows), base_uri=base_uri
        )

        views = {
            row[0]
            for row in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = ?",
                [release],
            ).fetchall()
        }
        assert views == set(dataset_rows)
    finally:
        conn.close()


def test_build_release_schema_reads_real_parquet_content(fixture_release_layout):
    base_uri, release, dataset_rows = fixture_release_layout
    conn = duckdb.connect()
    try:
        schema_builder.build_release_schema(
            conn, release, _datasets_for(dataset_rows), base_uri=base_uri
        )

        association_rows = conn.execute(
            f"SELECT targetId, diseaseId, CAST(score AS DOUBLE) FROM "
            f'"{release}".association_by_datasource_direct ORDER BY score DESC'
        ).fetchall()
        assert association_rows == [
            ("ENSG00000157764", "EFO_0000305", 0.8),
            ("ENSG00000141510", "EFO_0000616", 0.5),
        ]
    finally:
        conn.close()
