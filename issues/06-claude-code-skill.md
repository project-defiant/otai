# 06 - Claude Code Skill: `.claude/skills/otai/SKILL.md`

## Type

AFK

## What to build

Author the in-repo Skill that lets Claude use the `otai` CLI correctly, as a thin instruction layer with no independent logic.

- Lives at `.claude/skills/otai/SKILL.md`, ships and versions together with the CLI.
- Documents how to invoke the CLI: `uvx --from <repo-path> otai <subcommand> [args] [--format table]`.
- Encodes the behavioral rules from PRD §8:
  1. Call `list-datasets` before writing SQL when unsure which dataset(s) are relevant — never guess a table/schema name.
  2. Always `describe-dataset` on a table before joining, since ids and relationships aren't guessable from names alone.
  3. Always include a `LIMIT` in exploratory/preview queries unless the question needs a full aggregate.
  4. Schema-qualify table names explicitly when a question concerns a non-latest release (e.g. `"26.03".target`) or spans multiple releases; leave unqualified for latest.
  5. On a `run-sql` error, branch on `error.type`: `timeout` → narrow the query and retry; `sql_error`/`guardrail_violation` → fix the SQL; `release_not_found` → check `list-releases` before retrying.
  6. Cite the release(s) queried and the actual SQL executed in the final answer to the user.

## Acceptance criteria

- [ ] `SKILL.md` exists at `.claude/skills/otai/SKILL.md` and describes all four subcommands (`list-releases`, `list-datasets`, `describe-dataset`, `run-sql`) and their flags.
- [ ] All 6 behavioral rules from PRD §8 are present and unambiguous.
- [ ] The Skill instructs Claude to invoke the CLI via `uvx --from <repo-path> otai ...` and carries no logic duplicating what the CLI already enforces (e.g. no re-implementing guardrails in the Skill text).
- [ ] Manually verified in a Claude Code session: given a natural-language question, Claude calls `list-datasets`/`describe-dataset` before writing SQL, includes a `LIMIT` in an exploratory query, and cites the release + SQL in its final answer.

## Blocked by

- Blocked by #1, #2, #3, #4, #5
