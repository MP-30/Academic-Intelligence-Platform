"""Gradio UI — thin HTTP client. Requires Cognito login.

Uses /agent (v0.4+) so the UI exercises the full stack:
Strands agent, MCP tools, hybrid retrieval, multi-turn memory,
rolling summary compaction (v0.9), rich citations + retrieved contexts.
"""
import re
import time

import gradio as gr
import httpx

from academic_ai.config import settings

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _err(msg: str) -> str:
    return f"❌ {msg}"


def _detail(resp: httpx.Response, default: str) -> str:
    """Extract 'detail' from JSON error responses safely."""
    try:
        return resp.json().get("detail", default)
    except Exception:
        return default


def login(email: str, password: str):
    if not email or not password:
        return "⚠️ Email and password required", ""
    try:
        r = httpx.post(
            f"{settings.api_base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
    except httpx.RequestError as e:
        return _err(f"Network: {e}"), ""
    if r.status_code != 200:
        return _err(_detail(r, "Login failed")), ""
    return f"✅ Logged in as **{email}**", r.json()["id_token"]


def upload_pdf(file_path: str, token: str, workspace_id: str):
    if not token:
        return "❌ Log in first", ""
    if not file_path:
        return "❌ PDF required", ""
    if not workspace_id or not _UUID_RE.match(workspace_id.strip()):
        return "❌ Valid workspace UUID required", ""
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.split("/")[-1], f, "application/pdf")}
            r = httpx.post(
                f"{settings.api_base_url}/documents",
                files=files,
                data={"workspace_id": workspace_id.strip()},
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
            )
    except httpx.RequestError as e:
        return _err(f"Network error: {e}"), ""
    if r.status_code != 202:
        return _err(f"Upload failed ({r.status_code}): {_detail(r, 'unknown')}"), ""
    d = r.json()
    return (
        f"✅ **Uploaded**\n\n- document_id: `{d['document_id']}`\n- job_id: `{d['job_id']}`",
        d["document_id"],
    )


def poll_status(doc_id: str, token: str):
    if not token or not doc_id:
        return "⚠️ Log in and upload a PDF first"
    try:
        r = httpx.get(
            f"{settings.api_base_url}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.RequestError as e:
        return _err(f"Network error: {e}")
    if r.status_code != 200:
        return _err(f"Status check failed ({r.status_code})")
    d = r.json()
    icons = {"READY": "✅", "PENDING": "⏳", "PROCESSING": "🔄", "FAILED": "❌"}
    return f"{icons.get(d['processing_status'], '❓')} **{d['processing_status']}** — {d['page_count']} pages"


def search(query: str, token: str, workspace_id: str, top_k: int):
    if not token or not query:
        return "⚠️ Log in and enter a query"
    body = {"query": query, "workspace_id": workspace_id or None, "top_k": int(top_k)}
    try:
        r = httpx.post(
            f"{settings.api_base_url}/search",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
    except httpx.RequestError as e:
        return _err(f"Network error: {e}")
    if r.status_code != 200:
        return _err(f"Search failed ({r.status_code})")
    d = r.json()
    if d["count"] == 0:
        return f"**0 hits** for _{d['query']}_"
    out = [f"**{d['count']} hits** for _{d['query']}_\n"]
    for i, h in enumerate(d["hits"], 1):
        out.append(f"---\n#### [{i}] Page {h['page_number']} · RRF `{h['rrf_score']:.5f}`")
        out.append(f"\n> {h['content'][:600].strip()}\n")
    return "\n".join(out)


def _format_citations(citations: list[dict]) -> str:
    if not citations:
        return ""
    parts = []
    for c in citations:
        if c.get("source") == "document" and c.get("page_number"):
            parts.append(f"📄 p.{c['page_number']}")
        elif c.get("source") == "web" and c.get("url"):
            title = (c.get("title") or c["url"])[:40]
            parts.append(f"🌐 [{title}]({c['url']})")
    return " · ".join(parts)


def _format_tools(tool_calls: list[dict]) -> str:
    if not tool_calls:
        return ""
    return " · ".join(f"`{t.get('tool', 'unknown')}`" for t in tool_calls)


def _format_contexts(contexts: list[str], limit: int = 3) -> str:
    """Collapsible <details> block for retrieved chunks."""
    if not contexts:
        return ""
    previews = []
    for i, c in enumerate(contexts[:limit]):
        snippet = c[:400].replace("\n", " ")
        if len(c) > 400:
            snippet += "…"
        previews.append(f"**Chunk {i + 1}**\n\n> {snippet}")
    body = "\n\n".join(previews)
    more = f"\n\n*…and {len(contexts) - limit} more*" if len(contexts) > limit else ""
    return (
        f"\n\n<details><summary>📚 {len(contexts)} retrieved chunks</summary>\n\n"
        f"{body}{more}\n\n</details>"
    )


def chat_agent(question: str, history: list, token: str, workspace_id: str, conv_id: str):
    """Chat via /agent — multi-turn, MCP tools, citations, contexts."""
    history = history or []
    if not token or not question or not question.strip():
        return history, "", conv_id, ""

    body = {"message": question, "workspace_id": workspace_id or None}
    if conv_id:
        body["conversation_id"] = conv_id

    t0 = time.time()
    try:
        r = httpx.post(
            f"{settings.api_base_url}/agent",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=180,
        )
    except httpx.RequestError as e:
        return (
            history + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": _err(f"Network: {e}")},
            ],
            "",
            conv_id,
            "",
        )

    elapsed = time.time() - t0

    if r.status_code != 200:
        detail = _detail(r, f"HTTP {r.status_code}")
        return (
            history + [
                {"role": "user", "content": question},
                {"role": "assistant", "content": _err(detail)},
            ],
            "",
            conv_id,
            "",
        )

    d = r.json()
    new_conv = d.get("conversation_id") or conv_id

    meta_lines = []
    tools_str = _format_tools(d.get("tool_calls", []))
    if tools_str:
        meta_lines.append(f"*Tools:* {tools_str}")
    cites_str = _format_citations(d.get("citations", []))
    if cites_str:
        meta_lines.append(f"*Sources:* {cites_str}")
    n_ctx = len(d.get("contexts", []))
    if n_ctx:
        meta_lines.append(f"*Retrieved {n_ctx} chunk{'s' if n_ctx != 1 else ''}*")

    formatted = d["response"]
    if meta_lines:
        formatted += "\n\n---\n" + "  \n".join(meta_lines)
    formatted += _format_contexts(d.get("contexts", []))

    status = f"⏱ {elapsed:.1f}s"
    if new_conv:
        status += f" · 💬 `{new_conv[:8]}…`"

    return (
        history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": formatted},
        ],
        "",
        new_conv,
        status,
    )


def new_conversation():
    return [], "", "🆕 New conversation started"


with gr.Blocks(
    title="Academic RAG",
    theme=gr.themes.Soft(primary_hue="blue"),
    css=".gradio-container { max-width: 1200px !important; }",
) as demo:
    gr.Markdown("# 📚 Academic RAG")
    gr.Markdown(
        f"Backend: `{settings.api_base_url}` · "
        "Hybrid retrieval + MCP tools + citation grounding + rolling memory"
    )

    with gr.Group():
        with gr.Row():
            email = gr.Textbox(label="Email", scale=2, placeholder="you@example.com")
            password = gr.Textbox(label="Password", type="password", scale=2)
            login_btn = gr.Button("Login", variant="primary", scale=1)
        login_status = gr.Markdown("🔒 Not logged in")
        token_state = gr.State("")

    workspace_id = gr.Textbox(
        label="Workspace ID (UUID)",
        placeholder="paste workspace uuid",
        info="Required for upload, search, and chat. All operations are tenant-scoped.",
    )

    with gr.Tabs():
        with gr.Tab("💬 Chat"):
            with gr.Row():
                chat_status = gr.Markdown("💬 Start a new conversation")
                new_conv_btn = gr.Button("🆕 New", size="sm", scale=0)

            chatbot = gr.Chatbot(
                label="Assistant",
                height=500,
                value=[],
                show_label=False,
            )
            chat_input = gr.Textbox(
                label="Ask",
                lines=2,
                placeholder="Ask about your uploaded documents or the web…",
            )
            with gr.Row():
                chat_send = gr.Button("Send", variant="primary", scale=3)
                chat_clear = gr.Button("Clear History", scale=1)
            conv_id_state = gr.State("")

        with gr.Tab("📤 Upload & Ingest"):
            gr.Markdown(
                "Upload a PDF. Ingestion runs async via **SQS → ECS worker → pgvector**."
            )
            file = gr.File(label="PDF", file_types=[".pdf"])
            upload_btn = gr.Button("Upload & Ingest", variant="primary")
            upload_out = gr.Markdown()
            doc_id_state = gr.State("")
            poll_btn = gr.Button("🔄 Check Status")
            poll_out = gr.Markdown()

        with gr.Tab("🔍 Search"):
            gr.Markdown("Raw retrieval (no LLM synthesis) — useful for debugging.")
            query = gr.Textbox(label="Query", lines=2)
            top_k = gr.Slider(1, 10, value=5, step=1, label="Top K")
            search_btn = gr.Button("Search", variant="primary")
            results = gr.Markdown()

    login_btn.click(login, [email, password], [login_status, token_state])
    upload_btn.click(upload_pdf, [file, token_state, workspace_id], [upload_out, doc_id_state])
    poll_btn.click(poll_status, [doc_id_state, token_state], poll_out)
    search_btn.click(search, [query, token_state, workspace_id, top_k], results)

    chat_send.click(
        chat_agent,
        [chat_input, chatbot, token_state, workspace_id, conv_id_state],
        [chatbot, chat_input, conv_id_state, chat_status],
    )
    chat_input.submit(
        chat_agent,
        [chat_input, chatbot, token_state, workspace_id, conv_id_state],
        [chatbot, chat_input, conv_id_state, chat_status],
    )
    new_conv_btn.click(new_conversation, outputs=[chatbot, conv_id_state, chat_status])
    chat_clear.click(lambda: ([], ""), outputs=[chatbot, chat_input])


if __name__ == "__main__":
    demo.queue(default_concurrency_limit=4).launch(
        server_name=settings.ui_host,
        server_port=settings.ui_port,
        show_error=False,
        share=False,
    )