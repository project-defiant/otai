# 03 - Schema introspection: `describe-dataset`

## Type

AFK

## What to build

Extend the croissant parser built in #2 to expose full field-level detail, and implement `otai describe-dataset <name> [--release X]`.

- Parse each dataset's `field` list: name, description, `dataType`.
- Parse `references` on fields that point to another dataset's field (cross-dataset relationships).
- Parse `subField`s for nested/repeated struct columns.
- Field descriptions and relationships are read directly from the cached croissant.json on demand — never stored in DuckDB (no `COMMENT ON`).
- `otai describe-dataset <name> [--release X]` (default `latest`) returns the full field list for one dataset: column names, types, descriptions, and cross-dataset relationships.

## Acceptance criteria

- [ ] `otai describe-dataset <name>` returns every field's name, type, and description for the given dataset in the default (`latest`) release.
- [ ] Cross-dataset `references` are included in the output where present.
- [ ] Nested/repeated struct columns' `subField`s are included in the output where present.
- [ ] `--release X` selects a single explicit release; no multi-release support.
- [ ] Relationship/description data is sourced only from the cached croissant.json, not from DuckDB metadata.
- [ ] Tests cover a fixture croissant.json with at least one cross-dataset reference and one nested subField.

## Blocked by

- Blocked by #2
