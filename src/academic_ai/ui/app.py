"""Gradio UI — thin HTTP client. Requires Cognito login."""
import gradio as gr
import httpx

from academic_ai.config import settings


def login(email, password):
    if not email or not password:
        return "⚠️ Email and password required", ""
    try:
        r = httpx.post(
            f"{settings.api_base_url}/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
    except httpx.RequestError as e:
        return f"❌ Network: {e}", ""
    if r.status_code != 200:
        return f"❌ {r.json().get('detail', 'Login failed')}", ""
    return f"✅ Logged in as {email}", r.json()["id_token"]


def upload_pdf(file_path, token, workspace_id):
    if not token:
        return "❌ Log in first", ""
    if not file_path or not workspace_id:
        return "❌ File and workspace_id required", ""
    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.split("/")[-1], f, "application/pdf")}
            r = httpx.post(
                f"{settings.api_base_url}/documents",
                files=files,
                data={"workspace_id": workspace_id},
                headers={"Authorization": f"Bearer {token}"},
                timeout=120,
            )
    except httpx.RequestError as e:
        return f"❌ Network error: {e}", ""
    if r.status_code != 202:
        return f"❌ Upload failed ({r.status_code}): {r.text}", ""
    d = r.json()
    return (
        f"✅ Uploaded\n\n- document_id: `{d['document_id']}`\n- job_id: `{d['job_id']}`",
        d["document_id"],
    )


def poll_status(doc_id, token):
    if not token or not doc_id:
        return "⚠️ Log in and upload a PDF first"
    try:
        r = httpx.get(
            f"{settings.api_base_url}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
    except httpx.RequestError as e:
        return f"❌ Network error: {e}"
    if r.status_code != 200:
        return f"❌ Status check failed ({r.status_code}): {r.text}"
    d = r.json()
    icon = {"READY": "✅", "PENDING": "⏳", "PROCESSING": "🔄", "FAILED": "❌"}.get(
        d["processing_status"], "❓"
    )
    return f"{icon} **{d['processing_status']}** — {d['page_count']} pages"


def search(query, token, workspace_id, top_k):
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
        return f"❌ Network error: {e}"
    if r.status_code != 200:
        return f"❌ Search failed ({r.status_code}): {r.text}"
    d = r.json()
    if d["count"] == 0:
        return f"**0 hits** for _{d['query']}_"
    out = [f"**{d['count']} hits** for _{d['query']}_\n"]
    for i, h in enumerate(d["hits"], 1):
        out.append(f"---\n### [{i}] Page {h['page_number']} · `{h['rrf_score']:.5f}`")
        preview = h["content"][:600].strip()
        out.append(f"\n> {preview}\n")
    return "\n".join(out)


def chat_ask(question, history, token, workspace_id):
    if not token or not question or not question.strip():
        return history, ""
    body = {"question": question, "workspace_id": workspace_id or None}
    try:
        r = httpx.post(
            f"{settings.api_base_url}/ask",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
    except httpx.RequestError as e:
        return history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"❌ {e}"},
        ], ""
    if r.status_code != 200:
        return history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": f"❌ {r.status_code}"},
        ], ""
    d = r.json()
    answer = d["answer"]
    if d["citations"]:
        pages = sorted({c["page_number"] for c in d["citations"]})
        answer += f"\n\n*Sources: pages {', '.join(map(str, pages))}*"
    return history + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ], ""


with gr.Blocks(title="Academic RAG") as demo:
    gr.Markdown("# 📚 Academic RAG")
    gr.Markdown(f"Backend: `{settings.api_base_url}`")

    with gr.Row():
        email = gr.Textbox(label="Email", scale=2)
        password = gr.Textbox(label="Password", type="password", scale=2)
        login_btn = gr.Button("Login", variant="primary", scale=1)
    login_status = gr.Markdown()
    token_state = gr.State("")

    workspace_id = gr.Textbox(
        label="Workspace ID (UUID)", placeholder="paste your workspace uuid"
    )

    with gr.Tab("📤 Upload & Ingest"):
        file = gr.File(label="PDF", file_types=[".pdf"])
        upload_btn = gr.Button("Upload & Ingest", variant="primary")
        upload_out = gr.Markdown()
        doc_id_state = gr.State("")
        poll_btn = gr.Button("🔄 Check Status")
        poll_out = gr.Markdown()

    with gr.Tab("🔍 Search"):
        query = gr.Textbox(label="Query", lines=2)
        top_k = gr.Slider(1, 10, value=5, step=1, label="Top K")
        search_btn = gr.Button("Search", variant="primary")
        results = gr.Markdown()

    with gr.Tab("💬 Chat"):
        chatbot = gr.Chatbot(label="Assistant", height=500, value=[])
        chat_input = gr.Textbox(label="Ask", lines=2)
        with gr.Row():
            chat_send = gr.Button("Send", variant="primary")
            chat_clear = gr.Button("Clear")

    login_btn.click(login, [email, password], [login_status, token_state])
    upload_btn.click(upload_pdf, [file, token_state, workspace_id], [upload_out, doc_id_state])
    poll_btn.click(poll_status, [doc_id_state, token_state], poll_out)
    search_btn.click(search, [query, token_state, workspace_id, top_k], results)
    chat_send.click(chat_ask, [chat_input, chatbot, token_state, workspace_id], [chatbot, chat_input])
    chat_input.submit(chat_ask, [chat_input, chatbot, token_state, workspace_id], [chatbot, chat_input])
    chat_clear.click(lambda: ([], ""), outputs=[chatbot, chat_input])


if __name__ == "__main__":
    demo.launch(
        server_name=settings.ui_host,
        server_port=settings.ui_port,
        show_error=False,
        share=False,
    )
