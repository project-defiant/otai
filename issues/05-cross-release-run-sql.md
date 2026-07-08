# 05 - Cross-release queries: schema-qualified lazy-init in `run-sql`

## Type

AFK

## What to build

Extend `run-sql`'s `sqlglot` pass to walk table references and support explicit schema-qualified access to any release, including joins across releases.

- Walk the parsed AST's table references to collect every schema qualifier used in the query (e.g. `"26.03".target` → release `26.03`).
- Validate that every extracted schema qualifier is a well-formed release identifier; unresolvable/unknown releases return `error.type: "release_not_found"`.
- For each schema qualifier found, trigger the same lazy-init pipeline from #2 (fetch croissant if needed, `CREATE SCHEMA`/`CREATE VIEW`s) if that release's schema doesn't already exist in the catalog.
- Unqualified table names continue to resolve only against `latest` (via `search_path`) — this list-of-qualifiers extraction is what identifies and validates non-default releases up front, rather than relying on `search_path` alone.
- This enables queries like joining `"26.06".target` against `"26.03".target` in a single `run-sql` call with no extra flag.

## Acceptance criteria

- [ ] A query referencing a schema-qualified table for a release not yet built (e.g. `"26.03".target`) triggers lazy-init of that release's schema before execution.
- [ ] A query joining two explicitly schema-qualified releases (e.g. `"26.06".target` and `"26.03".target`) executes successfully in one `run-sql` call.
- [ ] A schema qualifier that isn't a valid/known release returns `error.type: "release_not_found"`.
- [ ] Unqualified table names still resolve only against `latest`, even when the query also references other schema-qualified releases.
- [ ] Guardrails from #4 (read-only enforcement, row cap, timeout) still apply to cross-release queries.
- [ ] Tests cover: a query touching two releases, and a query referencing an invalid/unknown release qualifier.

## Blocked by

- Blocked by #4
