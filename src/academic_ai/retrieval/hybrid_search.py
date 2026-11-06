from sqlalchemy import text

HYBRID_RRF_SQL = text("""
WITH q AS (
    SELECT plainto_tsquery('english', :query_text) AS tsq,
           CAST(:query_embedding AS vector)        AS qvec
),
semantic_search AS (
    SELECT id, document_id, page_number, content, metadata,
           ROW_NUMBER() OVER (ORDER BY embedding <=> q.qvec) AS rank_ix
    FROM document_chunks, q
    WHERE user_id = CAST(:user_id AS uuid)
      AND (CAST(:workspace_id AS uuid) IS NULL
           OR workspace_id = CAST(:workspace_id AS uuid))
    ORDER BY embedding <=> q.qvec
    LIMIT 20
),
keyword_search AS (
    SELECT id, document_id, page_number, content, metadata,
           ROW_NUMBER() OVER (ORDER BY ts_rank_cd(search_vector, q.tsq) DESC) AS rank_ix
    FROM document_chunks, q
    WHERE user_id = CAST(:user_id AS uuid)
      AND (CAST(:workspace_id AS uuid) IS NULL
           OR workspace_id = CAST(:workspace_id AS uuid))
      AND search_vector @@ q.tsq
    ORDER BY ts_rank_cd(search_vector, q.tsq) DESC
    LIMIT 20
)
SELECT
    COALESCE(s.id, k.id)                    AS chunk_id,
    COALESCE(s.document_id, k.document_id)  AS document_id,
    COALESCE(s.page_number, k.page_number)  AS page_number,
    COALESCE(s.content, k.content)          AS content,
    COALESCE(s.metadata, k.metadata)        AS metadata,
    COALESCE(1.0 / (60 + s.rank_ix), 0.0)
  + COALESCE(1.0 / (60 + k.rank_ix), 0.0)   AS rrf_score
FROM semantic_search s
FULL OUTER JOIN keyword_search k ON s.id = k.id
ORDER BY rrf_score DESC
LIMIT :top_k;
""")


async def hybrid_search(db, *, user_id, workspace_id, query_text, query_embedding, top_k=5):
    result = await db.execute(HYBRID_RRF_SQL, {
        "user_id":         str(user_id),
        "workspace_id":    str(workspace_id) if workspace_id else None,
        "query_text":      query_text,
        "query_embedding": "[" + ",".join(map(str, query_embedding)) + "]",
        "top_k":           top_k,
    })
    return [dict(r) for r in result.mappings().all()]