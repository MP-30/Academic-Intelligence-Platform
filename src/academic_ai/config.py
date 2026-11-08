from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    postgres_user: str
    postgres_password: str
    postgres_db: str
    postgres_port: int = 5432
    database_url: str

    # --- AWS ---
    aws_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices("AWS_REGION", "AWS_DEFAULT_REGION"),
    )
    aws_profile: str | None = None
    s3_bucket: str = "academic-docs-local"
    s3_endpoint_url: str | None = "http://localhost:4566"

    # --- SQS ---
    sqs_endpoint_url: str | None = "http://localhost:4566"
    sqs_queue_name: str = "ingestion-jobs"
    sqs_queue_url: str = ""
    sqs_dlq_url: str = ""

    # --- Embeddings ---
    embedding_provider: str = "bedrock"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    embedding_dimensions: int = 1024

    # --- LLM (Claude via Bedrock) ---
    llm_model_id: str = "mistral.mistral-large-3-675b-instruct"
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.1
    ask_top_k: int = 5

    # --- OpenAI fallback ---
    openai_api_key: str | None = None
    openai_model: str | None = None

    # --- Chunking ---
    chunk_size_tokens: int = 600
    chunk_overlap_tokens: int = 100

    # --- Ingestion ---
    ingestion_visibility_seconds: int = 300
    ingestion_max_retries: int = 5

    # --- UI / API ---
    api_base_url: str = "http://localhost:8000"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    ui_host: str = "0.0.0.0"
    ui_port: int = 7860

    cognito_user_pool_id: str = ""
    cognito_client_id: str = ""
    cognito_region: str = "us-east-1"

    # --- CORS ---
    cors_allowed_origin: str = "http://localhost:7860"

    # --- Agent (v0.4) ---
    strands_model_id: str = "mistral.mistral-large-3-675b-instruct"
    agent_max_iterations: int = 8
    agent_temperature: float = 0.1
    tavily_api_key: str = ""
    agent_top_k: int = 5

    # --- MCP servers (v0.5) ---
    doc_mcp_url: str = "http://localhost:8001/mcp"
    web_mcp_url: str = "http://localhost:8002/mcp"
    doc_mcp_port: int = 8001
    web_mcp_port: int = 8002

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


settings = Settings()


