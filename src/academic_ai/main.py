import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from academic_ai.api.documents import router as documents_router
from academic_ai.api.search import router as search_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(
    title="Academic Intelligence Platform",
    description="RAG pipeline over academic PDFs — hybrid retrieval with page-cited results.",
    version="0.1.0",
)

# CORS — useful later for browser frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_router)
app.include_router(search_router)


@app.get("/health")
def health():
    return {"status": "ok"}