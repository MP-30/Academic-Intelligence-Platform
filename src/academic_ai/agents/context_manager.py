import logging
from pathlib import Path
from uuid import UUID

import boto3
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from academic_ai.config import settings
from academic_ai.db.models import Conversation, Message

log = logging.getLogger(__name__)

SUMMARY_PROMPT_PATH = Path(__file__).parent / "prompts" / "summary.md"


async def get_or_create_conversation(
    db: AsyncSession,
    *,
    conversation_id: UUID | None,
    user_id: UUID,
    workspace_id: UUID | None,
) -> UUID:
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
    """Return prior messages as Strands-format history.

    If the conversation has been compacted, prepends the rolling summary
    as a synthetic exchange and returns only un-summarized messages.
    """
    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    rolling_summary = conv.rolling_summary if conv else None

    rows = (await db.execute(text("""
        SELECT role, content_blocks
        FROM messages
        WHERE conversation_id = :cid AND summarized = FALSE
        ORDER BY created_at ASC
    """), {"cid": str(conversation_id)})).mappings().all()

    history: list[dict] = []
    if rolling_summary:
        history.append({
            "role": "user",
            "content": [{"text": f"[Previous conversation summary]\n{rolling_summary}"}],
        })
        history.append({
            "role": "assistant",
            "content": [{"text": "Understood. Continuing from where we left off."}],
        })

    for r in rows:
        content = r["content_blocks"] or []
        if not isinstance(content, list):
            continue
        history.append({"role": r["role"], "content": content})

    log.info(
        "loaded %d messages for conv %s (compacted=%s)",
        len(history), conversation_id, bool(rolling_summary),
    )
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
    user_msg = Message(
        conversation_id=conversation_id, user_id=user_id, role="user",
        content_blocks=[{"text": user_text}], citations=[], agent_metadata={},
    )
    db.add(user_msg)

    assistant_msg = Message(
        conversation_id=conversation_id, user_id=user_id, role="assistant",
        content_blocks=[{"text": assistant_text}],
        citations=citations,
        agent_metadata={"tool_calls": tool_calls},
    )
    db.add(assistant_msg)

    await db.execute(text("""
        UPDATE conversations SET updated_at = NOW() WHERE id = :cid
    """), {"cid": str(conversation_id)})

    await db.commit()
    log.info("saved turn to conv %s (tools=%d, cites=%d)",
             conversation_id, len(tool_calls), len(citations))


def _bedrock_client():
    """Return boto3 bedrock-runtime client, honoring local profile if set."""
    session_kwargs = {"region_name": settings.aws_region}
    if settings.aws_profile:
        session_kwargs["profile_name"] = settings.aws_profile
    return boto3.Session(**session_kwargs).client("bedrock-runtime")


async def compact_if_needed(db: AsyncSession, conversation_id: UUID) -> None:
    """Summarize older messages into conv.rolling_summary when threshold hit.

    Called as a FastAPI background task — the user's response has already
    been sent by the time this runs. Safe to be slow.
    """
    rows = (await db.execute(text("""
        SELECT id, role, content_blocks
        FROM messages
        WHERE conversation_id = :cid AND summarized = FALSE
        ORDER BY created_at ASC
    """), {"cid": str(conversation_id)})).mappings().all()

    trigger_messages = settings.summary_trigger_turns * 2
    keep_messages = settings.recent_messages_keep

    if len(rows) <= trigger_messages:
        return

    to_summarize = rows[: len(rows) - keep_messages]
    if not to_summarize:
        return

    conv = (await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )).scalar_one_or_none()
    if conv is None:
        return
    previous_summary = conv.rolling_summary or ""

    template = SUMMARY_PROMPT_PATH.read_text()
    transcript = "\n\n".join(
        f"[{m['role']}]: {m['content_blocks'][0].get('text', '')}"
        for m in to_summarize
        if m["content_blocks"]
    )
    prompt = (
        template
        .replace("{previous_summary}", previous_summary or "(none)")
        .replace("{messages}", transcript)
    )

    try:
        client = _bedrock_client()
        resp = client.converse(
            modelId=settings.strands_model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={
                "maxTokens": settings.summary_max_tokens,
                "temperature": 0.2,
            },
        )
        new_summary = resp["output"]["message"]["content"][0]["text"].strip()
    except Exception as e:
        log.exception("compaction LLM call failed for conv %s: %s", conversation_id, e)
        return

    if not new_summary:
        log.warning("compaction produced empty summary for conv %s", conversation_id)
        return

    conv.rolling_summary = new_summary
    for m in to_summarize:
        await db.execute(
            text("UPDATE messages SET summarized = TRUE WHERE id = :mid"),
            {"mid": str(m["id"])},
        )
    await db.commit()

    log.info(
        "compacted %d messages into %d-char summary for conv %s",
        len(to_summarize), len(new_summary), conversation_id,
    )