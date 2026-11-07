#!/bin/sh
set -e

MODE="${1:-worker}"

case "$MODE" in
  worker)
    echo "==> [worker] Enabling pgvector extensions..."
    uv run --frozen --no-dev python -c "
import psycopg
from academic_ai.config import settings
url = settings.database_url.replace('+psycopg', '')
with psycopg.connect(url, autocommit=True, connect_timeout=10) as conn:
    conn.execute('CREATE EXTENSION IF NOT EXISTS vector')
    conn.execute('CREATE EXTENSION IF NOT EXISTS pgcrypto')
    print('extensions OK')
"
    echo "==> [worker] Running migrations..."
    uv run --frozen --no-dev alembic upgrade head
    echo "==> [worker] Starting worker..."
    exec uv run --frozen --no-dev python -m academic_ai.ingestion
    ;;

  api)
    echo "==> [api] Starting uvicorn on 0.0.0.0:8000..."
    exec uv run --frozen --no-dev uvicorn academic_ai.main:app \
      --host 0.0.0.0 --port 8000 --workers 1
    ;;

  ui)
    echo "==> [ui] Starting Gradio on 0.0.0.0:7860..."
    exec uv run --frozen --no-dev python -m academic_ai.ui.app
    ;;

  *)
    echo "Unknown mode: $MODE"; exit 1 ;;
esac
