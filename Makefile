.DEFAULT_GOAL := help
SHELL := /bin/bash

# this is old local setup
# Load .env if present
#ifneq (,$(wildcard ./.env))
#    include .env
#    export
#endif

# Load env file — defaults to .env, override with ENV_FILE=.env.aws
ENV_FILE ?= .env
ifneq (,$(wildcard ./$(ENV_FILE)))
    include $(ENV_FILE)
    export
endif

.PHONY: help
help:  ## Show this help
	@echo ""
	@echo "  Academic RAG — available commands"
	@echo "  Current env file: $(ENV_FILE)"
	@echo "  Override: make dev ENV_FILE=.env.aws"
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
up:
	docker compose up -d
	lstk start --persist 2>/dev/null || lstk restart --persist
	@echo ""
	@echo "⏳ Waiting for services..."
	@sleep 3
	@curl -sf http://localhost:4566/_localstack/health > /dev/null && echo "✅ localstack up" || echo "⚠️  localstack down (migrations still work)"
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
dev:  ## Run API + worker + UI (Ctrl+C stops all)
	@echo "🚀 Starting API (:$(API_PORT)) + UI (:$(UI_PORT))"
	@if [ "$(SKIP_WORKER)" = "1" ]; then \
		echo "   ⏭️  Worker skipped (SKIP_WORKER=1) — ECS handles ingestion"; \
	else \
		echo "   ▶️  Worker included — local worker polls SQS"; \
	fi
	@trap 'kill 0' EXIT INT TERM; \
		uv run uvicorn academic_ai.main:app --host $(API_HOST) --port $(API_PORT) --reload & \
		if [ "$(SKIP_WORKER)" != "1" ]; then \
			uv run python -m academic_ai.ingestion & \
		fi; \
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

AWS_ACCOUNT := 405101250590
AWS_REGION  := us-east-1
ECR_REPO    := $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com/academic-rag-worker

.PHONY: ecr-login
ecr-login:  ## Login to ECR
	aws ecr get-login-password --profile terraform-ai --region $(AWS_REGION) | \
	docker login --username AWS --password-stdin $(AWS_ACCOUNT).dkr.ecr.$(AWS_REGION).amazonaws.com

.PHONY: build-image
build-image:  ## Build worker image
	docker build --platform linux/amd64 -t academic-rag-worker:latest .

.PHONY: push-image
push-image: ecr-login build-image  ## Push worker image to ECR
	docker tag academic-rag-worker:latest $(ECR_REPO):latest
	docker push $(ECR_REPO):latest
.PHONY: evals
evals:  ## Run full eval suite (runner + scorer + compare)
	uv run python -m tests.evals.runner
	uv run python -m tests.evals.ragas_scorer
	uv run python -m tests.evals.compare

.PHONY: eval-baseline
eval-baseline:  ## Update reference baseline to current scores
	cp tests/evals/baseline.json tests/evals/baseline.reference.json
	@echo "✅ Reference baseline updated"
