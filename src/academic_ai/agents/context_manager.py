"""Load/save conversation history from Postgres JSONB (v0.1 schema)."""
import logging
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from academic_ai.db.models import Conversation, Message

log = logging.getLogger(__name__)


async def get_or_create_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID | None,
    user_id: UUID,
    workspace_id: UUID | None,
) -> UUID:
    """Return an existing conversation_id or create a new one."""
    if conversation_id is not None:
        row = (await db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.user_id == user_id,
            )
        )).scalar_one_or_none()
        if row is None:
            raise ValueError(f"Conversation {conversation_id} not found for user")
        return row.id

    conv = Conversation(
        user_id=user_id,
        workspace_id=workspace_id,
        title="Agent session",
    )
    db.add(conv)
    await db.flush()
    await db.commit()
    log.info("created conversation %s for user %s", conv.id, user_id)
    return conv.id


async def load_history(
    db: AsyncSession, conversation_id: UUID
) -> list[dict]:
    """Return prior messages as Strands-format history."""
    rows = (await db.execute(text("""
        SELECT role, content_blocks
        FROM messages
        WHERE conversation_id = :cid
        ORDER BY created_at ASC
    """), {"cid": str(conversation_id)})).mappings().all()

    history = []
    for r in rows:
        content = r["content_blocks"] or []
        # Ensure it's Strands-format list of {"text": "..."} blocks
        if not isinstance(content, list):
            continue
        history.append({"role": r["role"], "content": content})
    log.info("loaded %d prior messages for conv %s", len(history), conversation_id)
    return history


async def save_turn(
    db: AsyncSession,
    *,
    conversation_id: UUID,
    user_id: UUID,
    user_text: str,
    assistant_text: str,
    tool_calls: list[dict],
    citations: list[dict],
) -> None:
    """Persist one user+assistant turn to messages table."""
    user_msg = Message(
        conversation_id=conversation_id,
        user_id=user_id,
        role="user",
        content_blocks=[{"text": user_text}],
        citations=[],
        agent_metadata={},
    )
    db.add(user_msg)

    assistant_msg = Message(
        conversation_id=conversation_id,
        user_id=user_id,
        role="assistant",
        content_blocks=[{"text": assistant_text}],
        citations=citations,
        agent_metadata={"tool_calls": tool_calls},
    )
    db.add(assistant_msg)

    await db.execute(text("""
        UPDATE conversations
        SET updated_at = NOW()
        WHERE id = :cid
    """), {"cid": str(conversation_id)})

    await db.commit()
    log.info("saved turn to conv %s (tools=%d, cites=%d)",
             conversation_id, len(tool_calls), len(citations))
