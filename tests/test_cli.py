import json
from unittest.mock import patch

from typer.testing import CliRunner

from otai.cli import app
from test_croissant import CROISSANT_FIXTURE

runner = CliRunner()

SAMPLE_LISTING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <CommonPrefixes><Prefix>platform/25.12/</Prefix></CommonPrefixes>
    <CommonPrefixes><Prefix>platform/26.06/</Prefix></CommonPrefixes>
</ListBucketResult>
"""


def _invoke(args, cache_dir):
    with patch(
        "otai.releases.default_fetch_listing_xml", return_value=SAMPLE_LISTING_XML
    ):
        return runner.invoke(app, args, env={"OTAI_CACHE_DIR": str(cache_dir)})


def _invoke_with_fixtures(args, cache_dir, base_uri):
    with (
        patch(
            "otai.releases.default_fetch_listing_xml", return_value=SAMPLE_LISTING_XML
        ),
        patch(
            "otai.croissant.default_fetch_croissant",
            return_value=json.dumps(CROISSANT_FIXTURE).encode(),
        ),
    ):
        return runner.invoke(
            app,
            args,
            env={"OTAI_CACHE_DIR": str(cache_dir), "OTAI_BASE_URI": base_uri},
        )


def test_list_releases_json_output_default(tmp_path):
    result = _invoke(["list-releases"], tmp_path / "cache")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    releases = {r["release"]: r for r in payload["data"]["releases"]}
    assert releases["26.06"]["latest"] is True
    assert releases["25.12"]["latest"] is False


def test_list_releases_table_format(tmp_path):
    result = _invoke(["list-releases", "--format", "table"], tmp_path / "cache")

    assert result.exit_code == 0
    assert "release" in result.stdout
    assert "26.06" in result.stdout
    assert "yes" in result.stdout


def test_list_releases_has_no_release_flag(tmp_path):
    result = _invoke(["list-releases", "--release", "26.06"], tmp_path / "cache")
    assert result.exit_code != 0


def test_list_releases_creates_catalog_file_on_first_run(tmp_path):
    cache_dir = tmp_path / "cache"
    assert not (cache_dir / "catalog.duckdb").exists()

    _invoke(["list-releases"], cache_dir)

    assert (cache_dir / "catalog.duckdb").exists()


def test_unknown_format_is_rejected(tmp_path):
    result = _invoke(["list-releases", "--format", "yaml"], tmp_path / "cache")
    assert result.exit_code != 0


def test_list_datasets_json_output_defaults_to_latest(tmp_path, fixture_release_layout):
    base_uri, release, dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["list-datasets"], tmp_path / "cache", base_uri
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["release"] == release
    names = {d["dataset"] for d in payload["data"]["datasets"]}
    assert names == set(dataset_rows)


def test_list_datasets_table_format(tmp_path, fixture_release_layout):
    base_uri, _release, dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["list-datasets", "--format", "table"], tmp_path / "cache", base_uri
    )

    assert result.exit_code == 0
    assert "dataset" in result.stdout
    assert "description" in result.stdout
    assert "target" in result.stdout


def test_list_datasets_accepts_explicit_release(tmp_path, fixture_release_layout):
    base_uri, release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["list-datasets", "--release", release], tmp_path / "cache", base_uri
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["release"] == release


def test_describe_dataset_json_output_defaults_to_latest(tmp_path, fixture_release_layout):
    base_uri, release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["describe-dataset", "target"], tmp_path / "cache", base_uri
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["release"] == release
    assert payload["data"]["dataset"] == "target"
    fields_by_name = {f["name"]: f for f in payload["data"]["fields"]}
    assert fields_by_name["id"]["dataType"] == "sc:Text"


def test_describe_dataset_includes_references_and_subfields(tmp_path, fixture_release_layout):
    base_uri, _release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["describe-dataset", "association_by_datasource_direct"],
        tmp_path / "cache",
        base_uri,
    )

    payload = json.loads(result.stdout)
    fields_by_name = {f["name"]: f for f in payload["data"]["fields"]}
    assert fields_by_name["targetId"]["references"] == {
        "dataset": "target",
        "field": "id",
    }

    result = _invoke_with_fixtures(
        ["describe-dataset", "target"], tmp_path / "cache", base_uri
    )
    payload = json.loads(result.stdout)
    fields_by_name = {f["name"]: f for f in payload["data"]["fields"]}
    sub_by_name = {sf["name"]: sf for sf in fields_by_name["proteinIds"]["subFields"]}
    assert set(sub_by_name) == {"id", "source"}


def test_describe_dataset_table_format(tmp_path, fixture_release_layout):
    base_uri, _release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["describe-dataset", "target", "--format", "table"], tmp_path / "cache", base_uri
    )

    assert result.exit_code == 0
    assert "name" in result.stdout
    assert "dataType" in result.stdout
    assert "id" in result.stdout


def test_describe_dataset_accepts_explicit_release(tmp_path, fixture_release_layout):
    base_uri, release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["describe-dataset", "target", "--release", release], tmp_path / "cache", base_uri
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"]["release"] == release


def test_describe_dataset_unknown_dataset_returns_error(tmp_path, fixture_release_layout):
    base_uri, _release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["describe-dataset", "no_such_dataset"], tmp_path / "cache", base_uri
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "dataset_not_found"


def test_list_datasets_builds_catalog_schema_on_first_run(tmp_path, fixture_release_layout):
    base_uri, release, _dataset_rows = fixture_release_layout
    cache_dir = tmp_path / "cache"

    _invoke_with_fixtures(["list-datasets"], cache_dir, base_uri)

    import duckdb

    conn = duckdb.connect(str(cache_dir / "catalog.duckdb"))
    try:
        schemas = {
            row[0]
            for row in conn.execute(
                "SELECT schema_name FROM information_schema.schemata"
            ).fetchall()
        }
        assert release in schemas
    finally:
        conn.close()


def test_run_sql_json_output_against_latest(tmp_path, fixture_release_layout):
    base_uri, release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["run-sql", "SELECT id, approvedSymbol FROM target ORDER BY id"],
        tmp_path / "cache",
        base_uri,
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["release"] == release
    assert payload["data"]["columns"] == ["id", "approvedSymbol"]
    assert payload["data"]["rows"] == [
        ["ENSG00000141510", "TP53"],
        ["ENSG00000157764", "BRAF"],
    ]


def test_run_sql_table_format(tmp_path, fixture_release_layout):
    base_uri, _release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["run-sql", "SELECT id, approvedSymbol FROM target ORDER BY id", "--format", "table"],
        tmp_path / "cache",
        base_uri,
    )

    assert result.exit_code == 0
    assert "approvedSymbol" in result.stdout
    assert "BRAF" in result.stdout


def test_run_sql_has_no_release_flag(tmp_path, fixture_release_layout):
    base_uri, _release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["run-sql", "SELECT 1", "--release", "26.06"], tmp_path / "cache", base_uri
    )

    assert result.exit_code != 0


def test_run_sql_rejects_non_select_statement(tmp_path, fixture_release_layout):
    base_uri, _release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["run-sql", "DROP TABLE target"], tmp_path / "cache", base_uri
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "guardrail_violation"


def test_run_sql_malformed_query_returns_sql_error(tmp_path, fixture_release_layout):
    base_uri, _release, _dataset_rows = fixture_release_layout

    result = _invoke_with_fixtures(
        ["run-sql", "SELECT * FROM target WHERE ("], tmp_path / "cache", base_uri
    )

    assert result.exit_code != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["type"] == "sql_error"
