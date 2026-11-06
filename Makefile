.DEFAULT_GOAL := help
SHELL := /bin/bash

# Load .env if present
ifneq (,$(wildcard ./.env))
    include .env
    export
endif

.PHONY: help
help:  ## Show this help
	@echo ""
	@echo "  Academic RAG — available commands"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ─────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────

.PHONY: install
install:  ## Install deps + editable package
	uv sync
	uv pip install -e .

.PHONY: migrate
migrate:  ## Run alembic migrations
	uv run alembic upgrade head

.PHONY: migrate-new
migrate-new:  ## Generate a new migration (usage: make migrate-new MSG="add foo")
	@if [ -z "$(MSG)" ]; then echo "Usage: make migrate-new MSG=\"your message\""; exit 1; fi
	uv run alembic revision --autogenerate -m "$(MSG)"

# ─────────────────────────────────────────────────────────────────────
# Infrastructure
# ─────────────────────────────────────────────────────────────────────

.PHONY: up
up:  ## Start postgres (docker) + localstack (lstk)
	docker compose up -d
	lstk restart --persist
	@echo ""
	@echo "⏳ Waiting for services..."
	@sleep 3
	@curl -sf http://localhost:4566/_localstack/health > /dev/null && echo "✅ localstack up" || echo "❌ localstack down"
	@docker compose ps

.PHONY: down
down:  ## Stop all services
	docker compose down
	@echo "LocalStack is managed by lstk — run 'lstk stop' to shut it down too"

.PHONY: ps
ps:  ## Show running containers + localstack health
	@docker compose ps
	@echo ""
	@echo "LocalStack:"
	@curl -s http://localhost:4566/_localstack/health | python3 -m json.tool | head -8 || echo "  (down)"

.PHONY: logs
logs:  ## Tail docker container logs
	docker compose logs -f

# ─────────────────────────────────────────────────────────────────────
# Application (each in its own terminal)
# ─────────────────────────────────────────────────────────────────────

.PHONY: api
api:  ## Run FastAPI (foreground)
	uv run uvicorn academic_ai.main:app --host $(API_HOST) --port $(API_PORT) --reload

.PHONY: worker
worker:  ## Run SQS worker (foreground)
	uv run python -m academic_ai.ingestion

.PHONY: ui
ui:  ## Run Gradio UI (foreground)
	uv run python -m academic_ai.ui.app

.PHONY: dev
dev:  ## Run API + worker + UI all at once (Ctrl+C to stop all)
	@echo "🚀 Starting API (:$(API_PORT)) + Worker + UI (:$(UI_PORT))"
	@echo "   Press Ctrl+C to stop all three."
	@echo ""
	@trap 'kill 0' EXIT INT TERM; \
		uv run uvicorn academic_ai.main:app --host $(API_HOST) --port $(API_PORT) --reload & \
		uv run python -m academic_ai.ingestion & \
		uv run python -m academic_ai.ui.app & \
		wait

# ─────────────────────────────────────────────────────────────────────
# Quality
# ─────────────────────────────────────────────────────────────────────

.PHONY: test
test:  ## Run pytest
	uv run pytest -v

.PHONY: test-isolation
test-isolation:  ## Run just tenant isolation tests
	uv run pytest tests/test_tenant_isolation.py -v

.PHONY: lint
lint:  ## Run ruff check
	uv run ruff check .

.PHONY: format
format:  ## Run ruff format
	uv run ruff format .

.PHONY: check
check: lint test  ## Lint + test (CI equivalent)

# ─────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────

.PHONY: psql
psql:  ## Open psql shell
	docker exec -it academic_pgvector psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -P pager=off

.PHONY: psql-status
psql-status:  ## Quick status snapshot
	@docker exec -it academic_pgvector psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -P pager=off -c "\
		SELECT status, count(*) FROM ingestion_jobs GROUP BY status; \
		SELECT processing_status, count(*) FROM documents GROUP BY processing_status; \
		SELECT count(*) AS chunks FROM document_chunks;"

.PHONY: urls
urls:  ## Print useful URLs
	@echo ""
	@echo "  API docs   → http://localhost:$(API_PORT)/docs"
	@echo "  API health → http://localhost:$(API_PORT)/health"
	@echo "  Gradio UI  → http://localhost:$(UI_PORT)"
	@echo "  LocalStack → http://localhost:4566/_localstack/health"
	@echo ""

.PHONY: clean
clean:  ## Remove __pycache__ + .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache

.PHONY: reset-db
reset-db:  ## ⚠️ DROP all data and re-run migrations
	@read -p "This will DELETE all documents and chunks. Type 'yes' to continue: " confirm && \
	[ "$$confirm" = "yes" ] || (echo "Aborted."; exit 1)
	docker exec -it academic_pgvector psql -U $(POSTGRES_USER) -d $(POSTGRES_DB) -c "\
		TRUNCATE document_chunks, ingestion_jobs, documents RESTART IDENTITY CASCADE;"
	uv run alembic upgrade head