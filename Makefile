.PHONY: help dev lint test clean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "\033[36m%-9s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev: .git/hooks/pre-commit ## Install dev dependencies and pre-commit hook
	@uv sync --all-groups
	@echo "dev dependencies installed"

.git/hooks/pre-commit:
	@uv tool install prek --quiet
	@uvx prek install
	@echo "prek hook installed"

lint: ## Run ruff (lint + format check) and ty
	@uv run --frozen ruff check .
	@uv run --frozen ruff format --check .
	@uv run --frozen ty check
	@echo "lint completed"

test: ## Run pytest
	@uv run --frozen pytest
	@echo "tests completed"

clean: ## Remove build/test artifacts
	@rm -rf .venv .pytest_cache .ruff_cache *.egg-info
	@rm -rf .git/hooks/pre-commit
	@echo "cleaned"
