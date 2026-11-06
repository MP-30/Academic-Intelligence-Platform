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