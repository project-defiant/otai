# Contributing

## Setup

```sh
make dev
```

Installs dev dependencies for the project and registers the `prek`
pre-commit hook (ruff + ty run automatically on `git commit`).

## Workflow

1. Branch off `main`.
2. Make your change, with tests (see [PRD.md §10](PRD.md) for the testing
   strategy — fully offline, no real network calls).
3. `make lint && make test` locally before pushing.
4. Open a PR against `main`. The `Check` CI workflow runs lint, type-check,
   and the test suite; it must pass before merging.
5. `main` is protected — merges happen through a reviewed, green PR, not
   direct pushes.

## Local checks

| Command      | What it does                              |
| ------------ | ------------------------------------------ |
| `make lint`  | `ruff check`, `ruff format --check`, `ty check` |
| `make test`  | `pytest`                                    |
| `make clean` | Remove `.venv`, caches, and build artifacts |
