"""Strands tools — document search across the user's uploaded PDFs."""
import logging
from contextvars import ContextVar
from uuid import UUID

from strands import tool

from academic_ai.db.session import SessionLocal
from academic_ai.ingestion.embeddings import embed
from academic_ai.retrieval.hybrid_search import hybrid_search

log = logging.getLogger(__name__)

# Bound per request in the API endpoint — the LLM never sees or provides these
current_user_id_ctx: ContextVar[UUID | None] = ContextVar(
    "current_user_id", default=None
)
current_workspace_id_ctx: ContextVar[UUID | None] = ContextVar(
    "current_workspace_id", default=None
)


@tool
def search_course_documents(query: str, top_k: int = 5) -> list[dict]:
    """Search the user's uploaded course documents (syllabi, lecture notes, papers).

    Use this for questions about the user's specific uploaded content —
    course structure, syllabus details, assessment schemes, elective
    requirements, or anything present in their private PDFs.

    Args:
        query: Natural-language search query
        top_k: Number of top chunks to return (default 5)

    Returns:
        List of chunks with fields: page_number, document_id, content, rrf_score.
        Each chunk is from a specific PDF page — always cite the page number.
    """
    user_id = current_user_id_ctx.get()
    workspace_id = current_workspace_id_ctx.get()

    if user_id is None:
        log.warning("search_course_documents called without user_id in context")
        return [{"error": "user context not available"}]

    async def _search():
        async with SessionLocal() as db:
            return await hybrid_search(
                db,
                user_id=user_id,
                workspace_id=workspace_id,
                query_text=query,
                query_embedding=embed(query),
                top_k=top_k,
            )

    # Bridge async DB session into sync tool call (Strands invokes sync tools)
    import asyncio
    try:
        rows = asyncio.run(_search())
    except RuntimeError:
        # Already inside an event loop (ECS/API context) — use new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            rows = pool.submit(lambda: asyncio.run(_search())).result()

    log.info("search_course_documents: query=%r -> %d hits", query, len(rows))

    return [
        {
            "document_id":  str(r["document_id"]),
            "page_number":  int(r["page_number"]),
            "content":      r["content"],
            "rrf_score":    float(r["rrf_score"]),
        }
        for r in rows
    ]
