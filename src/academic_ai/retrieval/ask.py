"""LLM-synthesized answers over retrieved chunks. Cites pages, no hallucination."""
import json
import logging
import re

import boto3
from sqlalchemy.ext.asyncio import AsyncSession

from academic_ai.config import settings
from academic_ai.ingestion.embeddings import embed
from academic_ai.retrieval.hybrid_search import hybrid_search

log = logging.getLogger(__name__)

_client = None


def _llm_client():
    """REAL AWS Bedrock. Never point at LocalStack."""
    global _client
    if _client is None:
        session = (
            boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
            if settings.aws_profile
            else boto3.Session(region_name=settings.aws_region)
        )
        _client = session.client("bedrock-runtime")
        log.info("bedrock-runtime (LLM) created: region=%s profile=%s model=%s",
                 settings.aws_region, settings.aws_profile, settings.llm_model_id)
    return _client


SYSTEM_PROMPT = """You are a precise academic assistant. Answer ONLY using the provided context chunks.

Rules:
1. If the context does not contain the answer, say: "I couldn't find this in your uploaded documents."
2. Cite every factual claim with [p.N] where N is the page number from the chunk header.
3. Be concise. Prefer bullet lists for multi-part answers.
4. Never invent page numbers or facts not present in the context.
5. If multiple chunks cover the same point, cite the most specific one."""


def _build_context(hits: list[dict]) -> str:
    """Format retrieved chunks into the prompt context."""
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(
            f"[Chunk {i}] (page {h['page_number']})\n{h['content']}\n"
        )
    return "\n---\n".join(parts)


REFUSAL_MARKERS = (
    "couldn't find",
    "could not find",
    "cannot find",
    "no relevant",
    "not in your uploaded",
    "not mentioned in",
)


def _extract_citations(answer: str, hits: list[dict]) -> list[dict]:
    """
    Parse [p.N] markers, including multi-page [p.3, p.11] format.
    Returns only hits whose page was cited.
    """
    lower = answer.lower()
    if any(m in lower for m in REFUSAL_MARKERS):
        return []

    # Match [p.3] AND [p.3, p.11, p.14]
    cited_pages: set[int] = set()
    for group in re.findall(r"\[p\.(\d+(?:\s*,\s*p\.\d+)*)\]", answer):
        for n in re.findall(r"\d+", group):
            cited_pages.add(int(n))

    if not cited_pages:
        return hits

    seen = set()
    citations = []
    for h in hits:
        key = (h["document_id"], h["page_number"])
        if h["page_number"] in cited_pages and key not in seen:
            seen.add(key)
            citations.append({
                "chunk_id":    h["chunk_id"],
                "document_id": h["document_id"],
                "page_number": h["page_number"],
                "content":     h["content"][:400],
            })
    return citations

async def ask(
    db: AsyncSession,
    *,
    user_id,
    workspace_id,
    question: str,
    top_k: int | None = None,
) -> dict:
    """
    Retrieve + synthesize. Returns {answer, citations, chunks_used}.
    """
    k = top_k or settings.ask_top_k

    # 1. Retrieve (unchanged Phase 5 code)
    hits = await hybrid_search(
        db,
        user_id=user_id,
        workspace_id=workspace_id,
        query_text=question,
        query_embedding=embed(question),
        top_k=k,
    )

    if not hits:
        return {
            "answer":     "I couldn't find any relevant content in your uploaded documents. "
                          "Try uploading a syllabus or course notes first.",
            "citations":  [],
            "chunks_used": 0,
        }

    # 2. Build prompt
    context = _build_context(hits)
    user_prompt = f"""Context chunks from the user's documents:

{context}

Question: {question}

Answer (cite pages as [p.N]):"""

    # 3. Call Mistral Large 3 (chat completion format)
    try:
        resp = _llm_client().invoke_model(
            modelId=settings.llm_model_id,
            body=json.dumps({
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": settings.llm_max_tokens,
                "temperature": settings.llm_temperature,
            }),
            contentType="application/json",
            accept="application/json",
        )
    except Exception as e:
        log.exception("LLM call failed")
        return {
            "answer":     f"Sorry, I couldn't generate an answer right now ({e.__class__.__name__}). "
                          "The retrieved documents are below.",
            "citations":  [
                {
                    "chunk_id":    h["chunk_id"],
                    "document_id": h["document_id"],
                    "page_number": h["page_number"],
                    "content":     h["content"][:400],
                }
                for h in hits
            ],
            "chunks_used": len(hits),
        }

    body = json.loads(resp["body"].read())
    answer = body["choices"][0]["message"]["content"].strip()

    # 4. Extract cited pages
    citations = _extract_citations(answer, hits)

    return {
        "answer":     answer,
        "citations":  citations,
        "chunks_used": len(hits),
    }