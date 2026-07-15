import logging
import time

from sqlalchemy import text

from app.db.session import master_engine

logger = logging.getLogger(__name__)


def init_schema() -> None:
    """Create the table on the Master. Replica gets it via streaming replication."""
    dialect = master_engine.dialect.name
    if dialect == "postgresql":
        ddl = """
            CREATE TABLE IF NOT EXISTS issues (
                id UUID PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                idempotency_key TEXT
            )
        """
    else:
        ddl = """
            CREATE TABLE IF NOT EXISTS issues (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                idempotency_key TEXT
            )
        """
    with master_engine.begin() as conn:
        conn.execute(text(ddl))
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS issues_idempotency_key_uidx
            ON issues (idempotency_key)
        """))


def init_schema_with_retry(max_attempts: int = 30, delay_seconds: float = 1.0) -> None:
    for attempt in range(max_attempts):
        try:
            init_schema()
            return
        except Exception as exc:
            if attempt == max_attempts - 1:
                logger.exception("Schema initialization failed after retries")
                raise
            logger.warning("Schema initialization attempt %s failed: %s", attempt + 1, exc)
            time.sleep(delay_seconds)
