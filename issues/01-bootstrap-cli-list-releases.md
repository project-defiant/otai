# 01 - Bootstrap: CLI skeleton + `list-releases`

## Type

AFK

## What to build

Scaffold the `otai` Python project (uv + typer) and implement the first end-to-end vertical slice: `otai list-releases`.

This slice establishes the foundations every later command builds on:
- Project layout, `pyproject.toml`, `uv` dependency management, `typer` CLI entrypoint.
- DuckDB shared catalog file: locate at its predefined path (e.g. `~/.cache/otai/catalog.duckdb`), attach if it exists, create if not.
- S3 bucket listing (anonymous/unsigned access) to enumerate available releases, with "latest" resolved as lexically max.
- Local cache of the "latest release" resolution with a 24h TTL (no explicit refresh command; re-checked automatically once expired).
- Consistent JSON envelope for all commands: `{"ok": true, "data": {...}}` success / `{"ok": false, "error": {"type": ..., "message": ...}}` failure.
- `--format table` rendering as an alternative to the JSON envelope.
- Offline test harness: HTTP/S3 calls mocked with standard Python mocking tools — no real network calls in tests.

## Acceptance criteria

- [ ] `uvx --from <repo-path> otai list-releases` lists releases from the S3 bucket, flagging which is `latest` and which are already cached locally in the DuckDB catalog file.
- [ ] `otai list-releases` has no `--release` flag.
- [ ] Every command's output conforms to the JSON envelope shape; `--format table` produces a human-readable table instead.
- [ ] The shared DuckDB catalog file is created on first run at its predefined path and reused on subsequent runs.
- [ ] "Latest release" resolution is cached with a 24h TTL and re-fetched automatically once expired.
- [ ] All tests run fully offline (S3 listing mocked); no real network calls.

## Blocked by

None - can start immediately.
