"""Strands orchestrator — routes between MCP doc-server and web-server.

Two operating modes:
- v0.4 fallback: in-process tools (fast, no MCP dependency)
- v0.5 default: MCP tools via streamable HTTP (reusable, protocol-compliant)

Switch: settings.use_mcp_tools (bool). Defaults to True.
"""
import logging
from uuid import UUID

import boto3
from strands import Agent
from strands.models import BedrockModel

from academic_ai.agents.mcp_client import make_mcp_clients
from academic_ai.agents.tools.document_tools import search_course_documents
from academic_ai.agents.tools.web_tools import search_web
from academic_ai.config import settings

log = logging.getLogger(__name__)

_model = None


def _bedrock_model() -> BedrockModel:
    """REAL AWS Bedrock. Never point at LocalStack."""
    global _model
    if _model is None:
        session = (
            boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
            if settings.aws_profile
            else boto3.Session(region_name=settings.aws_region)
        )
        _model = BedrockModel(
            boto_session=session,
            model_id=settings.strands_model_id,
            temperature=settings.agent_temperature,
        )
        log.info("strands BedrockModel created: model=%s", settings.strands_model_id)
    return _model


SYSTEM_PROMPT = """You are an academic intelligence assistant with two tools:

1. `search_course_documents(query)` — user's uploaded PDFs
2. `search_web(query)` — public web via Tavily

Routing:
- Questions about user's uploaded content → `search_course_documents`
- Questions needing current/external info → `search_web`
- Complex comparisons → call BOTH, then synthesize

CITATION FORMAT — MANDATORY, EXACT SYNTAX:

When citing a document chunk, append: [Doc p.N]
  Example: "Sciences include Biology, Chemistry, Physics [Doc p.3]"

When citing a web result, append: [Web: TITLE (URL)]
  Example: "RAGAS is popular [Web: RAG Evaluation Guide (https://atlan.com/know/rag-eval)]"

Do NOT use markdown links like [text](url). Use the [Web: ...] format above.
Do NOT use footnote markers like [1], [2], or [^1].
Do NOT invent URLs — only cite URLs returned by search_web.

If a tool fails or returns nothing, explicitly say "Web search returned no results" or "No matching documents found."

Style:
- Concise bullet lists for multi-part answers
- Remember earlier context in follow-up questions
- Never fabricate facts, page numbers, or URLs
- Answer in 150-250 words unless the user explicitly asks for detail
- Cite page numbers like [Doc p.N], do not reproduce source chunk text verbatim
- For "tell me more" / "elaborate" follow-ups, extend the previous answer by 1-2 points. Do not restart the answer from scratch.
"""


# ──────────────────────────────────────────────────────────────
# v0.4 fallback path — in-process tools (kept as backup)
# ──────────────────────────────────────────────────────────────
def create_agent(history: list[dict] | None = None) -> Agent:
    """Legacy in-process agent (v0.4 mode). Use when USE_MCP_TOOLS=false."""
    kwargs = {
        "model": _bedrock_model(),
        "system_prompt": SYSTEM_PROMPT,
        "tools": [search_course_documents, search_web],
    }
    if history:
        kwargs["messages"] = history
    agent = Agent(**kwargs)
    log.info("strands agent created via IN-PROCESS tools (history=%d)", len(history or []))
    return agent


# ──────────────────────────────────────────────────────────────
# v0.5 default — MCP-based agent
# ──────────────────────────────────────────────────────────────
def create_agent_with_mcp(
    user_id: UUID, workspace_id: UUID | None, history: list[dict] | None = None
):
    """Return an async context manager that yields (agent, cleanup_fn).

    Usage:
        async with create_agent_with_mcp(user_id, ws_id, history) as agent:
            result = agent("question")
    """
    return _AgentWithMCPContext(user_id, workspace_id, history)


class _AgentWithMCPContext:
    """Context manager that binds MCP clients + Strands agent for one request."""

    def __init__(self, user_id: UUID, workspace_id: UUID | None, history: list[dict] | None):
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.history = history
        self.doc_mcp = None
        self.web_mcp = None
        self.http_client = None
        self.agent = None

    async def __aenter__(self):
        self.doc_mcp, self.web_mcp, self.http_client = make_mcp_clients(
            self.user_id, self.workspace_id
        )

        # MCPClient is a SYNC context manager. Call __enter__ explicitly.
        # The underlying streamable_http_client runs its own event loop in
        # a background thread, so this works from async callers too.
        self.doc_mcp.__enter__()
        self.web_mcp.__enter__()

        # list_tools_sync is also sync — wrap in thread to avoid blocking
        # the FastAPI event loop during MCP handshake (~100-300ms each)
        import asyncio
        doc_tools = await asyncio.to_thread(self.doc_mcp.list_tools_sync)
        web_tools = await asyncio.to_thread(self.web_mcp.list_tools_sync)
        all_tools = doc_tools + web_tools

        log.info(
            "MCP tools loaded: %d total (%d doc, %d web)",
            len(all_tools), len(doc_tools), len(web_tools),
        )

        kwargs = {
            "model": _bedrock_model(),
            "system_prompt": SYSTEM_PROMPT,
            "tools": all_tools,
        }
        if self.history:
            kwargs["messages"] = self.history
        self.agent = Agent(**kwargs)
        return self.agent

    async def __aexit__(self, *exc):
        # Cleanup failures must NOT crash the request.
        try:
            if self.web_mcp:
                self.web_mcp.__exit__(*exc)
        except Exception as e:
            log.warning("web_mcp exit failed (harmless): %s", e)
        try:
            if self.doc_mcp:
                self.doc_mcp.__exit__(*exc)
        except Exception as e:
            log.warning("doc_mcp exit failed (harmless): %s", e)
        try:
            if self.http_client:
                await self.http_client.aclose()
        except RuntimeError:
            log.debug("http_client.aclose() skipped: event loop closed")
        except Exception as e:
            log.warning("http_client.aclose() failed (harmless): %s", e)
