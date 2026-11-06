from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_port: int = 5432
    database_url: str

    # --- Redis queue ---
    redis_host: str = "localhost"
    redis_port: int = 6379

    # --- AWS ---
    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("AWS_REGION", "AWS_DEFAULT_REGION"),
    )
    aws_profile: str | None = "bedrock"
    s3_bucket: str = "academic-docs-local"
    s3_endpoint_url: str | None = "http://localhost:4566"

    # --- Embeddings ---
    embedding_provider: str = "bedrock"          # "bedrock" | "openai"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: int = 1024

    # --- OpenAI (optional, only used if embedding_provider == "openai") ---
    openai_api_key: str | None = None
    openai_model: str | None = None

    # --- Chunking ---
    chunk_size_tokens: int = 600
    chunk_overlap_tokens: int = 100

    # --- Ingestion ---
    ingestion_visibility_ms: int = 300_000
    ingestion_max_retries: int = 5

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()