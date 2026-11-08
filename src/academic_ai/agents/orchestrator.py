"""Strands orchestrator — routes between document search and web search."""
import logging

import boto3
from strands import Agent
from strands.models import BedrockModel

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
  Example: "RAGAS is a popular evaluation framework [Web: RAG Evaluation Guide (https://atlan.com/know/how-to-evaluate-rag-systems-explained)]"

Do NOT use markdown links like [text](url). Use the [Web: ...] format above.
Do NOT use footnote markers like [1], [2], or [^1].
Do NOT invent URLs — only cite URLs returned by search_web.

If a tool fails or returns nothing, explicitly say "Web search returned no results" or "No matching documents found."

Style:
- Concise bullet lists for multi-part answers
- Remember earlier context in follow-up questions
- Never fabricate facts, page numbers, or URLs
"""

def create_agent(history: list[dict] | None = None) -> Agent:
    """Construct a Strands agent with prior conversation history."""
    kwargs = {
        "model": _bedrock_model(),
        "system_prompt": SYSTEM_PROMPT,
        "tools": [search_course_documents, search_web],
    }
    if history:
        kwargs["messages"] = history

    agent = Agent(**kwargs)
    log.info("strands agent created (history=%d messages)", len(history or []))
    return agent
