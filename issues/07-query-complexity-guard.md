# 07 - Query complexity guard for `run-sql` via `EXPLAIN`

## Type

AFK

## What to build

Add a proactive, pre-execution complexity check to `run-sql`, sitting between the existing `validate_read_only` (statement shape) and `_execute_with_timeout` (real execution) steps in `sql_guard.py`. Today the ~45s timeout is the *only* backstop against an expensive query — this adds an early, cheap rejection instead of waiting out the timeout on any runaway query.

- Run `EXPLAIN (FORMAT JSON) <query>` on the already-connected, already-schema-built connection (no execution; DuckDB's planner returns a structured plan tree with an `"Estimated Cardinality"` per operator, computed from real table/parquet statistics).
- Recursively walk the plan tree and compute, for every node, its cost estimate:
  - If the node reports its own `"Estimated Cardinality"`, use it directly (confirmed present on `SEQ_SCAN`, `HASH_JOIN`, `HASH_GROUP_BY`, `PROJECTION`, and others).
  - Otherwise apply a known-operator rulebook (empirically confirmed missing their own estimate): `CROSS_PRODUCT` → product of children's estimates; `UNION` → sum of children; `TOP_N` / `UNGROUPED_AGGREGATE` / `PERFECT_HASH_GROUP_BY` / `WINDOW` → pass through the max of children (they reduce output rows, not underlying compute cost).
  - Any operator outside this rulebook is unrecognized → **fail closed**, reject rather than guess.
- The query's complexity score is the **maximum estimate found anywhere in the tree**, not just the final output — an expensive intermediate blow-up that later aggregates down to a small result must still be caught.
- Reject with a new error type if the score exceeds a threshold; new exception `QueryTooComplexError` in `sql_guard.py`.

## Threshold

Default **2,000,000,000** (2 billion) estimated rows, overridable via a new `OTAI_MAX_ESTIMATED_ROWS` env var (`config.py`, following the existing `OTAI_CACHE_DIR`/`OTAI_BASE_URI`/`OTAI_LOG_LEVEL` pattern — no CLI flag, consistent with how `row_cap`/`timeout_seconds` are configured today).

This was calibrated against real data during scoping: `colocalisation` (the largest current Open Targets dataset) has ~236M rows, and a plain `count(*)` over it is a normal, cheap query — the threshold must sit comfortably above any legitimate single-table scan while still catching genuinely gratuitous multi-table blowups (e.g. an accidental cross join). It's a coarse safety net, not a precise cost model.

## Error handling

New envelope error type: `query_too_complex` — distinct from `guardrail_violation`, since the query *is* valid read-only SQL, just too expensive.

Two distinct rejection messages:
- **Over threshold**: names the offending operator, the estimate, and the limit, e.g. *"Query plan estimates ~5,000,000,000 rows at a CROSS_PRODUCT step (limit: 2,000,000,000); add a join condition or filters and retry."*
- **Unrecognized operator** (fail-closed gap): names the operator so it's diagnosable, e.g. *"Could not estimate query cost: unrecognized plan operator 'PIVOT'."*

`.claude/skills/otai/SKILL.md`'s error-type table and behavioral rules need a new row/branch for `query_too_complex`: same remediation family as `timeout` (narrow the query — add filters or a join condition — and retry).

## Known limitation (call out explicitly, don't silently paper over)

The operator rulebook (`CROSS_PRODUCT`, `UNION`, `TOP_N`, `UNGROUPED_AGGREGATE`, `PERFECT_HASH_GROUP_BY`, `WINDOW`) was built from operators observed during scoping (aggregates, `GROUP BY`, `DISTINCT`, `WINDOW`, `UNION`, inner/left joins, cross products) — it is **not** a verified-complete list of DuckDB's plan vocabulary. Fail-closed means a real but untested operator shape could reject a legitimate query until added to the rulebook. Since the error message names the operator specifically, gaps are diagnosable, not silent — but implementation should deliberately test a broad range of query shapes (subqueries, CTEs, more join types, `DISTINCT`, multi-level aggregation) to make the rulebook reasonably complete before shipping, and treat "unrecognized operator" reports from real usage as bugs to fix by extending the rulebook, not as expected behavior.

## Acceptance criteria

- [ ] `check_query_complexity(conn, sql, max_estimated_rows=...)` in `sql_guard.py`, called from `run_guarded_query` after `validate_read_only` succeeds and before execution.
- [ ] A query whose plan estimates more than `OTAI_MAX_ESTIMATED_ROWS` (default 2B) anywhere in the tree is rejected with `error.type: "query_too_complex"` before any execution occurs.
- [ ] The rejection message names the offending operator and both the estimate and the configured limit.
- [ ] A plan operator outside the known rulebook is rejected (fail-closed) with a message naming the unrecognized operator.
- [ ] `OTAI_MAX_ESTIMATED_ROWS` overrides the default threshold; `config.get_max_estimated_rows()` mirrors the existing `get_cache_dir`/`get_base_uri`/`get_log_level` pattern.
- [ ] Ordinary queries (single-table scans/aggregates, filtered joins with conditions, `GROUP BY`, `DISTINCT`, `WINDOW`, `UNION`, subqueries/CTEs) are unaffected — verified against fixtures large enough to exercise the rulebook's passthrough paths, not just tiny ones.
- [ ] Existing guardrails (read-only enforcement, table-function allowlist, row cap, timeout) are unaffected and still apply.
- [ ] Unit tests for the cardinality-walking logic against hand-crafted `EXPLAIN (FORMAT JSON)` fixtures (scan, cross product, join, each rulebook passthrough operator, nested combinations, an unrecognized operator) — fast, no DB needed.
- [ ] At least one real end-to-end test: two views of tens of thousands of rows each (via `range()`, created outside the guard — same pattern used for the existing timeout tests in `test_sql_guard.py`) cross-joined to estimate well over the default threshold, checked via `EXPLAIN` without ever executing the cross join.
- [ ] `SKILL.md` updated with the new error type and remediation guidance.

## Blocked by

- Blocked by #4 (guarded `run-sql`) and #5 (cross-release `run-sql`) — both already implemented on `main`; this issue can start immediately.
