# 04 - Guarded query engine: `run-sql` (latest release only)

## Type

AFK

## What to build

Implement `otai run-sql "<query>"` restricted to the `latest` release (unqualified table names), with its core guardrails.

- Execute a read-only DuckDB SQL query against the `latest` release's views, with `latest` set as the default DuckDB `search_path` so unqualified table names resolve there.
- **Read-only enforcement**: parse the query with `sqlglot` (DuckDB dialect) into an AST and reject anything that isn't a single read-only `SELECT`/`WITH` statement — must catch `ATTACH`/`COPY`/`INSTALL`/`PRAGMA`/DDL/DML anywhere in the statement, including inside CTEs/subqueries.
- **Row cap**: truncate results at ~1,000 rows; response indicates truncation occurred.
- **Query timeout**: kill queries running longer than ~30–60s and return a `timeout` error.
- Results and errors conform to the JSON envelope: `{"ok": true, "data": {...}}` / `{"ok": false, "error": {"type": "guardrail_violation | timeout | sql_error", "message": "..."}}`.

## Acceptance criteria

- [ ] `otai run-sql "SELECT ... FROM target LIMIT 10"` executes against `latest`'s views and returns rows in the JSON envelope / table format.
- [ ] A non-`SELECT`/`WITH` statement (e.g. `ATTACH`, `COPY`, `DROP`, or DDL/DML nested inside a CTE or subquery) is rejected with `error.type: "guardrail_violation"` before execution.
- [ ] A query returning more than ~1,000 rows is truncated and the response indicates truncation occurred.
- [ ] A query exceeding the timeout is killed and returns `error.type: "timeout"`.
- [ ] A malformed query returns `error.type: "sql_error"` with a useful message.
- [ ] Guardrail logic (rejection, timeout, row cap, envelope shape) is unit tested against a local/in-memory DuckDB with synthetic tables — independent of real Open Targets data or fixtures.

## Blocked by

- Blocked by #2
