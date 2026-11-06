"""Proves the retrieval layer enforces tenant isolation at the DB level."""
import uuid

from sqlalchemy import text

from academic_ai.retrieval.hybrid_search import HYBRID_RRF_SQL


def _run_search(db, *, user_id, workspace_id, query_text="elective"):
    """Run the RRF query without hitting Bedrock (dummy embedding)."""
    dummy_vec = "[" + ",".join(["0.03125"] * 1024) + "]"
    rows = db.execute(HYBRID_RRF_SQL, {
        "user_id":         str(user_id),
        "workspace_id":    str(workspace_id) if workspace_id else None,
        "query_text":      query_text,
        "query_embedding": dummy_vec,
        "top_k":           10,
    }).mappings().all()
    return rows


def test_attacker_cannot_see_real_user_chunks(db, seed_chunks):
    """Attacker user + real workspace → 0 chunks."""
    attacker = uuid.uuid4()
    rows = _run_search(
        db,
        user_id=attacker,
        workspace_id=seed_chunks["workspace_id"],
    )
    assert rows == [], f"TENANT LEAK — attacker saw {len(rows)} chunks!"


def test_real_user_wrong_workspace_sees_nothing(db, seed_chunks):
    """Real user + fake workspace → 0 chunks."""
    rows = _run_search(
        db,
        user_id=seed_chunks["user_id"],
        workspace_id=uuid.uuid4(),
    )
    assert rows == [], f"WORKSPACE LEAK — user saw {len(rows)} chunks!"


def test_control_real_user_real_workspace_sees_chunks(db, seed_chunks):
    """Real user + real workspace → should see all seeded chunks."""
    rows = _run_search(
        db,
        user_id=seed_chunks["user_id"],
        workspace_id=seed_chunks["workspace_id"],
    )
    assert len(rows) > 0, "Control failed — isolation is blocking everything!"
    assert len(rows) <= seed_chunks["chunk_count"], "More chunks than seeded"