from academic_ai.ingestion.parser import parse_pdf


def test_parse_syllabus():
    with open("tests/fixtures/Curriculum_SrSec_2025-26.pdf", "rb") as f:
        pdf = f.read()

    pages, chunks = parse_pdf(pdf)

    assert pages >= 1, "should detect at least one page"
    assert len(chunks) >= 1, "should produce at least one chunk"
    assert all(c.page_number >= 1 for c in chunks), "page numbers are 1-indexed"
    assert all(c.page_number <= pages for c in chunks), "page numbers don't exceed total"
    assert [c.chunk_index for c in chunks] == list(range(len(chunks))), "chunk_index is contiguous 0..N-1"
    assert all(c.content.strip() for c in chunks), "no empty chunks"

    print(f"\n{pages} pages, {len(chunks)} chunks")
    for c in chunks[:3]:
        print(f"  page {c.page_number} chunk {c.chunk_index}: {c.content[:80]!r}...")