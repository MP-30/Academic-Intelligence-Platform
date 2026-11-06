"""Gradio UI for Academic RAG. Thin HTTP client over the FastAPI backend."""
import gradio as gr
import httpx

from academic_ai.config import settings


def upload_pdf(file_path, user_id, workspace_id):
    if not file_path:
        return "❌ No file selected", ""
    if not user_id or not workspace_id:
        return "❌ user_id and workspace_id are required", ""

    try:
        with open(file_path, "rb") as f:
            files = {"file": (file_path.split("/")[-1], f, "application/pdf")}
            r = httpx.post(
                f"{settings.api_base_url}/documents",
                files=files,
                data={"workspace_id": workspace_id},
                headers={"Authorization": f"Bearer {user_id}"},
                timeout=120,
            )
    except httpx.RequestError as e:
        return f"❌ Cannot reach API at `{settings.api_base_url}`: {e}", ""

    if r.status_code != 202:
        return f"❌ Upload failed ({r.status_code}): {r.text}", ""

    d = r.json()
    return (
        f"✅ Uploaded\n\n"
        f"- document_id: `{d['document_id']}`\n"
        f"- job_id: `{d['job_id']}`\n\n"
        f"Click **Check Status** to poll.",
        d["document_id"],
    )


def poll_status(doc_id, user_id):
    if not doc_id:
        return "⚠️ Upload a PDF first"
    if not user_id:
        return "⚠️ user_id required"

    try:
        r = httpx.get(
            f"{settings.api_base_url}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {user_id}"},
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
    return (
        f"{icon} **Status:** {d['processing_status']}\n\n"
        f"- Pages: {d['page_count']}\n"
        f"- Job: {d.get('job_status') or '—'}\n"
        f"- Error: {d.get('job_error') or '—'}"
    )


def search(query, user_id, workspace_id, top_k):
    if not query:
        return "⚠️ Enter a query"
    if not user_id:
        return "⚠️ user_id required"

    body = {
        "query": query,
        "workspace_id": workspace_id or None,
        "top_k": int(top_k),
    }
    try:
        r = httpx.post(
            f"{settings.api_base_url}/search",
            json=body,
            headers={"Authorization": f"Bearer {user_id}"},
            timeout=30,
        )
    except httpx.RequestError as e:
        return f"❌ Network error: {e}"

    if r.status_code != 200:
        return f"❌ Search failed ({r.status_code}): {r.text}"

    d = r.json()
    if d["count"] == 0:
        return f"**0 hits** for _{d['query']}_ — try a different query or upload a PDF first."

    out = [f"**{d['count']} hits** for _{d['query']}_\n"]
    for i, h in enumerate(d["hits"], 1):
        out.append(f"---\n### [{i}] Page {h['page_number']} · score `{h['rrf_score']:.5f}`")
        preview = h["content"][:600].strip()
        if len(h["content"]) > 600:
            preview += "…"
        out.append(f"\n> {preview}\n")
    return "\n".join(out)


with gr.Blocks(title="Academic RAG") as demo:
    gr.Markdown(
        "# 📚 Academic RAG\n"
        f"Upload PDFs, search with page-cited results. "
        f"Backend: `{settings.api_base_url}`"
    )

    with gr.Row():
        user_id = gr.Textbox(
            label="User ID (UUID)",
            placeholder="paste your user uuid",
            scale=2,
        )
        workspace_id = gr.Textbox(
            label="Workspace ID (UUID)",
            placeholder="paste your workspace uuid",
            scale=2,
        )

    with gr.Tab("📤 Upload & Ingest"):
        with gr.Row():
            file = gr.File(label="PDF", file_types=[".pdf"], scale=3)
        upload_btn = gr.Button("Upload & Ingest", variant="primary")
        upload_out = gr.Markdown()
        doc_id_state = gr.State("")
        with gr.Row():
            poll_btn = gr.Button("🔄 Check Status")
        poll_out = gr.Markdown()

    with gr.Tab("🔍 Search"):
        query = gr.Textbox(
            label="Query",
            placeholder="e.g. elective subjects, assessment scheme, physics...",
            lines=2,
        )
        top_k = gr.Slider(1, 10, value=5, step=1, label="Top K")
        search_btn = gr.Button("Search", variant="primary")
        results = gr.Markdown()

    upload_btn.click(
        upload_pdf, [file, user_id, workspace_id], [upload_out, doc_id_state]
    )
    poll_btn.click(poll_status, [doc_id_state, user_id], poll_out)
    search_btn.click(
        search, [query, user_id, workspace_id, top_k], results
    )


if __name__ == "__main__":
    demo.launch(
        server_name=settings.ui_host,
        server_port=settings.ui_port,
        show_error=False,
        share=False,
        theme=gr.themes.Soft(),     # ← moved here
    )