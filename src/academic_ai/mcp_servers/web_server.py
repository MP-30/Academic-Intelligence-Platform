"""MCP server — web search via Tavily.

Run: python -m academic_ai.mcp_servers.web_server
Listens on http://0.0.0.0:8002/mcp (streamable HTTP transport).
"""
import logging

from mcp.server import MCPServer

from academic_ai.config import settings

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

mcp = MCPServer("academic-web-mcp")

_tavily_client = None


def _tavily():
    global _tavily_client
    if _tavily_client is None:
        from tavily import TavilyClient
        _tavily_client = TavilyClient(api_key=settings.tavily_api_key)
        log.info("Tavily client created")
    return _tavily_client


@mcp.tool()
def search_web(query: str, max_results: int = 3) -> list[dict]:
    """Search the public web for current information, external research, or general knowledge.

    Use this when the user's question is about information not in their
    uploaded documents — current events, external research, recent papers,
    web content, or general facts.

    Args:
        query: Natural-language search query
        max_results: Number of results to return (default 3, max 5)

    Returns:
        List of web results. Each has: title, url, content (snippet), score.
        Always cite as [Web: title (URL)].
    """
    if not settings.tavily_api_key:
        return [{"error": "web search not configured (TAVILY_API_KEY missing)"}]

    max_results = min(max(max_results, 1), 5)

    try:
        resp = _tavily().search(
            query=query,
            max_results=max_results,
            search_depth="basic",
        )
    except Exception as e:
        log.exception("tavily search failed")
        return [{"error": f"web search failed: {e.__class__.__name__}"}]

    results = resp.get("results", [])
    log.info("search_web: query=%r -> %d results", query, len(results))

    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", "")[:1500],
            "score": float(r.get("score", 0.0)),
        }
        for r in results
    ]


if __name__ == "__main__":
    log.info("Starting web-mcp on port %d", settings.web_mcp_port)
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=settings.web_mcp_port,
    )
