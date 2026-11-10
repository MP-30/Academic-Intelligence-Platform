"""POST /agent — Strands-powered conversational RAG."""
import logging
import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from academic_ai.agents.context_manager import (
    get_or_create_conversation,
    load_history,
    save_turn,
)
from academic_ai.agents.orchestrator import create_agent, create_agent_with_mcp
from academic_ai.agents.tools.document_tools import (
    current_user_id_ctx,
    current_workspace_id_ctx,
)
from academic_ai.api.schemas import (
    AgentCitation,
    AgentRequest,
    AgentResponse,
    AgentToolCall,
)
from academic_ai.auth.dependencies import get_current_user
from academic_ai.config import settings
from academic_ai.db.session import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agent", tags=["agent"])

DOC_CITE_RE = re.compile(r"\[(?:Doc\s+)?p\.(\d+)\]")
WEB_CITE_RE = re.compile(r"\[Web:\s*([^\]\(]+)\(([^\)]+)\)\]")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")
# Fallback: LLM emits "Web: title (url)" without brackets (Mistral does this)
BARE_WEB_RE = re.compile(r"Web:\s*(.+?)\s*\((https?://[^\)]+)\)")
# Fallback 3: bare domain URLs like "arxiv.org/html/2504" (Mistral drops https://)
_COMMON_TLDS = r"(?:com|org|net|io|ai|dev|edu|gov|co|tech|app|info|xyz|so|sh|me)"
BARE_DOMAIN_RE = re.compile(
    rf"\b((?:[a-z0-9][a-z0-9\-]*\.)+{_COMMON_TLDS}(?:/[a-zA-Z0-9\-._~:/?#\[\]@!$&'()*+,;=%]*)?)",
    re.IGNORECASE,
)


def _extract_citations(answer: str, history_new: list[dict]) -> list[AgentCitation]:
    """Parse [Doc p.N] and [Web: title (URL)] markers + tool results."""
    citations: list[AgentCitation] = []
    seen = set()

    # Doc citations from answer text
    for page in DOC_CITE_RE.findall(answer):
        key = ("doc", int(page))
        if key in seen:
            continue
        seen.add(key)
        citations.append(AgentCitation(source="document", page_number=int(page)))

    # Web citations from answer text
    for title, url in WEB_CITE_RE.findall(answer):
        key = ("web", url.strip())
        if key in seen:
            continue
        seen.add(key)
        citations.append(AgentCitation(source="web", url=url.strip(), title=title.strip()))

    for title, url in MD_LINK_RE.findall(answer):
        key = ("web", url.strip())
        if key in seen:
            continue
        seen.add(key)
        citations.append(AgentCitation(source="web", url=url.strip(), title=title.strip()))

    # Fallback 2: bare "Web: title (url)" — Mistral drops the brackets
    for title, url in BARE_WEB_RE.findall(answer):
        key = ("web", url.strip())
        if key in seen:
            continue
        seen.add(key)
        cleaned = title.strip().rstrip(".,;:")
        citations.append(AgentCitation(source="web", url=url.strip(), title=cleaned))

    # Fallback 3: bare domain URLs — Mistral drops https:// scheme entirely
    for url in BARE_DOMAIN_RE.findall(answer):
        url_clean = url.strip().rstrip(".,;:!?)\]")
        if not url_clean.startswith(("http://", "https://")):
            url_clean = "https://" + url_clean
        key = ("web", url_clean)
        if key in seen:
            continue
        seen.add(key)
        # Extract domain as fallback title (no context available for bare URLs)
        title = url_clean.split("//")[-1].split("/")[0]
        citations.append(AgentCitation(source="web", url=url_clean, title=title))

    return citations


def _extract_tool_calls(messages: list) -> list[AgentToolCall]:
    """Extract tool_use blocks from Strands message history."""
    calls: list[AgentToolCall] = []
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("toolUse"):
                tu = block["toolUse"]
                calls.append(AgentToolCall(
                    tool=tu.get("name", "unknown"),
                    args=tu.get("input", {}),
                ))
    return calls

def _extract_contexts(messages: list) -> list[str]:
    """Pull retrieved chunk text out of Strands toolResult blocks.

    Strands stores tool results as:
        {"toolResult": {"toolUseId": "...", "content": [{"text": "..."}], "status": "..."}}
    The tool's `text` payload is a JSON string (list of chunks).
    """
    import json as _json
    contexts: list[str] = []
    for msg in messages:
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", None)
        if not isinstance(content, list):
            continue
        for block in content:
            if not (isinstance(block, dict) and block.get("toolResult")):
                continue
            tr = block["toolResult"]
            for part in tr.get("content", []):
                text = part.get("text") if isinstance(part, dict) else None
                if not text:
                    continue
                # Tool returns JSON: [{page_number, text, ...}, ...]
                try:
                    parsed = _json.loads(text)
                except (ValueError, TypeError):
                    contexts.append(text)
                    continue
                if isinstance(parsed, list):
                    for item in parsed:
                        if isinstance(item, dict) and item.get("text"):
                            contexts.append(item["text"])
                elif isinstance(parsed, dict) and parsed.get("text"):
                    contexts.append(parsed["text"])
    return contexts

@router.post("", response_model=AgentResponse)
async def run_agent(
    req: AgentRequest,
    user_id: UUID = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Multi-turn Strands agent over docs + web with page/URL citations."""
    try:
        conv_id = await get_or_create_conversation(
            db,
            conversation_id=req.conversation_id,
            user_id=user_id,
            workspace_id=req.workspace_id,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))

    history = await load_history(db, conv_id)

    # Bind user context for in-process tools (v0.4 fallback path)
    tok_user = current_user_id_ctx.set(user_id)
    tok_ws = current_workspace_id_ctx.set(req.workspace_id)
    agent_messages_snapshot: list = []

    try:
        if settings.use_mcp_tools:
            # v0.5 default: MCP tools over HTTP
            async with create_agent_with_mcp(
                user_id=user_id,
                workspace_id=req.workspace_id,
                history=history,
            ) as agent:
                try:
                    result = await agent.invoke_async(req.message)
                except AttributeError:
                    # Fallback if Strands version lacks invoke_async
                    result = agent(req.message)
                agent_messages_snapshot = list(agent.messages) if hasattr(agent, "messages") else []
        else:
            # v0.4 fallback: in-process tools
            agent = create_agent(history=history)
            result = agent(req.message)
            agent_messages_snapshot = list(agent.messages) if hasattr(agent, "messages") else []
    except Exception as e:
        log.exception("agent invocation failed")
        raise HTTPException(500, f"Agent failed: {e.__class__.__name__}")
    finally:
        current_user_id_ctx.reset(tok_user)
        current_workspace_id_ctx.reset(tok_ws)

    # Extract answer text
    try:
        answer_text = result.message["content"][0]["text"]
    except Exception:
        answer_text = str(result)

    # Extract tool calls + citations
    tool_calls = _extract_tool_calls(agent_messages_snapshot)
    citations = _extract_citations(answer_text, agent_messages_snapshot)
    contexts = _extract_contexts(agent_messages_snapshot)

    await save_turn(
        db,
        conversation_id=conv_id,
        user_id=user_id,
        user_text=req.message,
        assistant_text=answer_text,
        tool_calls=[tc.model_dump() for tc in tool_calls],
        citations=[c.model_dump() for c in citations],
    )

    return AgentResponse(
        conversation_id=conv_id,
        response=answer_text,
        tool_calls=tool_calls,
        citations=citations,
        contexts=contexts,
    )
