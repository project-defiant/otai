# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```sh
make dev              # uv sync --all-groups + install the prek pre-commit hook
make lint             # ruff check . && ruff format --check . && ty check
make test             # pytest (168 tests, fully offline, ~2.5s)
make clean            # remove .venv, caches, build artifacts

uv run pytest tests/test_sql_guard.py            # single test file
uv run pytest tests/test_sql_guard.py -k timeout # single test by name/keyword
uv run ruff check . --fix                        # auto-fix lint findings
uv run ruff format .                             # apply formatting
uv run ty check                                  # type check only

uvx --from . otai list-releases
uvx --from . otai run-sql "SELECT count(*) FROM target" --format table
```

`main` is protected: PRs must pass the `Check` CI workflow (pytest + ty in
one job, `prek --all-files` in another) before merging. See
[CONTRIBUTING.md](CONTRIBUTING.md) for the branch/PR workflow.

## Architecture

`otai` is a CLI (`src/otai/cli.py`, Typer) that answers questions about
Open Targets Platform data by running DuckDB SQL directly against parquet
files on a public, anonymous-access S3 bucket — no local data
materialization. A paired Claude Code Skill
(`.claude/skills/otai/SKILL.md`) drives the same CLI from natural-language
questions. Full design rationale lives in [PRD.md](PRD.md).

### Request flow (the part that spans files)

Every command shares an **implicit init pipeline**, factored into
`commands.py`'s `_resolve_release` / `_load_datasets` (combined for the
common case as `_resolve_release_and_datasets`) / `_ensure_release_schema`
helpers, called in the same sequence by `list_datasets`, `describe_dataset`,
and `run_sql`:

1. **Resolve the release** — an explicit `--release`, or `latest` via
   `releases.get_releases()` (lists the S3 bucket, lexically-max release
   name, cached with a 24h TTL — `releases.py`).
2. **Load that release's dataset catalog** — `croissant.get_croissant()`
   fetches and *permanently* caches `croissant.json` (release data is
   immutable, unlike the 24h "latest" cache), then `croissant.parse_datasets()`
   extracts dataset names, field-level types/descriptions, cross-dataset
   `references`, and nested `subField`s from the Croissant 1.0 JSON-LD shape.
3. **Lazily materialize the DuckDB schema** — if the release's schema isn't
   already in the shared catalog file (`~/.cache/otai/catalog.duckdb`, one
   schema namespace per release), `schema_builder.build_release_schema()`
   creates it: `CREATE SCHEMA "<release>"` + one `CREATE VIEW` per dataset
   over `read_parquet(<base_uri>/<release>/output/<glob>)`.
4. **Execute** (only for `run-sql`) — `sql_guard.run_guarded_query()`
   validates, runs, caps, and envelopes the query; `commands.run_sql` sets
   `search_path` to `latest` first, so unqualified table names resolve
   there, then separately walks the query for schema-qualified references
   (e.g. `"26.03".target`) via `sql_guard.extract_schema_qualifiers()` and
   runs steps 1–3 again for each one, before execution — that's what makes
   cross-release joins work in a single `run-sql` call.

### Module map

- `cli.py` — Typer app; thin per-command wiring (JSON envelope vs.
  `--format table`, error emission). No logic of its own.
- `commands.py` — one function per subcommand, decoupled from Typer so
  they're unit-testable directly; owns the shared release-resolution flow
  above.
- `releases.py` / `croissant.py` — S3 listing and Croissant parsing. Every
  network-touching function takes an **injectable fetch callable**
  (defaults to a real `urlopen` call) so tests never hit the network. Both
  share `json_cache.py` for their on-disk cache file I/O (tolerant reads
  that treat a corrupt file as a miss, atomic writes via temp-file+rename).
- `schema_builder.py` — DuckDB schema/view construction; takes an
  injectable `base_uri` (defaults to the real S3 bucket) so tests point it
  at local fixture parquet files via `file://` instead. Shows a `tqdm`
  progress bar while building (a full release build measured ~18s for 55
  datasets) and logs via `loguru` — both on stderr, never stdout.
- `sql_guard.py` — the `run-sql` guardrails, deliberately decoupled from
  release resolution so they're tested against a synthetic in-memory
  DuckDB, independent of Open Targets fixtures:
  - Read-only enforcement walks the **entire** `sqlglot` AST (not just the
    top-level statement), so a mutation nested inside a CTE or subquery is
    still rejected as `guardrail_violation`.
  - Table sources are allowlisted, not blocklisted: a plain table/view
    reference always parses as `exp.Table(this=exp.Identifier)`; anything
    else (`read_csv_auto(...)`, `read_parquet(...)`, etc.) is a
    table-valued function and gets rejected, so `run-sql` can't read
    arbitrary local/remote data outside the release catalog.
  - The query timeout is a real wall-clock cancellation: the query runs in
    a daemon thread, and past the deadline the main thread calls
    `conn.interrupt()` on the shared connection from outside — DuckDB has
    no built-in `statement_timeout`.
- `catalog.py` — the shared DuckDB catalog file. `connect_catalog()`
  (read-write) retries on lock contention rather than failing immediately;
  `try_connect_readonly()` lets a caller peek at already-built schemas
  without taking the write lock at all, since read-only connections
  coexist freely. `commands.py` uses the peek to skip the write connection
  entirely whenever everything needed is already cached, so concurrent
  `otai` calls (e.g. parallel Claude Code subagents) against a warm cache
  don't fight over the lock.
- `logging_setup.py` — the one place that configures `loguru`'s sink
  (stderr, level from `OTAI_LOG_LEVEL`); library modules just import
  `logger` and log directly. Called once from `cli.py`'s root callback.
- `config.py` / `envelope.py` / `formatting.py` — small, single-purpose:
  cache-dir/base-uri/log-level resolution (overridable via
  `OTAI_CACHE_DIR`/`OTAI_BASE_URI`/`OTAI_LOG_LEVEL` env vars), the
  `{"ok": ...}` envelope shape, and `--format table` rendering.

### Testing strategy

Fully offline (PRD §10) — no real network calls anywhere in the suite:

- HTTP calls (croissant fetch, S3 listing) are mocked via the injectable
  `fetch`/`fetch_xml` parameters described above.
- Parquet/DuckDB behavior is tested against **real** `read_parquet()` over
  tiny fixture files (`tests/conftest.py`'s `fixture_release_layout` /
  `fixture_two_release_layout`, built with DuckDB's own `COPY ... TO
  '...parquet'`), not mocked — only the S3 URL is swapped for a `file://` one.
  `fixture_two_release_layout` exists specifically to exercise cross-release
  joins against two distinct, self-consistent release schemas.
- Guardrail logic (`sql_guard.py`) is tested against a synthetic in-memory
  DuckDB table, independent of any croissant/parquet fixtures.

### Error vocabulary

`error.type` values a caller (including the Skill) needs to branch on:
`guardrail_violation`, `sql_error`, `timeout`, `release_not_found`,
`dataset_not_found`, `s3_error`, `catalog_error`, `croissant_error` — see
the table in `.claude/skills/otai/SKILL.md` for what each means and how to
react.
