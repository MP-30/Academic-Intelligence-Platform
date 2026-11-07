import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from academic_ai.config import settings
from academic_ai.ingestion.worker import run_worker

logger = logging.getLogger(__name__)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# Sync engine — SQS polling loop is blocking, async adds no value here
sync_url = settings.database_url.replace("+asyncpg", "+psycopg")
engine = create_engine(sync_url, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
db = Session()

try:
    run_worker(db)
except KeyboardInterrupt:
    logger.info("worker stopped by user")
finally:
    db.close()
