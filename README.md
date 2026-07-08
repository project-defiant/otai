# otai — Open Targets Agentic Query Tool

A CLI, paired with a Claude Code Skill, that lets Claude (or you) answer
natural-language questions about Open Targets Platform release data by
generating and executing SQL against the platform's parquet files hosted on
a public S3 bucket. No local data materialization, no hosted service —
phase 1 runs entirely inside a local Claude Code session or a terminal.

See [PRD.md](PRD.md) for the full design (architecture, guardrails, caching,
testing strategy) and [issues/](issues/) for the vertical slices phase 1 was
broken into, plus follow-on issues filed since.

## How it works

```
Claude Code session
   └─ Skill (.claude/skills/otai/SKILL.md)
        └─ invokes: uvx --from <repo-path> otai <subcommand> [args] [--format table]
             └─ otai CLI (Python, Typer)
                  └─ DuckDB (httpfs, anonymous S3 access)
                       └─ s3://open-targets-public-data-releases/platform/<release>/output/*.parquet
```

`otai` never downloads or materializes Open Targets data locally — every
query reads live parquet files over S3 through DuckDB's `read_parquet()`.
The first time a release is touched, `otai` fetches that release's
[Croissant](http://mlcommons.org/croissant/1.0) schema descriptor, caches
it forever (release data is immutable), and lazily builds one DuckDB view
per dataset; a small shared DuckDB file (`~/.cache/otai/catalog.duckdb`)
tracks which releases have already been built, with one schema namespace
per release so cross-release joins work in a single query.

The four commands:

- `list-releases` — what releases exist on S3, which is `latest`, which are cached locally.
- `list-datasets [--release X]` — the datasets (tables) available in a release.
- `describe-dataset <name> [--release X]` — a dataset's columns, types, and relationships.
- `run-sql "<query>"` — read-only SQL against the views, guarded by `sqlglot`-based
  validation: rejects anything but a single `SELECT`/`WITH` (including mutations
  nested in a CTE or subquery) and rejects table-valued functions like
  `read_csv_auto`/`read_parquet` as a data source (only plain, optionally
  schema-qualified table/view names are allowed — `run-sql` can only query the
  release catalog, never arbitrary local/remote files), plus a ~1000-row cap
  and a ~45s timeout. A proactive `EXPLAIN`-based complexity check is scoped
  but not yet implemented (see [issues/07](issues/07-query-complexity-guard.md)).

Every command emits a JSON envelope (`{"ok": true, "data": {...}}` /
`{"ok": false, "error": {"type": "...", "message": "..."}}`) by default, or
a human-readable table with `--format table`.

Building a release's schema for the first time can take a while (each
dataset resolves a glob against real S3) — a progress bar and log messages
report on that, always on stderr so they never interfere with the JSON on
stdout. Set `OTAI_LOG_LEVEL` (default `INFO`) to `DEBUG` for more detail or
`WARNING` to quiet it down.

## Requirements

- [uv](https://docs.astral.sh/uv/) — runs the CLI (`uvx`) and manages the
  Python environment; every other Python dependency, including `duckdb`
  itself, is declared in `pyproject.toml` and installed automatically the
  first time you run `uvx`/`uv sync` — there's nothing to install by hand.
- git — `otai` isn't published to PyPI, so getting the source onto disk
  means cloning this repo. It's also what `make dev`'s pre-commit hook
  installs into (`.git/hooks/pre-commit`) and what the
  [contribution workflow](CONTRIBUTING.md) runs on. Once you have the
  files, though, running the CLI itself doesn't touch git at all — `uvx
  --from <path> otai ...` works the same from a plain directory as from a
  git checkout.

## Setting up with Claude Code

The Skill lives at `.claude/skills/otai/SKILL.md`, checked into this repo,
and ships and versions together with the CLI. Claude Code auto-discovers
skills under a project's `.claude/skills/` directory, so:

- **Working directly in this repo**: open it as your Claude Code project
  (or a parent directory containing it) and the `otai` Skill is available
  immediately — no extra setup.
- **Using it from another project**: copy (or symlink)
  `.claude/skills/otai/` into that project's own `.claude/skills/`
  directory, and update the `<repo-path>` in the Skill's invocation
  examples to wherever you cloned `otai`.

Either way, there's no global install: every invocation runs `uvx --from
<repo-path> otai ...`, so a local code change to `otai` is picked up on
the very next call, with no reinstall step.

## Running

```sh
uvx --from . otai list-releases
uvx --from . otai list-datasets [--release 26.03]
uvx --from . otai describe-dataset target [--release 26.03]
uvx --from . otai run-sql "SELECT count(*) FROM target"
```

Add `--format table` to any command for human-readable output; the default
is a JSON envelope (`{"ok": true, "data": {...}}` / `{"ok": false, "error":
{...}}`).

From Claude Code, the [`otai` Skill](.claude/skills/otai/SKILL.md) drives
these same commands automatically when you ask a question about Open
Targets data.

## Development

| Make Target  | Description                                    |
| ------------ | ----------------------------------------------- |
| `make dev`   | Install dev dependencies and the pre-commit hook. |
| `make lint`  | Run `ruff` (lint + format check) and `ty`.      |
| `make test`  | Run `pytest`.                                   |
| `make clean` | Remove build/test artifacts.                    |

### Workflow

Work happens on feature branches; open a PR against `main` and let CI
(lint + type-check + tests) pass before merging. See
[CONTRIBUTING.md](CONTRIBUTING.md) for details.
