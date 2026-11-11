"""Manual verification: compaction fires, summary persists, load_history trims.

Run:
    make up          # postgres must be live
    uv run python -m tests.manual.test_compaction

What it does:
  - Creates a throwaway conversation
  - Inserts 12 turns (24 messages)
  - Runs compact_if_needed with mocked Bedrock (no AWS call)
  - Verifies load_history returns 2 (summary pair) + 8 (kept) = 10 messages
  - Cleans up the throwaway conversation
"""
import asyncio
from unittest.mock import MagicMock, patch
from uuid import uuid4

from sqlalchemy import delete

from academic_ai.agents.context_manager import (
    compact_if_needed,
    get_or_create_conversation,
    load_history,
    save_turn,
)
from academic_ai.db.models import Conversation
from academic_ai.db.session import SessionLocal


async def _cleanup(conv_id):
    async with SessionLocal() as db:
        await db.execute(delete(Conversation).where(Conversation.id == conv_id))
        await db.commit()


async def main():
    user_id = uuid4()
    conv_id = None
    try:
        async with SessionLocal() as db:
            conv_id = await get_or_create_conversation(
                db, conversation_id=None, user_id=user_id, workspace_id=None,
            )
            print(f"conv_id: {conv_id}")

            for i in range(12):
                await save_turn(
                    db,
                    conversation_id=conv_id,
                    user_id=user_id,
                    user_text=f"question {i}",
                    assistant_text=f"answer {i}",
                    tool_calls=[],
                    citations=[],
                )

            hist_before = await load_history(db, conv_id)
            print(f"before: {len(hist_before)} messages")

            fake = MagicMock()
            fake.converse.return_value = {
                "output": {
                    "message": {
                        "content": [
                            {"text": "Summary of turns 1-8: user asked about elective areas, language requirements, and grading scale."}
                        ]
                    }
                }
            }

            with patch(
                "academic_ai.agents.context_manager._bedrock_client",
                return_value=fake,
            ):
                await compact_if_needed(db, conv_id)

            hist_after = await load_history(db, conv_id)
            print(f"after:  {len(hist_after)} messages")
            print(f"first message: {hist_after[0]['content'][0]['text'][:80]}")

            assert len(hist_after) < len(hist_before), (
                f"compaction didn't trim: {len(hist_before)} -> {len(hist_after)}"
            )
            assert "[Previous conversation summary]" in hist_after[0]["content"][0]["text"], (
                "first message missing summary prefix"
            )
            assert len(hist_after) == 2 + 8, (
                f"expected summary(2) + kept(8) = 10, got {len(hist_after)}"
            )
            print("✅ compaction works")

    finally:
        if conv_id:
            await _cleanup(conv_id)
            print(f"cleaned up conversation {conv_id}")


if __name__ == "__main__":
    asyncio.run(main())