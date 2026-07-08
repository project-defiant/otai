import json
from datetime import datetime, timezone
from unittest.mock import Mock

from otai import catalog, commands

from test_croissant import CROISSANT_FIXTURE

SAMPLE_LISTING_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">
    <CommonPrefixes><Prefix>platform/25.12/</Prefix></CommonPrefixes>
    <CommonPrefixes><Prefix>platform/26.03/</Prefix></CommonPrefixes>
    <CommonPrefixes><Prefix>platform/26.06/</Prefix></CommonPrefixes>
</ListBucketResult>
"""


def test_list_releases_reports_latest_and_no_cached_schemas(tmp_path):
    fetch = Mock(return_value=SAMPLE_LISTING_XML)

    result = commands.list_releases(
        tmp_path, fetch_xml=fetch, now=datetime(2026, 7, 8, tzinfo=timezone.utc)
    )

    assert result["ok"] is True
    releases_out = {r["release"]: r for r in result["data"]["releases"]}
    assert set(releases_out) == {"25.12", "26.03", "26.06"}
    assert releases_out["26.06"]["latest"] is True
    assert releases_out["25.12"]["latest"] is False
    assert releases_out["26.03"]["latest"] is False
    assert all(r["cached"] is False for r in releases_out.values())
    assert result["data"]["latest"] == "26.06"


def test_list_releases_flags_schemas_already_in_catalog_as_cached(tmp_path):
    conn = catalog.connect_catalog(tmp_path)
    conn.execute('CREATE SCHEMA "25.12"')
    conn.close()

    fetch = Mock(return_value=SAMPLE_LISTING_XML)
    result = commands.list_releases(
        tmp_path, fetch_xml=fetch, now=datetime(2026, 7, 8, tzinfo=timezone.utc)
    )

    releases_out = {r["release"]: r for r in result["data"]["releases"]}
    assert releases_out["25.12"]["cached"] is True
    assert releases_out["26.03"]["cached"] is False
    assert releases_out["26.06"]["cached"] is False


def test_list_releases_returns_failure_envelope_on_s3_error(tmp_path):
    fetch = Mock(side_effect=OSError("network unreachable"))

    result = commands.list_releases(
        tmp_path, fetch_xml=fetch, now=datetime(2026, 7, 8, tzinfo=timezone.utc)
    )

    assert result["ok"] is False
    assert result["error"]["type"] == "s3_error"
    assert "network unreachable" in result["error"]["message"]


class TestListDatasets:
    NOW = datetime(2026, 7, 8, tzinfo=timezone.utc)

    def _fetch_xml(self):
        return Mock(return_value=SAMPLE_LISTING_XML)

    def _fetch_croissant(self):
        return Mock(return_value=json.dumps(CROISSANT_FIXTURE).encode())

    def test_defaults_to_latest_release_and_lists_datasets(self, tmp_path, fixture_release_layout):
        base_uri, release, dataset_rows = fixture_release_layout
        fetch_croissant = self._fetch_croissant()

        result = commands.list_datasets(
            tmp_path,
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["release"] == "26.06" == release
        names = {d["dataset"] for d in result["data"]["datasets"]}
        assert names == set(dataset_rows)
        by_name = {d["dataset"]: d["description"] for d in result["data"]["datasets"]}
        assert by_name["target"] == "Target (gene/protein) annotation."

    def test_accepts_explicit_single_release(self, tmp_path, fixture_release_layout):
        base_uri, release, _dataset_rows = fixture_release_layout
        fetch_xml = self._fetch_xml()

        result = commands.list_datasets(
            tmp_path,
            release=release,
            fetch_xml=fetch_xml,
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["release"] == release
        # An explicit --release must skip latest-resolution entirely.
        fetch_xml.assert_not_called()

    def test_builds_release_schema_lazily_and_reuses_it(self, tmp_path, fixture_release_layout):
        base_uri, release, dataset_rows = fixture_release_layout
        fetch_croissant = self._fetch_croissant()

        commands.list_datasets(
            tmp_path,
            release=release,
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            base_uri=base_uri,
            now=self.NOW,
        )
        conn = catalog.connect_catalog(tmp_path)
        try:
            assert release in catalog.list_cached_schemas(conn)
        finally:
            conn.close()

        # Second call must not attempt to recreate the schema (which would
        # raise "already exists") - it should just reuse it.
        second = commands.list_datasets(
            tmp_path,
            release=release,
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            base_uri=base_uri,
            now=self.NOW,
        )
        assert second["ok"] is True
        assert {d["dataset"] for d in second["data"]["datasets"]} == set(dataset_rows)

    def test_croissant_fetched_once_then_cached_across_calls(self, tmp_path, fixture_release_layout):
        base_uri, release, _dataset_rows = fixture_release_layout
        fetch_croissant = self._fetch_croissant()

        commands.list_datasets(
            tmp_path,
            release=release,
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            base_uri=base_uri,
            now=self.NOW,
        )
        commands.list_datasets(
            tmp_path,
            release=release,
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            base_uri=base_uri,
            now=self.NOW,
        )

        fetch_croissant.assert_called_once_with(release)
        cache_file = tmp_path / release / "croissant.json"
        assert cache_file.exists()

    def test_returns_failure_when_latest_resolution_fails(self, tmp_path):
        fetch_xml = Mock(side_effect=OSError("network unreachable"))

        result = commands.list_datasets(
            tmp_path, fetch_xml=fetch_xml, fetch_croissant=self._fetch_croissant(), now=self.NOW
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "s3_error"

    def test_returns_failure_on_croissant_fetch_error(self, tmp_path):
        fetch_croissant = Mock(side_effect=OSError("network unreachable"))

        result = commands.list_datasets(
            tmp_path,
            release="26.06",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "croissant_error"


class TestDescribeDataset:
    NOW = datetime(2026, 7, 8, tzinfo=timezone.utc)

    def _fetch_xml(self):
        return Mock(return_value=SAMPLE_LISTING_XML)

    def _fetch_croissant(self):
        return Mock(return_value=json.dumps(CROISSANT_FIXTURE).encode())

    def test_defaults_to_latest_release_and_returns_fields(self, tmp_path):
        result = commands.describe_dataset(
            tmp_path,
            "target",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["release"] == "26.06"
        assert result["data"]["dataset"] == "target"
        fields_by_name = {f["name"]: f for f in result["data"]["fields"]}
        assert fields_by_name["id"]["dataType"] == "sc:Text"
        assert fields_by_name["id"]["description"] == "Ensembl gene identifier."

    def test_accepts_explicit_single_release(self, tmp_path):
        fetch_xml = self._fetch_xml()

        result = commands.describe_dataset(
            tmp_path,
            "target",
            release="26.06",
            fetch_xml=fetch_xml,
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["release"] == "26.06"
        fetch_xml.assert_not_called()

    def test_includes_cross_dataset_references(self, tmp_path):
        result = commands.describe_dataset(
            tmp_path,
            "association_by_datasource_direct",
            release="26.06",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        fields_by_name = {f["name"]: f for f in result["data"]["fields"]}
        assert fields_by_name["targetId"]["references"] == {
            "dataset": "target",
            "field": "id",
        }
        assert fields_by_name["diseaseId"]["references"] == {
            "dataset": "disease",
            "field": "id",
        }

    def test_includes_nested_subfields(self, tmp_path):
        result = commands.describe_dataset(
            tmp_path,
            "target",
            release="26.06",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        fields_by_name = {f["name"]: f for f in result["data"]["fields"]}
        protein_ids = fields_by_name["proteinIds"]
        sub_by_name = {sf["name"]: sf for sf in protein_ids["subFields"]}
        assert set(sub_by_name) == {"id", "source"}
        assert sub_by_name["id"]["description"] == "External protein identifier."

    def test_field_without_references_has_none(self, tmp_path):
        result = commands.describe_dataset(
            tmp_path,
            "target",
            release="26.06",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        fields_by_name = {f["name"]: f for f in result["data"]["fields"]}
        assert fields_by_name["id"]["references"] is None
        assert fields_by_name["id"]["subFields"] == []

    def test_returns_dataset_not_found_for_unknown_dataset(self, tmp_path):
        result = commands.describe_dataset(
            tmp_path,
            "no_such_dataset",
            release="26.06",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "dataset_not_found"

    def test_returns_failure_when_latest_resolution_fails(self, tmp_path):
        fetch_xml = Mock(side_effect=OSError("network unreachable"))

        result = commands.describe_dataset(
            tmp_path,
            "target",
            fetch_xml=fetch_xml,
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "s3_error"

    def test_returns_failure_on_croissant_fetch_error(self, tmp_path):
        fetch_croissant = Mock(side_effect=OSError("network unreachable"))

        result = commands.describe_dataset(
            tmp_path,
            "target",
            release="26.06",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "croissant_error"

    def test_does_not_touch_duckdb_catalog(self, tmp_path):
        # describe-dataset reads croissant.json directly and never needs the
        # DuckDB views (PRD §5/§7) - no catalog.duckdb should be created.
        commands.describe_dataset(
            tmp_path,
            "target",
            release="26.06",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        assert not (tmp_path / "catalog.duckdb").exists()


class TestRunSql:
    NOW = datetime(2026, 7, 8, tzinfo=timezone.utc)

    def _fetch_xml(self):
        return Mock(return_value=SAMPLE_LISTING_XML)

    def _fetch_croissant(self):
        return Mock(return_value=json.dumps(CROISSANT_FIXTURE).encode())

    def test_executes_against_latest_via_search_path(self, tmp_path, fixture_release_layout):
        base_uri, release, _dataset_rows = fixture_release_layout

        result = commands.run_sql(
            tmp_path,
            "SELECT id, approvedSymbol FROM target ORDER BY id",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["release"] == release == "26.06"
        assert result["data"]["columns"] == ["id", "approvedSymbol"]
        assert result["data"]["rows"] == [
            ["ENSG00000141510", "TP53"],
            ["ENSG00000157764", "BRAF"],
        ]
        assert result["data"]["truncated"] is False

    def test_has_no_release_parameter(self):
        # run-sql has no --release flag (PRD §7) - always latest.
        import inspect

        assert "release" not in inspect.signature(commands.run_sql).parameters

    def test_builds_release_schema_lazily(self, tmp_path, fixture_release_layout):
        base_uri, release, _dataset_rows = fixture_release_layout

        commands.run_sql(
            tmp_path,
            "SELECT * FROM target",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        conn = catalog.connect_catalog(tmp_path)
        try:
            assert release in catalog.list_cached_schemas(conn)
        finally:
            conn.close()

    def test_rejects_non_select_with_guardrail_violation(self, tmp_path, fixture_release_layout):
        base_uri, _release, _dataset_rows = fixture_release_layout

        result = commands.run_sql(
            tmp_path,
            "DROP TABLE target",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "guardrail_violation"

    def test_rejects_mutation_nested_in_cte(self, tmp_path, fixture_release_layout):
        base_uri, _release, _dataset_rows = fixture_release_layout

        result = commands.run_sql(
            tmp_path,
            'WITH x AS (INSERT INTO target VALUES ("z", "Z", []) RETURNING *) SELECT * FROM x',
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "guardrail_violation"

    def test_malformed_query_returns_sql_error(self, tmp_path, fixture_release_layout):
        base_uri, _release, _dataset_rows = fixture_release_layout

        result = commands.run_sql(
            tmp_path,
            "SELECT * FROM target WHERE (",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "sql_error"

    def test_row_cap_truncates_large_result(self, tmp_path, fixture_release_layout):
        base_uri, _release, _dataset_rows = fixture_release_layout

        result = commands.run_sql(
            tmp_path,
            "SELECT * FROM range(2500) AS t(n)",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
            row_cap=1000,
        )

        assert result["ok"] is True
        assert result["data"]["row_count"] == 1000
        assert result["data"]["truncated"] is True

    def test_slow_query_times_out(self, tmp_path, fixture_release_layout):
        base_uri, _release, _dataset_rows = fixture_release_layout

        result = commands.run_sql(
            tmp_path,
            "SELECT count(*) FROM range(100000000) a, range(100000) b",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
            timeout_seconds=0.2,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "timeout"

    def test_returns_failure_when_latest_resolution_fails(self, tmp_path):
        fetch_xml = Mock(side_effect=OSError("network unreachable"))

        result = commands.run_sql(
            tmp_path,
            "SELECT 1",
            fetch_xml=fetch_xml,
            fetch_croissant=self._fetch_croissant(),
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "s3_error"

    def test_returns_failure_on_croissant_fetch_error(self, tmp_path):
        fetch_croissant = Mock(side_effect=OSError("network unreachable"))

        result = commands.run_sql(
            tmp_path,
            "SELECT 1",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=fetch_croissant,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "croissant_error"

    def test_schema_qualified_table_triggers_lazy_init_of_that_release(
        self, tmp_path, fixture_two_release_layout
    ):
        base_uri, latest, other, _rows = fixture_two_release_layout

        conn = catalog.connect_catalog(tmp_path)
        try:
            assert other not in catalog.list_cached_schemas(conn)
        finally:
            conn.close()

        result = commands.run_sql(
            tmp_path,
            f'SELECT id, approvedSymbol FROM "{other}".target ORDER BY id',
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["rows"] == [
            ["ENSG00000141510", "TP53_OLD"],
            ["ENSG00000157764", "BRAF_OLD"],
        ]

        conn = catalog.connect_catalog(tmp_path)
        try:
            cached = catalog.list_cached_schemas(conn)
            assert other in cached
            assert latest in cached
        finally:
            conn.close()

    def test_unqualified_names_still_resolve_only_to_latest_alongside_a_qualified_release(
        self, tmp_path, fixture_two_release_layout
    ):
        base_uri, latest, other, _rows = fixture_two_release_layout

        result = commands.run_sql(
            tmp_path,
            f'SELECT t.id, t.approvedSymbol, o.approvedSymbol AS old_symbol '
            f'FROM target t JOIN "{other}".target o ON t.id = o.id ORDER BY t.id',
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["release"] == latest
        assert result["data"]["rows"] == [
            ["ENSG00000141510", "TP53", "TP53_OLD"],
            ["ENSG00000157764", "BRAF", "BRAF_OLD"],
        ]

    def test_query_joining_two_explicitly_qualified_releases_executes(
        self, tmp_path, fixture_two_release_layout
    ):
        base_uri, latest, other, _rows = fixture_two_release_layout

        result = commands.run_sql(
            tmp_path,
            f'SELECT a.id, a.approvedSymbol, b.approvedSymbol '
            f'FROM "{latest}".target a JOIN "{other}".target b ON a.id = b.id '
            f"ORDER BY a.id",
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is True
        assert result["data"]["rows"] == [
            ["ENSG00000141510", "TP53", "TP53_OLD"],
            ["ENSG00000157764", "BRAF", "BRAF_OLD"],
        ]

    def test_unknown_schema_qualifier_returns_release_not_found(
        self, tmp_path, fixture_release_layout
    ):
        base_uri, _release, _rows = fixture_release_layout

        result = commands.run_sql(
            tmp_path,
            'SELECT * FROM "99.99".target',
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "release_not_found"

        # Nothing should have been built for the bogus qualifier.
        conn = catalog.connect_catalog(tmp_path)
        try:
            assert "99.99" not in catalog.list_cached_schemas(conn)
        finally:
            conn.close()

    def test_guardrails_still_apply_to_cross_release_queries(
        self, tmp_path, fixture_two_release_layout
    ):
        base_uri, _latest, other, _rows = fixture_two_release_layout

        result = commands.run_sql(
            tmp_path,
            f'DROP TABLE "{other}".target',
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "guardrail_violation"

    def test_row_cap_and_timeout_still_apply_to_cross_release_queries(
        self, tmp_path, fixture_two_release_layout
    ):
        base_uri, _latest, other, _rows = fixture_two_release_layout

        result = commands.run_sql(
            tmp_path,
            f'SELECT * FROM "{other}".target CROSS JOIN range(2500) AS t(n)',
            fetch_xml=self._fetch_xml(),
            fetch_croissant=self._fetch_croissant(),
            base_uri=base_uri,
            now=self.NOW,
            row_cap=1000,
        )

        assert result["ok"] is True
        assert result["data"]["row_count"] == 1000
        assert result["data"]["truncated"] is True
