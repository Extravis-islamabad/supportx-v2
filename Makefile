# SupportX v2 task runner. `make check` must be green before any task is reported done (CLAUDE.md).
.DEFAULT_GOAL := help
.PHONY: help setup lint typecheck test format check build \
	backend-lint backend-typecheck backend-test frontend-lint frontend-typecheck frontend-test

BACKEND := cd backend &&
FRONTEND := cd frontend &&

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'

setup: ## Install backend (uv, Python 3.12) and frontend (pnpm) deps, install git hooks
	$(BACKEND) uv sync
	$(FRONTEND) pnpm install --frozen-lockfile
	uv run --project backend pre-commit install

lint: backend-lint frontend-lint ## Lint everything (ruff, import-linter, ESLint, Prettier check)

typecheck: backend-typecheck frontend-typecheck ## Type-check everything (mypy strict, tsc strict)

test: backend-test frontend-test ## Run all tests (pytest, Vitest)

check: lint typecheck test ## lint + typecheck + test for everything

format: ## Auto-format and auto-fix everything
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .
	$(FRONTEND) pnpm format

build: ## Production builds of the console and portal
	$(FRONTEND) pnpm build

backend-lint:
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run lint-imports

backend-typecheck:
	$(BACKEND) uv run mypy

backend-test:
	$(BACKEND) uv run pytest

frontend-lint:
	$(FRONTEND) pnpm lint && pnpm format:check

frontend-typecheck:
	$(FRONTEND) pnpm typecheck

frontend-test:
	$(FRONTEND) pnpm test
