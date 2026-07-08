"""Guardrails for `otai run-sql`: read-only enforcement, row cap, and timeout.

This module is deliberately decoupled from release resolution / lazy schema
init (that lives in `commands.run_sql`): everything here operates on a
plain `duckdb.DuckDBPyConnection` and a raw SQL string, so the guardrail
logic itself - rejection, timeout, row cap, envelope shape - can be unit
tested against a local/in-memory DuckDB with synthetic tables, independent
of any Open Targets data or fixtures (PRD §10).

Read-only enforcement (PRD §7) parses the query with `sqlglot` (DuckDB
dialect) into an AST and rejects anything that isn't a single read-only
`SELECT`/`WITH` statement. Critically, this walks the *entire* AST rather
than just checking the top-level statement type, so a mutating statement
smuggled inside a CTE or subquery is still caught, e.g.:

    WITH x AS (INSERT INTO t VALUES (1) RETURNING *) SELECT * FROM x

parses as a top-level `Select` (with an `Insert` nested three levels down
inside its `WITH` clause) - a naive "does the query start with SELECT"
check would miss it entirely.
"""

from __future__ import annotations

import threading
from typing import Any

import duckdb
import sqlglot
from sqlglot import exp

from otai import envelope

DEFAULT_ROW_CAP = 1000
DEFAULT_TIMEOUT_SECONDS = 45.0
DIALECT = "duckdb"

# Anything matching one of these anywhere in the AST means the query is not
# purely a read-only SELECT/WITH: DDL (CREATE/DROP/ALTER/...), DML
# (INSERT/UPDATE/DELETE/MERGE/COPY), DuckDB-specific statements
# (ATTACH/DETACH/INSTALL/PRAGMA/SET/USE/...), transaction control, and the
# generic `Command` node sqlglot falls back to for unsupported/ambiguous
# syntax (e.g. EXPLAIN, CALL) - which we also want to reject defensively.
_DISALLOWED_NODE_TYPES: tuple[type[exp.Expression], ...] = (
    exp.DDL,
    exp.DML,
    exp.Alter,
    exp.Drop,
    exp.Attach,
    exp.Detach,
    exp.Install,
    exp.Pragma,
    exp.Command,
    exp.Set,
    exp.TruncateTable,
    exp.Cache,
    exp.Use,
    exp.Uncache,
    exp.Kill,
    exp.Export,
    exp.Analyze,
    exp.Comment,
    exp.Rollback,
    exp.Commit,
    exp.Transaction,
    exp.Grant,
    exp.Refresh,
)


class GuardrailViolationError(Exception):
    """Raised when a query fails the read-only guardrail check."""


class SqlError(Exception):
    """Raised for malformed SQL - parse failure or execution error."""


class QueryTimeoutError(Exception):
    """Raised when a query exceeds the wall-clock execution timeout."""


def _parse_statements(sql: str) -> list[exp.Expression]:
    """Parse `sql` (DuckDB dialect) into its top-level statement list.

    Shared by `validate_read_only` and `extract_schema_qualifiers` so both
    walk the same parse of the query rather than duplicating the
    `sqlglot.parse` invocation's dialect/None-filtering details. Raises
    `sqlglot.errors.ParseError` on malformed SQL - callers decide how to
    react (raise `SqlError`, or swallow it, per their own contract).
    """
    return [s for s in sqlglot.parse(sql, read=DIALECT) if s is not None]


def validate_read_only(sql: str) -> None:
    """Reject anything that is not a single read-only SELECT/WITH statement.

    Raises `SqlError` if `sql` fails to parse at all, or `GuardrailViolationError`
    if it parses but is not a single read-only query (including mutating
    statements nested inside a CTE or subquery - see module docstring).
    """
    try:
        statements = _parse_statements(sql)
    except sqlglot.errors.ParseError as exc:
        raise SqlError(f"Failed to parse SQL: {exc}") from exc

    if len(statements) != 1:
        raise GuardrailViolationError(
            "Only a single SELECT/WITH statement is allowed per run-sql call "
            f"(found {len(statements)})."
        )

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise GuardrailViolationError(
            "Only read-only SELECT/WITH statements are allowed; got a "
            f"{type(statement).__name__} statement."
        )

    for node in statement.walk():
        if isinstance(node, _DISALLOWED_NODE_TYPES):
            raise GuardrailViolationError(
                "Query contains a disallowed statement or expression "
                f"({type(node).__name__}); only read-only SELECT/WITH "
                "queries are permitted, including inside CTEs and "
                "subqueries."
            )


def extract_schema_qualifiers(sql: str) -> list[str]:
    """Collect every distinct schema/db qualifier used in `sql`'s table refs.

    Walks every `exp.Table` node in the parsed AST (PRD §6/§7, issue #5) and
    returns the sorted, deduplicated set of schema qualifiers found (e.g.
    `"26.03".target` -> `"26.03"`). Table references with no qualifier are
    not included - those resolve via `search_path` to `latest`, unchanged
    from issue #4.

    Deliberately lenient: diagnosing malformed or multi-statement SQL is
    `validate_read_only`'s job (it raises `SqlError`/`GuardrailViolationError`
    with the right error type). This function instead returns an empty list
    whenever `sql` can't be parsed into exactly one statement, so
    `commands.run_sql` can call it unconditionally before the real guardrail
    check without duplicating that error handling. It also does not care
    whether the statement is read-only - a schema-qualified table inside a
    rejected DDL/DML statement still gets extracted, since the guardrail
    check (not this function) is what ultimately rejects the query.
    """
    try:
        statements = _parse_statements(sql)
    except sqlglot.errors.ParseError:
        return []
    if len(statements) != 1:
        return []

    qualifiers = {
        node.text("db")
        for node in statements[0].walk()
        if isinstance(node, exp.Table) and node.text("db")
    }
    return sorted(qualifiers)


def _execute_with_timeout(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    timeout_seconds: float,
    fetch_limit: int,
) -> tuple[list[str], list[tuple[Any, ...]]]:
    """Run `sql` on `conn`, killing it via `conn.interrupt()` past the deadline.

    DuckDB has no built-in statement_timeout setting, so the query runs in a
    daemon worker thread while this (calling) thread waits up to
    `timeout_seconds`; if the worker is still running once the deadline
    passes, `conn.interrupt()` is called on the shared connection from this
    thread, which raises inside the worker's `execute()` call almost
    immediately - a real wall-clock cancellation, not a mocked one.
    """
    outcome: dict[str, Any] = {}

    def _target() -> None:
        try:
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(fetch_limit)
            outcome["columns"] = columns
            outcome["rows"] = rows
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller below
            outcome["error"] = exc

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    worker.join(timeout_seconds)

    if worker.is_alive():
        conn.interrupt()
        worker.join(max(timeout_seconds, 5.0))
        raise QueryTimeoutError(
            f"Query exceeded the {timeout_seconds:g}s timeout and was cancelled."
        )

    if "error" in outcome:
        raise SqlError(str(outcome["error"]))

    return outcome["columns"], outcome["rows"]


def run_guarded_query(
    conn: duckdb.DuckDBPyConnection,
    sql: str,
    row_cap: int = DEFAULT_ROW_CAP,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Validate, execute, cap, and envelope a `run-sql` query against `conn`.

    This is the guardrail core: read-only enforcement, wall-clock timeout,
    and row-cap truncation, returning the standard JSON envelope (PRD §7).
    It has no opinion on which release(s) `conn`'s search_path points at -
    that setup is `commands.run_sql`'s job.
    """
    try:
        validate_read_only(sql)
    except GuardrailViolationError as exc:
        return envelope.failure("guardrail_violation", str(exc))
    except SqlError as exc:
        return envelope.failure("sql_error", str(exc))

    try:
        columns, rows = _execute_with_timeout(
            conn, sql, timeout_seconds, fetch_limit=row_cap + 1
        )
    except QueryTimeoutError as exc:
        return envelope.failure("timeout", str(exc))
    except SqlError as exc:
        return envelope.failure("sql_error", str(exc))

    truncated = len(rows) > row_cap
    if truncated:
        rows = rows[:row_cap]

    return envelope.success(
        {
            "columns": columns,
            "rows": [list(row) for row in rows],
            "row_count": len(rows),
            "truncated": truncated,
        }
    )
