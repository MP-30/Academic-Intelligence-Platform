from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    workspace_id: UUID | None = None
    top_k: int = Field(5, ge=1, le=20)


class SearchHit(BaseModel):
    chunk_id: UUID
    document_id: UUID
    page_number: int
    content: str
    rrf_score: float


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHit]
    count: int


class DocumentUploadResponse(BaseModel):
    document_id: UUID
    job_id: UUID


class DocumentStatusResponse(BaseModel):
    document_id: UUID
    processing_status: str
    page_count: int
    job_status: str | None = None
    job_error: str | None = None

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    workspace_id: UUID | None = None
    top_k: int | None = Field(None, ge=1, le=10)


class AskCitation(BaseModel):
    chunk_id: UUID
    document_id: UUID
    page_number: int
    content: str


class AskResponse(BaseModel):
    answer: str
    citations: list[AskCitation]
    chunks_used: int

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    id_token: str
    access_token: str
    refresh_token: str | None = None
    expires_in: int
    token_type: str


class AgentRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: UUID | None = None
    workspace_id: UUID | None = None


class AgentToolCall(BaseModel):
    tool: str
    args: dict


class AgentCitation(BaseModel):
    source: str  # "document" | "web"
    page_number: int | None = None
    document_id: str | None = None
    url: str | None = None
    title: str | None = None


class AgentResponse(BaseModel):
    conversation_id: UUID
    response: str
    tool_calls: list[AgentToolCall]
    citations: list[AgentCitation]