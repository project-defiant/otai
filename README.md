# otai — Open Targets Agentic Query Tool

A CLI, paired with a Claude Code Skill, that lets Claude (or you) answer
natural-language questions about Open Targets Platform release data by
generating and executing SQL against the platform's parquet files hosted on
a public S3 bucket. No local data materialization, no hosted service —
phase 1 runs entirely inside a local Claude Code session or a terminal.

See [PRD.md](PRD.md) for the full design (architecture, guardrails, caching,
testing strategy) and [issues/](issues/) for how phase 1 was broken into
vertical slices.

## Requirements

- [uv](https://docs.astral.sh/uv/)
- git

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
