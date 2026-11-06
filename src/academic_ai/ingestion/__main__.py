import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from academic_ai.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

# Sync engine — SQS polling loop is blocking, async adds no value here

sync_url = settings.database_url.replace("+asyncpg", "+psycopg")

engine = create_engine(sync_url, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
db = Session()

from academic_ai.ingestion.worker import run_worker

try:
    run_worker(db)
except KeyboardInterrupt:
    logging.info("worker stopped by user")
finally:
    db.close()