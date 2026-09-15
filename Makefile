# YuPay — Makefile is the single entrypoint for all common tasks.
# Prefer `make <target>` over invoking raw tools. New targets must also appear in AGENTS.md.

.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

COMPOSE_DEV  := docker compose -f docker-compose.yml
COMPOSE_PROD := docker compose -f docker-compose.prod.yml

# ---------- meta ----------

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nYuPay — make targets\n\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Setup

.PHONY: bootstrap
bootstrap: ## Install all deps (pnpm + uv) + pre-commit + gen api client
	corepack enable
	corepack prepare pnpm@9 --activate
	pnpm install --frozen-lockfile=false
	uv sync
	pnpm exec husky install || true
	pre-commit install || echo "pre-commit not on PATH; install with: uv tool install pre-commit"
	$(MAKE) gen-api || echo "gen-api skipped: api app not yet scaffolded"

##@ Development

.PHONY: dev
dev: ## Bring up the full dev stack
	$(COMPOSE_DEV) up --build

.PHONY: dev-detached
dev-detached: ## Bring up the dev stack in the background
	$(COMPOSE_DEV) up -d --build

.PHONY: dev-api
dev-api: ## Run only the API (host process; requires postgres+redis up)
	cd apps/api && uv run uvicorn yupay.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: dev-worker
dev-worker: ## Run only the worker
	cd apps/worker && uv run python -m yupay_worker.consumer

.PHONY: dev-web
dev-web: ## Run only the public web (host process)
	pnpm --filter @yupay/web dev

.PHONY: dev-miniapp
dev-miniapp: ## Run only the Telegram Mini App (host process)
	pnpm --filter @yupay/miniapp dev

.PHONY: down
down: ## Bring the dev stack down
	$(COMPOSE_DEV) down

.PHONY: logs
logs: ## Tail a service's logs: make logs service=api
	@if [ -z "$(service)" ]; then echo "Usage: make logs service=api"; exit 1; fi
	$(COMPOSE_DEV) logs -f $(service)

##@ Database

.PHONY: migrate
migrate: ## Apply all alembic migrations inside the api container
	$(COMPOSE_DEV) exec api alembic upgrade head

.PHONY: migration
migration: ## Create a new alembic migration: make migration name=add_orders
	@if [ -z "$(name)" ]; then echo "Usage: make migration name=add_x"; exit 1; fi
	$(COMPOSE_DEV) exec api alembic revision --autogenerate -m "$(name)"

.PHONY: psql
psql: ## Open a psql shell inside the postgres container
	$(COMPOSE_DEV) exec postgres psql -U yupay_app -d yupay

.PHONY: seed
seed: ## Seed dev data (idempotent: matches by slug / sku_code and updates in place)
	$(COMPOSE_DEV) exec api python -m yupay.scripts.seed_catalog

##@ Quality

.PHONY: lint
lint: lint-py lint-ts ## Lint everything

.PHONY: lint-py
lint-py: ## Ruff check + format check
	uv run ruff check apps
	uv run ruff format --check apps

.PHONY: lint-ts
lint-ts: ## ESLint + Prettier check
	pnpm exec turbo run lint
	pnpm exec prettier --check .

.PHONY: lint-fix
lint-fix: ## Autofix everything
	uv run ruff check --fix apps
	uv run ruff format apps
	pnpm exec turbo run lint:fix
	pnpm exec prettier --write .

.PHONY: typecheck
typecheck: ## mypy + tsc
	uv run mypy apps
	pnpm exec turbo run typecheck

##@ Testing

.PHONY: test
test: test-py test-ts ## All tests (Python + TS)

.PHONY: test-py
test-py: ## Python unit + integration tests
	COVERAGE_CORE=sysmon uv run pytest -n auto

.PHONY: test-ts
test-ts: ## TS tests across all packages and apps
	pnpm exec turbo run test

.PHONY: test-e2e
test-e2e: ## Playwright e2e tests (requires running stack)
	pnpm --filter @yupay/e2e exec playwright test

##@ Build / release

.PHONY: build
build: ## Build all Docker images locally
	$(COMPOSE_DEV) build

.PHONY: gen-api
gen-api: ## Regenerate docs/api/*.json + packages/api-client
	@if [ -d apps/api/src/yupay ]; then \
		cd apps/api && uv run python -m yupay.scripts.export_openapi ../../docs/api/openapi.json \
			&& uv run python -m yupay.scripts.export_merchant_openapi ../../docs/api/merchant-openapi.json \
			&& cd ../..; \
		pnpm --filter @yupay/api-client gen:api; \
	else \
		echo "apps/api not scaffolded yet"; \
	fi

.PHONY: deploy
deploy: ## Deploy via GitHub Actions: make deploy env=prod
	@if [ -z "$(env)" ]; then echo "Usage: make deploy env=prod"; exit 1; fi
	gh workflow run deploy.yml -f environment=$(env)

.PHONY: indexnow
indexnow: ## Ping Bing/Yandex (IndexNow) with the live sitemap URLs (run after deploy)
	node scripts/indexnow.mjs

##@ Ops

.PHONY: backup
backup: ## One-off pg_backup.sh run (the backup service itself runs nightly)
	$(COMPOSE_PROD) run --rm backup /bin/bash /scripts/pg_backup.sh

.PHONY: restore
restore: ## Restore DB from backup: make restore file=path
	@if [ -z "$(file)" ]; then echo "Usage: make restore file=/path/to/backup.dump"; exit 1; fi
	$(COMPOSE_PROD) run --rm -v $(file):/restore.dump backup /bin/bash /scripts/restore.sh /restore.dump
