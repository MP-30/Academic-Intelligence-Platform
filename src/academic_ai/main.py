import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from academic_ai.api.agent import router as agent_router
from academic_ai.api.ask import router as ask_router
from academic_ai.api.auth import router as auth_router
from academic_ai.api.documents import router as documents_router
from academic_ai.api.search import router as search_router
from academic_ai.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="Academic Intelligence Platform",
    description="RAG pipeline over academic PDFs — hybrid retrieval with page-cited results.",
    version="0.3.5",
)

# CORS — useful later for browser frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.cors_allowed_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(search_router)
app.include_router(ask_router)
app.include_router(agent_router)


@app.get("/health")
def health():
    return {"status": "ok"}