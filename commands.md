**  Generate and Apply Migrations
uv run alembic init -t async alembic
# Configure alembic/env.py to import Base.metadata and read DATABASE_URL
uv run alembic revision --autogenerate -m "init_academic_schema_jsonb_pgvector"
uv run alembic upgrade head
