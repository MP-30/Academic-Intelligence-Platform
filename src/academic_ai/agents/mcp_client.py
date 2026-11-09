"""MCP client wrapper — connects Strands agent to external MCP servers.

Each request creates a fresh connection (no long-lived state across users).
Headers are bound per-request from the authenticated user_id/workspace_id.
"""
import logging
from uuid import UUID

import httpx
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp import MCPClient

from academic_ai.config import settings

log = logging.getLogger(__name__)


def make_mcp_clients(
    user_id: UUID, workspace_id: UUID | None
) -> tuple[MCPClient, MCPClient, httpx.AsyncClient]:
    """Return (doc_mcp_client, web_mcp_client, http_client) for Strands.

    The http_client carries the auth headers and must be closed by the caller.
    Strands MCPClient objects must be used as context managers.
    """
    headers = {"X-User-Id": str(user_id)}
    if workspace_id:
        headers["X-Workspace-Id"] = str(workspace_id)

    http_client = httpx.AsyncClient(headers=headers, timeout=60.0)

    doc_mcp = MCPClient(
        lambda: streamable_http_client(settings.doc_mcp_url, http_client=http_client)
    )
    web_mcp = MCPClient(
        lambda: streamable_http_client(settings.web_mcp_url, http_client=http_client)
    )

    log.info("created MCP clients for user=%s ws=%s", user_id, workspace_id)
    return doc_mcp, web_mcp, http_client
