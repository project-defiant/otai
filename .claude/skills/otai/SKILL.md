---
name: otai
description: Answer natural-language questions about Open Targets Platform data (targets, diseases, associations, evidence, drugs, etc.) by driving the `otai` CLI, which runs guarded read-only SQL against release parquet files on S3. Use whenever the user asks about Open Targets targets/diseases/drugs/evidence/associations, wants a specific Open Targets release explored or compared, or asks a question that requires querying Open Targets Platform data.
---

# otai — Open Targets Agentic Query Tool

`otai` is the engine: it owns the schema catalog, DuckDB views, and all
guardrails. This Skill is a thin instruction layer on top of it — it tells
you which subcommands exist, when to call them, and how to react to their
output. It carries no independent logic of its own: never re-derive or
re-enforce a guardrail (e.g. read-only checks, timeouts, row caps) yourself
in prose or in a query — the CLI already does that. Your job is to call the
CLI correctly and interpret what it returns.

## Invocation

```
uvx --from git+https://github.com/opentargets/otai.git otai <subcommand> [args] [--format table]
```

`<repo-path>` is the absolute path to the local `otai` checkout (this
repo). Every invocation picks up local code changes — no persistent
install. Omit `--format table` to get the default JSON envelope (preferred
for your own parsing); pass it only when showing a human-readable table
directly to the user.

## Subcommands

### `otai list-releases`
Lists releases available in the S3 bucket, flagging which is `latest` and
which are already cached locally. No arguments besides `--format`.

### `otai list-datasets [--release X]`
Lists all datasets (recordSets) for one release, each with a one-line
description. `--release` defaults to `latest`; single release only (no
comparing releases in one call).

### `otai describe-dataset <name> [--release X]`
Positional `<name>` (the dataset to describe) plus `--release` (default
`latest`). Returns the full field list for that dataset in that release:
column names, types, descriptions, and cross-dataset relationships/nested
subfields, parsed from the release's croissant schema.

### `otai run-sql "<query>"`
Positional `<query>`, a read-only SQL string. No `--release` flag:
- Unqualified table names resolve against `latest`.
- Schema-qualify a table to target a specific (possibly non-latest)
  release, e.g. `"26.03".target`; this also enables cross-release joins in
  a single query, e.g. `"26.06".target JOIN "26.03".target ...`.
- The CLI enforces read-only SQL, a ~1000-row cap (response says whether
  results were truncated), and a ~45s timeout — do not attempt to
  replicate or second-guess these checks yourself.

## JSON envelope

Every command emits one of:

```json
{"ok": true, "data": { ... }}
```
```json
{"ok": false, "error": {"type": "...", "message": "..."}}
```

`error.type` values you may see, and how to react:

| `error.type`           | Meaning                                             | What to do |
|------------------------|------------------------------------------------------|------------|
| `guardrail_violation`  | Query isn't a single read-only SELECT/WITH           | Fix the SQL (e.g. remove the mutating/DDL statement) and retry |
| `sql_error`            | SQL failed to parse, or failed at execution           | Fix the SQL syntax/logic and retry |
| `timeout`              | Query ran past the execution time limit               | Narrow the query (add filters/LIMIT, reduce scope) and retry |
| `release_not_found`    | A schema-qualified release in the query is unknown    | Run `list-releases` to see valid release identifiers, then retry with a correct qualifier |
| `dataset_not_found`    | `describe-dataset` name doesn't exist in that release | Run `list-datasets` for that release to find the correct name |
| `s3_error`             | Couldn't list/reach the S3 bucket                     | Report the failure to the user; retrying immediately is unlikely to help |
| `catalog_error`        | Local DuckDB catalog couldn't be opened/built          | Report the failure to the user |
| `croissant_error`      | A release's schema descriptor couldn't be fetched/parsed | Report the failure to the user |

## Behavioral rules

1. **Never guess a table/schema name.** If you're unsure which dataset(s)
   are relevant to the question, call `list-datasets` first.
2. **Always `describe-dataset` before joining.** Column names,
   relationships, and join keys aren't guessable from a dataset name alone
   — check the real field list first.
3. **Always include a `LIMIT`** in exploratory/preview queries, unless the
   question genuinely needs a full aggregate (e.g. `COUNT(*)`,
   `AVG(...)` over the whole table).
4. **Schema-qualify explicitly for non-latest or multi-release
   questions.** Use `"26.03".target` etc. when the question concerns a
   specific past release or spans more than one release; leave table names
   unqualified when the question is about the latest release.
5. **On a `run-sql` error, branch on `error.type`** per the table above —
   in short: `timeout` → narrow and retry; `sql_error` /
   `guardrail_violation` → fix the SQL; `release_not_found` → check
   `list-releases` before retrying.
6. **Cite your sources in the final answer**: state which release(s) were
   queried and show the actual SQL you executed, so the user can verify or
   rerun it.

## Example

Question: "How many approved drug targets does the human genome have,
according to Open Targets?"

1. `otai list-datasets` → confirms a `target` dataset exists (default,
   `latest` release).
2. `otai describe-dataset target` → confirms the dataset has an `id`
   column and how targets are defined; no join needed for this question.
3. `otai run-sql "SELECT count(*) FROM target"` — a full aggregate, so no
   `LIMIT` is needed (rule 3's exception).
4. Answer cites the release returned in the response's `data.release`
   field and the exact SQL run, e.g.: "Per Open Targets release 26.06,
   there are 78,691 targets in the platform (`SELECT count(*) FROM
   target`)."
