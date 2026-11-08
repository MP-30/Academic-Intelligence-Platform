"""Strands tools — web search via Tavily."""
import logging

from strands import tool

from academic_ai.config import settings

log = logging.getLogger(__name__)

_tavily_client = None


def _tavily():
    global _tavily_client
    if _tavily_client is None:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=settings.tavily_api_key)
        log.info("Tavily client created")
    return _tavily_client


@tool
def search_web(query: str, max_results: int = 3) -> list[dict]:
    """Search the public web for current information, external research, or general knowledge.

    Use this when the user's question is about information not in their
    uploaded documents — current events, external research, recent papers,
    web content, or general facts.

    Args:
        query: Natural-language search query
        max_results: Number of results to return (default 3, max 5)

    Returns:
        List of web results with fields: title, url, content (snippet), score.
        Always cite as [Web: title (URL)].
    """
    if not settings.tavily_api_key:
        log.warning("search_web called but TAVILY_API_KEY not configured")
        return [{"error": "web search not configured"}]

    try:
        resp = _tavily().search(
            query=query,
            max_results=min(max_results, 5),
            search_depth="basic",
        )
    except Exception as e:
        log.exception("tavily search failed")
        return [{"error": f"web search failed: {e.__class__.__name__}"}]

    results = resp.get("results", [])
    log.info("search_web: query=%r -> %d results", query, len(results))

    return [
        {
            "title":   r.get("title", ""),
            "url":     r.get("url", ""),
            "content": r.get("content", "")[:1500],  # cap snippet length
            "score":   float(r.get("score", 0.0)),
        }
        for r in results
    ]
