import uuid
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from academic_ai.api.dependencies import get_current_user
from academic_ai.api.schemas import DocumentStatusResponse, DocumentUploadResponse
from academic_ai.db.models import Document
from academic_ai.db.session import get_db
from academic_ai.ingestion.producer import enqueue_ingestion_job
from academic_ai.ingestion.s3_service import upload_pdf

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentUploadResponse, status_code=202)
async def upload_document(
    file: UploadFile = File(...),
    workspace_id: UUID = Form(...),
    user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a PDF, store in S3, enqueue an ingestion job."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are accepted")

    s3_key = f"{user_id}/{uuid.uuid4()}/{file.filename}"
    upload_pdf(s3_key, await file.read())

    doc = Document(
        user_id=user_id,
        workspace_id=workspace_id,
        filename=file.filename,
        s3_key=s3_key,
        doc_type="syllabus",
        processing_status="PENDING",
        vector_store_location="PGVECTOR",
        page_count=0,
    )
    db.add(doc)
    await db.flush()

    job_id = await enqueue_ingestion_job(
        db,
        document_id=doc.id,
        user_id=user_id,
        workspace_id=workspace_id,
        s3_key=s3_key,
    )

    return DocumentUploadResponse(document_id=doc.id, job_id=UUID(job_id))


@router.get("/{doc_id}", response_model=DocumentStatusResponse)
async def get_document(
    doc_id: UUID,
    user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll ingestion status."""
    doc = (await db.execute(
        select(Document).where(
            Document.id == doc_id,
            Document.user_id == user_id,
        )
    )).scalar_one_or_none()

    if not doc:
        raise HTTPException(404, "Document not found")

    job = (await db.execute(text("""
        SELECT status, last_error
        FROM ingestion_jobs
        WHERE document_id = :doc_id
        ORDER BY created_at DESC
        LIMIT 1
    """), {"doc_id": str(doc_id)})).mappings().first()

    return DocumentStatusResponse(
        document_id=doc.id,
        processing_status=doc.processing_status,
        page_count=doc.page_count,
        job_status=job["status"] if job else None,
        job_error=job["last_error"] if job else None,
    )