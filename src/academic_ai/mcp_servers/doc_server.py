"""MCP server — document search over user's uploaded PDFs.

Run: python -m academic_ai.mcp_servers.doc_server
Listens on http://0.0.0.0:8001/mcp (streamable HTTP transport).

Auth headers on each request:
    X-User-Id: <uuid>        (required)
    X-Workspace-Id: <uuid>   (optional)
"""
import asyncio
import logging
from uuid import UUID

from mcp.server import MCPServer
from mcp.server.mcpserver import Context

from academic_ai.config import settings
from academic_ai.db.session import SessionLocal
from academic_ai.ingestion.embeddings import embed
from academic_ai.retrieval.hybrid_search import hybrid_search

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

mcp = MCPServer("academic-doc-mcp")


def _user_context(ctx: Context | None) -> tuple[UUID | None, UUID | None]:
    """Extract X-User-Id / X-Workspace-Id from incoming HTTP headers.

    In v2, MCPServer tools read headers from `ctx.headers` (a mapping).
    """
    if ctx is None or not getattr(ctx, "headers", None):
        log.warning("no ctx.headers available")
        return None, None

    h = ctx.headers
    # HTTP headers are case-insensitive; try both common forms
    user_id_str = h.get("x-user-id") or h.get("X-User-Id")
    workspace_id_str = h.get("x-workspace-id") or h.get("X-Workspace-Id")

    if not user_id_str:
        log.warning("missing X-User-Id header")
        return None, None

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        log.warning("invalid X-User-Id: %s", user_id_str)
        return None, None

    workspace_id = None
    if workspace_id_str:
        try:
            workspace_id = UUID(workspace_id_str)
        except ValueError:
            log.warning("invalid X-Workspace-Id: %s", workspace_id_str)

    return user_id, workspace_id


async def _do_search(user_id: UUID, workspace_id: UUID | None, query: str, top_k: int) -> list[dict]:
    async with SessionLocal() as db:
        return await hybrid_search(
            db,
            user_id=user_id,
            workspace_id=workspace_id,
            query_text=query,
            query_embedding=embed(query),
            top_k=top_k,
        )


@mcp.tool()
def search_course_documents(
    query: str,
    top_k: int = 5,
    ctx: Context | None = None,
) -> list[dict]:
    """Search the user's uploaded course documents (syllabi, lecture notes, papers).

    Use this for questions about the user's specific uploaded content —
    course structure, syllabus details, assessment schemes, elective
    requirements, or anything present in their private PDFs.

    Args:
        query: Natural-language search query
        top_k: Number of top chunks to return (default 5, max 20)

    Returns:
        List of chunks. Each chunk has: document_id, page_number, content, rrf_score.
        Always cite the page_number when using a chunk in an answer.
    """
    user_id, workspace_id = _user_context(ctx)
    if user_id is None:
        return [{"error": "authentication required: missing X-User-Id header"}]

    top_k = min(max(top_k, 1), 20)

    # v2 sync tools run on a worker thread (no running loop), so asyncio.run works
    rows = asyncio.run(_do_search(user_id, workspace_id, query, top_k))

    log.info(
        "search_course_documents: user=%s ws=%s query=%r -> %d hits",
        user_id, workspace_id, query, len(rows),
    )
    return [
        {
            "document_id": str(r["document_id"]),
            "page_number": int(r["page_number"]),
            "content": r["content"],
            "rrf_score": float(r["rrf_score"]),
        }
        for r in rows
    ]


if __name__ == "__main__":
    log.info("Starting doc-mcp on port %d", settings.doc_mcp_port)
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=settings.doc_mcp_port,
    )
