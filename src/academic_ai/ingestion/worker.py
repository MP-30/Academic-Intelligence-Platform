import json
import logging
import threading

from sqlalchemy import text

from academic_ai.config import settings
from academic_ai.ingestion.embeddings import embed
from academic_ai.ingestion.parser import parse_pdf
from academic_ai.ingestion.queue import _sqs, get_queue_url
from academic_ai.ingestion.s3_service import download_pdf

log = logging.getLogger(__name__)

# SQS polling config
WAIT_SECONDS = 20
VISIBILITY_SECONDS = settings.ingestion_visibility_seconds   # 300 default
MAX_MESSAGES = 1



# Core processing — the body of Phase 2.2 from the original doc

def process_document(sync_db, job: dict) -> None:
    import uuid

    pdf = download_pdf(job["s3_key"])
    pages, chunks = parse_pdf(
        pdf,
        size=settings.chunk_size_tokens,
        overlap=settings.chunk_overlap_tokens,
    )

    rows = []
    for c in chunks:
        rows.append({
            "id":           str(uuid.uuid4()),          # ← NEW
            "document_id":  job["document_id"],
            "user_id":      job["user_id"],
            "workspace_id": job["workspace_id"],
            "page_number":  c.page_number,
            "chunk_index":  c.chunk_index,
            "content":      c.content,
            "embedding":    "[" + ",".join(map(str, embed(c.content))) + "]",
            "metadata":     json.dumps({"page_number": c.page_number}),
        })

    if rows:
        sync_db.execute(text("""
            INSERT INTO document_chunks
              (id, document_id, user_id, workspace_id, page_number, chunk_index,
               content, embedding, metadata)
            VALUES
              (:id, :document_id, :user_id, :workspace_id, :page_number, :chunk_index,
               :content, CAST(:embedding AS vector), CAST(:metadata AS jsonb))
            ON CONFLICT (document_id, chunk_index) DO NOTHING
        """), rows)

    sync_db.execute(text("""
        UPDATE documents SET processing_status='READY', page_count=:p WHERE id=:id
    """), {"p": pages, "id": job["document_id"]})
    sync_db.commit()

# Heartbeat — keeps visibility timeout alive for slow PDFs

def _heartbeat(sqs, queue_url, receipt_handle, stop_evt):
    """Every ~4 min, extend visibility by another 5 min. Stops when stop_evt is set."""
    interval = max(60, VISIBILITY_SECONDS - 60)
    while not stop_evt.wait(interval):
        try:
            sqs.change_message_visibility(
                QueueUrl=queue_url,
                ReceiptHandle=receipt_handle,
                VisibilityTimeout=VISIBILITY_SECONDS,
            )
        except Exception:
            log.warning("heartbeat failed", exc_info=True)



# Message handler — idempotency + ack/retry semantics

def handle_message(sync_db, sqs, queue_url, msg):
    receipt = msg["ReceiptHandle"]
    job = json.loads(msg["Body"])
    log.info("picked up job=%s msg=%s", job["job_id"], msg["MessageId"])

    # Idempotency guard — SQS is at-least-once
    status = sync_db.execute(text(
        "SELECT status FROM ingestion_jobs WHERE id=:id"
    ), {"id": job["job_id"]}).scalar()

    if status == "COMPLETED":
        log.info("skip duplicate job=%s", job["job_id"])
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        return

    try:
        sync_db.execute(text(
            "UPDATE ingestion_jobs SET status='PROCESSING' WHERE id=:id"
        ), {"id": job["job_id"]})
        sync_db.commit()

        # Heartbeat while processing
        stop_evt = threading.Event()
        hb = threading.Thread(
            target=_heartbeat,
            args=(sqs, queue_url, receipt, stop_evt),
            daemon=True,
        )
        hb.start()

        try:
            process_document(sync_db, job)
        finally:
            stop_evt.set()

        sync_db.execute(text("""
            UPDATE ingestion_jobs
            SET status='COMPLETED', completed_at=NOW()
            WHERE id=:id
        """), {"id": job["job_id"]})
        sync_db.commit()

        # DELETE from SQS = ack
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt)
        log.info("done job=%s", job["job_id"])

    except Exception as e:
        log.exception("ingest failed job=%s", job["job_id"])
        sync_db.rollback()
        sync_db.execute(text("""
            UPDATE ingestion_jobs SET status='RETRY', last_error=:e WHERE id=:id
        """), {"e": str(e)[:500], "id": job["job_id"]})
        sync_db.commit()



# Main loop — replaces the Redis XREADGROUP + sweeper

def run_worker(sync_db) -> None:
    sqs = _sqs()
    queue_url = get_queue_url()
    log.info("worker started; polling %s", queue_url)

    while True:
        resp = sqs.receive_message(
            QueueUrl=queue_url,
            MaxNumberOfMessages=MAX_MESSAGES,
            WaitTimeSeconds=WAIT_SECONDS,
            VisibilityTimeout=VISIBILITY_SECONDS,
            AttributeNames=["ApproximateReceiveCount"],
        )
        for msg in resp.get("Messages", []):
            handle_message(sync_db, sqs, queue_url, msg)