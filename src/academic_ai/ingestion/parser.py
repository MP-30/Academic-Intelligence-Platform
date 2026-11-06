import io
from dataclasses import dataclass
from pypdf import PdfReader
import tiktoken

_enc = tiktoken.get_encoding("cl100k_base")


@dataclass
class PageChunk:
    page_number: int
    chunk_index: int
    content: str


def _split_tokens(text: str, size: int, overlap: int) -> list[str]:
    toks = _enc.encode(text)
    if not toks:
        return []
    step = max(1, size - overlap)
    return [_enc.decode(toks[i:i + size]) for i in range(0, len(toks), step)]


def parse_pdf(pdf_bytes: bytes, size: int = 600, overlap: int = 100) -> tuple[int, list[PageChunk]]:
    """Returns (total_pages, chunks). Page numbers are 1-indexed."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    chunks: list[PageChunk] = []
    idx = 0
    for page_num, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if not text:
            continue
        for piece in _split_tokens(text, size, overlap):
            chunks.append(PageChunk(page_number=page_num, chunk_index=idx, content=piece))
            idx += 1
    return len(reader.pages), chunks