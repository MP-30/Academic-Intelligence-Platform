"""Pytest fixtures for the RAG test suite."""
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from academic_ai.config import settings


@pytest.fixture(scope="session")
def sync_engine():
    """Sync engine (psycopg) — simpler for tests than async."""
    sync_url = settings.database_url.replace("+asyncpg", "+psycopg")
    return create_engine(sync_url, pool_pre_ping=True)


@pytest.fixture
def db(sync_engine):
    """Per-test DB session. Rolls back after each test."""
    Session = sessionmaker(bind=sync_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def seed_chunks(db):
    """
    Seed a real user + workspace + document + 3 chunks.
    Returns dict with ids so tests can reference them.
    """
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    db.execute(text("""
        INSERT INTO documents
          (id, user_id, workspace_id, filename, s3_key, doc_type,
           processing_status, vector_store_location, page_count)
        VALUES
          (:id, :u, :w, 'test.pdf', 'test/key.pdf', 'syllabus',
           'READY', 'PGVECTOR', 3)
    """), {"id": doc_id, "u": user_id, "w": workspace_id})

    # Small hand-rolled unit vector (1024-dim) — avoids a Bedrock call in unit tests
    dummy_vec = "[" + ",".join(["0.03125"] * 1024) + "]"  # unit-ish

    for idx in range(3):
        db.execute(text("""
            INSERT INTO document_chunks
              (id, document_id, user_id, workspace_id, page_number, chunk_index,
               content, embedding, metadata)
            VALUES
              (:id, :doc, :u, :w, :p, :ci, :content,
               CAST(:emb AS vector), CAST('{}' AS jsonb))
        """), {
            "id": uuid.uuid4(),
            "doc": doc_id, "u": user_id, "w": workspace_id,
            "p": idx + 1, "ci": idx,
            "content": f"elective test content {idx}",
            "emb": dummy_vec,
        })

    db.commit()

    yield {
        "user_id": user_id,
        "workspace_id": workspace_id,
        "document_id": doc_id,
        "chunk_count": 3,
    }

    # Cleanup — cascade deletes chunks
    db.execute(text("DELETE FROM documents WHERE id = :id"), {"id": doc_id})
    db.commit()