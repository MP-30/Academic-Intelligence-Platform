from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from academic_ai.api.dependencies import get_current_user
from academic_ai.api.schemas import AskRequest, AskResponse
from academic_ai.db.session import get_db
from academic_ai.retrieval.ask import ask

router = APIRouter(prefix="/ask", tags=["ask"])


@router.post("", response_model=AskResponse)
async def ask_endpoint(
    req: AskRequest,
    user_id=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """LLM-synthesized answer with page citations from the user's documents."""
    result = await ask(
        db,
        user_id=user_id,
        workspace_id=req.workspace_id,
        question=req.question,
        top_k=req.top_k,
    )
    return AskResponse(**result)