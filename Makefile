# SupportX v2 task runner. `make check` must be green before any task is reported done (CLAUDE.md).
.DEFAULT_GOAL := help
.PHONY: help setup lint typecheck test format check build \
	dev-init dev-up dev-up-full dev-down dev-ps dev-logs dev-check dev-reset \
	backend-lint backend-typecheck backend-test frontend-lint frontend-typecheck frontend-test

BACKEND := cd backend &&
FRONTEND := cd frontend &&
# Local dev stack (WP-002, docs/dev-setup.md). `--profile full` on down/ps/logs so they cover every
# service whichever profile started it; it never starts anything by itself.
DEV_DIR := deploy/compose
COMPOSE := docker compose --project-directory $(DEV_DIR) -f $(DEV_DIR)/docker-compose.yml
DEV_ENV := $(DEV_DIR)/.env

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

# --- Local dev stack -----------------------------------------------------------------------------

$(DEV_ENV):
	@echo "deploy/compose/.env is missing; run 'make dev-init' first." && exit 1

dev-init: ## Create deploy/compose/.env with random dev secrets (never overwrites it)
	@bash $(DEV_DIR)/scripts/dev-init.sh

dev-up: $(DEV_ENV) ## Start the core dev services and wait until healthy
	$(COMPOSE) up -d --wait --wait-timeout 300
	$(COMPOSE) run --rm minio-init

dev-up-full: $(DEV_ENV) ## Start core + full (Temporal, OpenSearch, ClickHouse, ClamAV)
	$(COMPOSE) --profile full up -d --wait --wait-timeout 900
	$(COMPOSE) run --rm minio-init

dev-down: $(DEV_ENV) ## Stop all dev services; data volumes are KEPT
	$(COMPOSE) --profile full --profile setup down --remove-orphans

dev-ps: $(DEV_ENV) ## Show dev services and their health
	$(COMPOSE) --profile full ps --all

dev-logs: $(DEV_ENV) ## Follow logs (one service: make dev-logs s=postgres)
	$(COMPOSE) --profile full logs -f --tail=100 $(s)

dev-check: $(DEV_ENV) ## Verify every running dev service really works (PASS/FAIL table)
	@bash $(DEV_DIR)/scripts/dev-check.sh

dev-reset: $(DEV_ENV) ## DELETE all dev data volumes (asks you to type "yes" first)
	@bash $(DEV_DIR)/scripts/dev-reset.sh
