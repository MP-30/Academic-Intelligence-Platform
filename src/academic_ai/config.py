from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database (existing) ---
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_port: int = 5432
    database_url: str

    # --- Redis queue ---
    redis_host: str = "localhost"
    redis_port: int = 6379

    # --- AWS / S3 ---
    aws_region: str = "ap-south-1"
    s3_bucket: str = "academic-docs-local"
    s3_endpoint_url: str | None = "http://localhost:4566"

    # --- Embeddings (Titan v2) ---
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: int = 1024

    # --- Chunking ---
    chunk_size_tokens: int = 600
    chunk_overlap_tokens: int = 100

    # --- Ingestion queue tunables ---
    ingestion_visibility_ms: int = 300_000
    ingestion_max_retries: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()