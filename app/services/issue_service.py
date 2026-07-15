import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.models.issue import IssueCreate, IssueUpdate

logger = logging.getLogger(__name__)


class IssueService:
    def __init__(self, master_session_factory, replica_session_factory, redis_client=None, cache_ttl_seconds: int | None = None):
        self.master_session_factory = master_session_factory
        self.replica_session_factory = replica_session_factory
        self.redis_client = redis_client
        self.cache_ttl_seconds = cache_ttl_seconds or settings.cache_ttl_seconds
        self.worker_id = settings.worker_id

    def _cache_key(self, issue_id: str) -> str:
        return f"issue:{issue_id}"

    def _list_cache_key(self) -> str:
        return "issues:list"

    def _serialize_value(self, value: Any) -> Any:
        if isinstance(value, (datetime,)):
            return value.isoformat()
        if hasattr(value, "hex") and value.__class__.__name__ == "UUID":
            return str(value)
        return value

    def _normalize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {k: self._serialize_value(v) for k, v in row.items()}

    def _cache_invalidate(self, issue_id: str) -> None:
        if self.redis_client:
            self.redis_client.delete(self._cache_key(issue_id))

    def _cache_invalidate_list(self) -> None:
        if self.redis_client:
            self.redis_client.delete(self._list_cache_key())

    def create_issue(self, payload: IssueCreate, response) -> dict[str, Any]:
        key = payload.idempotency_key

        if key is None:
            issue_id = str(uuid.uuid4())
            with self.master_session_factory() as session:
                session.execute(
                    text("INSERT INTO issues (id, title, status) VALUES (:id, :title, :status)"),
                    {"id": issue_id, "title": payload.title, "status": payload.status},
                )
                session.commit()
            self._cache_invalidate_list()
            return {"id": issue_id, "title": payload.title, "status": payload.status, "handled_by": self.worker_id}

        issue_id = str(uuid.uuid4())
        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                with self.master_session_factory() as session:
                    dialect_name = session.bind.dialect.name
                    if dialect_name == "postgresql":
                        inserted = session.execute(
                            text("""
                                INSERT INTO issues (id, title, status, idempotency_key)
                                VALUES (:id, :title, :status, :key)
                                ON CONFLICT (idempotency_key) DO NOTHING
                                RETURNING id, title, status
                            """),
                            {"id": issue_id, "title": payload.title, "status": payload.status, "key": key},
                        ).mappings().first()
                    else:
                        try:
                            session.execute(
                                text("""
                                    INSERT INTO issues (id, title, status, idempotency_key)
                                    VALUES (:id, :title, :status, :key)
                                """),
                                {"id": issue_id, "title": payload.title, "status": payload.status, "key": key},
                            )
                            inserted = {"id": issue_id, "title": payload.title, "status": payload.status}
                        except Exception:
                            inserted = None
                    session.commit()

                    existing = session.execute(
                        text(f"SELECT id, title, status FROM issues WHERE idempotency_key = '{key}'"),
                    ).mappings().first()

                    if inserted is not None:
                        logger.info("Idempotency create created issue %s for key %s", inserted["id"], key)
                        self._cache_invalidate_list()
                        return {**dict(inserted), "handled_by": self.worker_id, "idempotent_replay": False}

                    if existing is not None:
                        response.status_code = 200
                        logger.info("Idempotency replay for key %s returning existing issue %s", key, existing["id"])
                        return {**dict(existing), "handled_by": self.worker_id, "idempotent_replay": True}

                    response.status_code = 200
                    logger.info("Idempotency replay for key %s returning existing issue %s", key, existing["id"])
                    return {**dict(existing), "handled_by": self.worker_id, "idempotent_replay": True}
            except OperationalError as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    logger.warning("Retrying idempotent create for key %s after OperationalError: %s", key, exc)
                    time.sleep(0.1 * (2 ** attempt))
                    continue
                raise

        raise last_error

    def list_issues(self) -> dict[str, Any]:
        if self.redis_client:
            cached = self.redis_client.get(self._list_cache_key())
            if cached:
                logger.info("List cache hit")
                return {"issues": json.loads(cached), "handled_by": self.worker_id}

        with self.replica_session_factory() as session:
            rows = session.execute(text("SELECT id, title, status, created_at FROM issues ORDER BY created_at")).mappings().all()
        issues = [self._normalize_row(dict(r)) for r in rows]
        if self.redis_client:
            self.redis_client.setex(self._list_cache_key(), self.cache_ttl_seconds, json.dumps(issues))
        return {"issues": issues, "handled_by": self.worker_id}

    def get_issue(self, issue_id: str) -> dict[str, Any]:
        if self.redis_client:
            cached = self.redis_client.get(self._cache_key(issue_id))
            if cached:
                logger.info("Cache hit for issue %s", issue_id)
                return {**json.loads(cached), "handled_by": self.worker_id, "cache": "hit"}
            logger.info("Cache miss for issue %s", issue_id)

        with self.replica_session_factory() as session:
            row = session.execute(
                text("SELECT id, title, status, created_at FROM issues WHERE id = :id"),
                {"id": issue_id},
            ).mappings().first()
        if not row:
            raise HTTPException(404, "Issue not found")

        result = self._normalize_row(dict(row))
        if self.redis_client:
            self.redis_client.setex(self._cache_key(issue_id), self.cache_ttl_seconds, json.dumps(result))

        return {**result, "handled_by": self.worker_id, "cache": "miss"}

    def update_issue(self, issue_id: str, payload: IssueUpdate) -> dict[str, Any]:
        fields = {k: v for k, v in payload.dict().items() if v is not None}
        if not fields:
            raise HTTPException(400, "No fields to update")
        set_clause = ", ".join(f"{k} = :{k}" for k in fields)
        with self.master_session_factory() as session:
            result = session.execute(
                text(f"UPDATE issues SET {set_clause} WHERE id = :id"),
                {**fields, "id": issue_id},
            )
            session.commit()
            if result.rowcount == 0:
                raise HTTPException(404, "Issue not found")
        self._cache_invalidate(issue_id)
        self._cache_invalidate_list()
        return {"id": issue_id, **fields, "handled_by": self.worker_id}

    def delete_issue(self, issue_id: str) -> None:
        with self.master_session_factory() as session:
            result = session.execute(text("DELETE FROM issues WHERE id = :id"), {"id": issue_id})
            session.commit()
            if result.rowcount == 0:
                raise HTTPException(404, "Issue not found")
        self._cache_invalidate(issue_id)
