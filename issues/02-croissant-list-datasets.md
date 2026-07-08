# 02 - Dataset catalog: croissant fetch/cache + `list-datasets`

## Type

AFK

## What to build

Implement the implicit initialization pipeline for a single release and the `otai list-datasets` command.

- Fetch a release's `croissant.json` descriptor from `s3://open-targets-public-data-releases/platform/<release>/croissant.json` and cache it locally at `~/.cache/otai/<release>/croissant.json`. Never re-fetch once cached (release data is immutable).
- Parse the croissant descriptor's `recordSet` entries (dataset name, one-line description, `fileSet` glob).
- For a release not yet present in the DuckDB catalog: `CREATE SCHEMA "<release>"`, then for each dataset `CREATE VIEW "<release>".<dataset> AS SELECT * FROM read_parquet('s3://.../<dataset>/*.parquet')`.
- Wire this into `otai list-datasets [--release X]` (default `latest`), returning dataset names + one-line descriptions in the JSON envelope / table format.
- Schema-builder takes an injectable base URI (defaults to the real S3 bucket in production) so tests can point it at a local directory of small fixture parquet files (`file://` paths) and exercise DuckDB's real `read_parquet()` against them.

## Acceptance criteria

- [ ] First call to `list-datasets` for a release fetches and caches croissant.json; subsequent calls reuse the cached file with no re-fetch.
- [ ] The release's DuckDB schema and per-dataset views are created lazily on first use and reused on subsequent calls (schema-exists check before rebuilding).
- [ ] `otai list-datasets` defaults to `latest` when `--release` is omitted, and accepts a single explicit release.
- [ ] `otai list-datasets` has no multi-release support (single `--release` value only).
- [ ] Tests run against local fixture parquet files via an injectable base URI — no real S3 or mock-S3-server involved.
- [ ] Croissant fetch is mocked in tests (no real network calls).

## Blocked by

- Blocked by #1
