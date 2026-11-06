import json
import logging
import uuid
from sqlalchemy import text
from academic_ai.ingestion.queue import _sqs, get_queue_url

log = logging.getLogger(__name__)


async def enqueue_ingestion_job(db, *, document_id, user_id, workspace_id, s3_key) -> str:

    job_id = str(uuid.uuid4())

    # 1. Ledger
    await db.execute(text("""
        INSERT INTO ingestion_jobs (id, document_id, status, retry_count, max_retries)
        VALUES (:id, :doc, 'PENDING', 0, :max_retries)
    """), {
        "id": job_id,
        "doc": str(document_id),
        "max_retries": 5,
    })

    # 2. SQS pointer
    resp = _sqs().send_message(
        QueueUrl=get_queue_url(),
        MessageBody=json.dumps({
            "job_id":       job_id,
            "document_id":  str(document_id),
            "user_id":      str(user_id),
            "workspace_id": str(workspace_id),
            "s3_key":       s3_key,
        }),
    )

    # Store the SQS MessageId for debugging / tracing
    await db.execute(text(
        "UPDATE ingestion_jobs SET stream_message_id = :m WHERE id = :id"
    ), {"m": resp["MessageId"], "id": job_id})
    await db.commit()

    log.info("enqueued job=%s msg=%s", job_id, resp["MessageId"])
    return job_id