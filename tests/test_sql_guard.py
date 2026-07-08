"""Guardrail unit tests: read-only enforcement, row cap, timeout, envelope
shape - all against a local/in-memory DuckDB with synthetic tables,
independent of any real Open Targets data or fixtures (PRD §10).
"""

from __future__ import annotations

import duckdb
import pytest

from otai import sql_guard


class TestValidateReadOnly:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM target",
            "SELECT * FROM target LIMIT 10",
            "SELECT id FROM target WHERE id = 1",
            "WITH x AS (SELECT * FROM target) SELECT * FROM x",
            "SELECT * FROM target UNION SELECT * FROM target",
            "SELECT (SELECT count(*) FROM target) AS n",
        ],
    )
    def test_accepts_plain_select_and_with_queries(self, sql):
        sql_guard.validate_read_only(sql)  # must not raise

    @pytest.mark.parametrize(
        "sql",
        [
            "ATTACH 'other.db' AS other",
            "DETACH other",
            "COPY target TO 'out.csv'",
            "INSTALL httpfs",
            "PRAGMA database_list",
            "DROP TABLE target",
            "CREATE TABLE foo AS SELECT * FROM target",
            "INSERT INTO target VALUES (1)",
            "UPDATE target SET id = 1",
            "DELETE FROM target",
            "ALTER TABLE target ADD COLUMN x INT",
            "SET memory_limit = '1GB'",
            "EXPLAIN SELECT * FROM target",
            "CALL some_proc()",
        ],
    )
    def test_rejects_non_read_only_statements(self, sql):
        with pytest.raises(sql_guard.GuardrailViolation):
            sql_guard.validate_read_only(sql)

    def test_rejects_mutating_statement_nested_inside_cte(self):
        sql = "WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x"
        with pytest.raises(sql_guard.GuardrailViolation):
            sql_guard.validate_read_only(sql)

    def test_rejects_ddl_nested_inside_subquery(self):
        sql = (
            "SELECT * FROM (SELECT * FROM target) AS t "
            "WHERE t.id IN (SELECT id FROM (DROP TABLE target) AS dropped)"
        )
        with pytest.raises((sql_guard.GuardrailViolation, sql_guard.SqlError)):
            sql_guard.validate_read_only(sql)

    def test_rejects_multiple_statements(self):
        sql = "SELECT * FROM target; DROP TABLE target"
        with pytest.raises(sql_guard.GuardrailViolation):
            sql_guard.validate_read_only(sql)

    def test_malformed_sql_raises_sql_error(self):
        with pytest.raises(sql_guard.SqlError):
            sql_guard.validate_read_only("SELEKT FRUM WHERE ??")


class TestExtractSchemaQualifiers:
    def test_unqualified_table_yields_no_qualifiers(self):
        assert sql_guard.extract_schema_qualifiers("SELECT * FROM target") == []

    def test_single_qualified_table_yields_its_release(self):
        sql = 'SELECT * FROM "26.03".target'
        assert sql_guard.extract_schema_qualifiers(sql) == ["26.03"]

    def test_mixed_qualified_and_unqualified_only_collects_qualified(self):
        sql = 'SELECT * FROM "26.03".target t JOIN disease d ON 1=1'
        assert sql_guard.extract_schema_qualifiers(sql) == ["26.03"]

    def test_two_distinct_qualifiers_in_a_join_both_collected_sorted_and_deduped(self):
        sql = (
            'SELECT * FROM "26.06".target a '
            'JOIN "26.03".target b ON a.id = b.id '
            'JOIN "26.06".disease c ON 1=1'
        )
        assert sql_guard.extract_schema_qualifiers(sql) == ["26.03", "26.06"]

    def test_qualifier_inside_cte_and_subquery_is_still_collected(self):
        sql = (
            'WITH old AS (SELECT * FROM "26.03".target) '
            "SELECT * FROM old WHERE id IN (SELECT id FROM old)"
        )
        assert sql_guard.extract_schema_qualifiers(sql) == ["26.03"]

    def test_malformed_sql_returns_empty_list_rather_than_raising(self):
        # Diagnosing malformed SQL is validate_read_only's job (sql_error);
        # extraction is deliberately lenient so commands.run_sql can call it
        # unconditionally before running the real guardrail check.
        assert sql_guard.extract_schema_qualifiers("SELEKT FRUM WHERE ??") == []

    def test_multiple_statements_returns_empty_list_rather_than_raising(self):
        sql = 'SELECT * FROM "26.03".target; DROP TABLE target'
        assert sql_guard.extract_schema_qualifiers(sql) == []

    def test_qualifier_collected_even_for_non_select_statement(self):
        # Guardrail rejection of non-SELECT statements happens later in
        # validate_read_only; extraction itself just walks table refs.
        sql = 'DROP TABLE "26.03".target'
        assert sql_guard.extract_schema_qualifiers(sql) == ["26.03"]


@pytest.fixture
def synthetic_conn():
    conn = duckdb.connect()
    conn.execute("CREATE TABLE target (id INTEGER, symbol VARCHAR)")
    conn.execute("INSERT INTO target VALUES (1, 'BRAF'), (2, 'TP53'), (3, 'EGFR')")
    yield conn
    conn.close()


class TestRunGuardedQuery:
    def test_executes_select_and_returns_envelope_rows(self, synthetic_conn):
        result = sql_guard.run_guarded_query(
            synthetic_conn, "SELECT id, symbol FROM target ORDER BY id"
        )

        assert result["ok"] is True
        assert result["data"]["columns"] == ["id", "symbol"]
        assert result["data"]["rows"] == [[1, "BRAF"], [2, "TP53"], [3, "EGFR"]]
        assert result["data"]["row_count"] == 3
        assert result["data"]["truncated"] is False

    def test_non_select_returns_guardrail_violation_error(self, synthetic_conn):
        result = sql_guard.run_guarded_query(synthetic_conn, "DROP TABLE target")

        assert result["ok"] is False
        assert result["error"]["type"] == "guardrail_violation"

        # And it really wasn't executed - the table must still exist.
        rows = synthetic_conn.execute("SELECT count(*) FROM target").fetchall()
        assert rows == [(3,)]

    def test_nested_mutation_in_cte_returns_guardrail_violation_error(
        self, synthetic_conn
    ):
        sql = (
            "WITH x AS (INSERT INTO target VALUES (99, 'X') RETURNING *) "
            "SELECT * FROM x"
        )

        result = sql_guard.run_guarded_query(synthetic_conn, sql)

        assert result["ok"] is False
        assert result["error"]["type"] == "guardrail_violation"
        rows = synthetic_conn.execute("SELECT count(*) FROM target").fetchall()
        assert rows == [(3,)]

    def test_malformed_query_returns_sql_error(self, synthetic_conn):
        result = sql_guard.run_guarded_query(
            synthetic_conn, "SELECT * FROM target WHERE ("
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "sql_error"
        assert result["error"]["message"]

    def test_query_against_unknown_table_returns_sql_error(self, synthetic_conn):
        result = sql_guard.run_guarded_query(
            synthetic_conn, "SELECT * FROM no_such_table"
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "sql_error"

    def test_row_cap_truncates_and_flags_truncation(self, synthetic_conn):
        synthetic_conn.execute("CREATE TABLE big AS SELECT * FROM range(2500) AS t(n)")

        result = sql_guard.run_guarded_query(
            synthetic_conn, "SELECT n FROM big ORDER BY n", row_cap=1000
        )

        assert result["ok"] is True
        assert result["data"]["row_count"] == 1000
        assert len(result["data"]["rows"]) == 1000
        assert result["data"]["truncated"] is True
        assert result["data"]["rows"][0] == [0]
        assert result["data"]["rows"][-1] == [999]

    def test_result_under_cap_is_not_flagged_truncated(self, synthetic_conn):
        result = sql_guard.run_guarded_query(
            synthetic_conn, "SELECT * FROM target", row_cap=1000
        )

        assert result["ok"] is True
        assert result["data"]["truncated"] is False

    def test_slow_query_is_killed_and_returns_timeout_error(self, synthetic_conn):
        # A cross join over range() is cheap to set up but expensive enough
        # to reliably still be running past a very short timeout - this
        # exercises the real timeout/interrupt path against a real DuckDB
        # connection, not a mocked one (PRD §10).
        slow_sql = "SELECT count(*) FROM range(100000000) a, range(100000) b"

        result = sql_guard.run_guarded_query(
            synthetic_conn, slow_sql, timeout_seconds=0.2
        )

        assert result["ok"] is False
        assert result["error"]["type"] == "timeout"

    def test_connection_is_reusable_after_a_timeout(self, synthetic_conn):
        slow_sql = "SELECT count(*) FROM range(100000000) a, range(100000) b"
        sql_guard.run_guarded_query(synthetic_conn, slow_sql, timeout_seconds=0.2)

        # The connection must survive the interrupt and still be usable.
        result = sql_guard.run_guarded_query(synthetic_conn, "SELECT 1 AS one")
        assert result["ok"] is True
        assert result["data"]["rows"] == [[1]]
