from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from academic_ai.api.schemas import SearchRequest, SearchResponse
from academic_ai.auth.dependencies import get_current_user
from academic_ai.db.session import get_db
from academic_ai.ingestion.embeddings import embed
from academic_ai.retrieval.hybrid_search import hybrid_search

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def search(
    req: SearchRequest,
    user_id=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):

    rows = await hybrid_search(
        db,
        user_id=user_id,
        workspace_id=req.workspace_id,
        query_text=req.query,
        query_embedding=embed(req.query),
        top_k=req.top_k,
    )
    return SearchResponse(query=req.query, hits=rows, count=len(rows))