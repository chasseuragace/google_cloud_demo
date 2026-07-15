"""
Simple Issues CRUD API demonstrating explicit read/write database splitting.

- Writes (POST/PUT/DELETE) go to the Master.
- Reads (GET) go to a Replica.
- The worker's identity (hostname) is exposed on every response so we can
  prove, from the outside, that the load balancer really is spreading
  traffic across multiple worker processes.
"""
import json
import os
import socket
import time
import uuid

import redis
from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

MASTER_URL = os.environ["DATABASE_MASTER_URL"]
REPLICA_URL = os.environ["DATABASE_REPLICA_URL"]
REDIS_URL = os.environ.get("REDIS_URL")  # unset in the monolith build
WORKER_ID = os.environ.get("WORKER_ID", socket.gethostname())
CACHE_TTL_SECONDS = 30

master_engine = create_engine(MASTER_URL, pool_size=5, pool_pre_ping=True)
replica_engine = create_engine(REPLICA_URL, pool_size=10, pool_pre_ping=True)

MasterSession = sessionmaker(bind=master_engine)
ReplicaSession = sessionmaker(bind=replica_engine)

redis_client = redis.from_url(REDIS_URL, decode_responses=True) if REDIS_URL else None

app = FastAPI(title="Issues API")


def _cache_key(issue_id: str) -> str:
    return f"issue:{issue_id}"


def _cache_invalidate(issue_id: str):
    if redis_client:
        redis_client.delete(_cache_key(issue_id))


def init_schema():
    """Create the table on the Master. Replica gets it via streaming replication."""
    with master_engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS issues (
                id UUID PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                idempotency_key TEXT
            )
        """))
        # Postgres unique indexes treat NULLs as distinct from each other, so
        # rows created without an idempotency_key never collide with one
        # another -- only two requests reusing the SAME key can conflict.
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS issues_idempotency_key_uidx
            ON issues (idempotency_key)
        """))


class IssueCreate(BaseModel):
    title: str
    status: str = "open"
    idempotency_key: str | None = None


class IssueUpdate(BaseModel):
    title: str | None = None
    status: str | None = None


@app.on_event("startup")
def on_startup():
    # Small retry loop since the DB container may still be booting.
    for _ in range(30):
        try:
            init_schema()
            return
        except Exception:
            time.sleep(1)
    init_schema()


@app.get("/health")
def health():
    return {"worker_id": WORKER_ID, "status": "ok"}


@app.post("/issues", status_code=201)
def create_issue(payload: IssueCreate, response: Response):
    key = payload.idempotency_key

    if key is None:
        # No idempotency key supplied -- behaves as a plain insert, same as before.
        issue_id = str(uuid.uuid4())
        with MasterSession() as session:
            session.execute(
                text("INSERT INTO issues (id, title, status) VALUES (:id, :title, :status)"),
                {"id": issue_id, "title": payload.title, "status": payload.status},
            )
            session.commit()
        return {"id": issue_id, "title": payload.title, "status": payload.status, "handled_by": WORKER_ID}

    issue_id = str(uuid.uuid4())
    max_attempts = 3
    last_error = None

    for attempt in range(max_attempts):
        try:
            with MasterSession() as session:
                # Atomic upsert: either this request wins the insert, or it
                # silently no-ops because another request already used this
                # key. Either way, one round trip decides the outcome --
                # there's no window between a "check" and an "insert" for a
                # concurrent duplicate request to sneak through.
                inserted = session.execute(
                    text("""
                        INSERT INTO issues (id, title, status, idempotency_key)
                        VALUES (:id, :title, :status, :key)
                        ON CONFLICT (idempotency_key) DO NOTHING
                        RETURNING id, title, status
                    """),
                    {"id": issue_id, "title": payload.title, "status": payload.status, "key": key},
                ).mappings().first()
                session.commit()

                if inserted is not None:
                    # We created it.
                    return {**dict(inserted), "handled_by": WORKER_ID, "idempotent_replay": False}

                # Conflict: some request (possibly this one, retried after a
                # dropped response) already created a row for this key.
                # Return that existing row instead of erroring.
                existing = session.execute(
                    text("SELECT id, title, status FROM issues WHERE idempotency_key = :key"),
                    {"key": key},
                ).mappings().first()
                response.status_code = 200
                return {**dict(existing), "handled_by": WORKER_ID, "idempotent_replay": True}

        except OperationalError as e:
            # Transient errors (connection drop, deadlock, etc.) -- retry
            # with backoff. The upsert is safe to retry since it's atomic:
            # retrying never creates a second row for the same key.
            last_error = e
            if attempt < max_attempts - 1:
                time.sleep(0.1 * (2 ** attempt))
                continue
            raise

    raise last_error


@app.get("/issues")
def list_issues():
    with ReplicaSession() as session:
        rows = session.execute(text("SELECT id, title, status, created_at FROM issues ORDER BY created_at")).mappings().all()
    return {"issues": [dict(r) for r in rows], "handled_by": WORKER_ID}


@app.get("/issues/{issue_id}")
def get_issue(issue_id: str):
    if redis_client:
        cached = redis_client.get(_cache_key(issue_id))
        if cached:
            return {**json.loads(cached), "handled_by": WORKER_ID, "cache": "hit"}

    with ReplicaSession() as session:
        row = session.execute(
            text("SELECT id, title, status, created_at FROM issues WHERE id = :id"),
            {"id": issue_id},
        ).mappings().first()
    if not row:
        raise HTTPException(404, "Issue not found")

    result = dict(row)
    result["created_at"] = str(result["created_at"])
    if redis_client:
        redis_client.setex(_cache_key(issue_id), CACHE_TTL_SECONDS, json.dumps(result))

    return {**result, "handled_by": WORKER_ID, "cache": "miss"}


@app.put("/issues/{issue_id}")
def update_issue(issue_id: str, payload: IssueUpdate):
    fields = {k: v for k, v in payload.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    with MasterSession() as session:
        result = session.execute(
            text(f"UPDATE issues SET {set_clause} WHERE id = :id"),
            {**fields, "id": issue_id},
        )
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Issue not found")
    _cache_invalidate(issue_id)
    return {"id": issue_id, **fields, "handled_by": WORKER_ID}


@app.delete("/issues/{issue_id}", status_code=204)
def delete_issue(issue_id: str):
    with MasterSession() as session:
        result = session.execute(text("DELETE FROM issues WHERE id = :id"), {"id": issue_id})
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Issue not found")
    _cache_invalidate(issue_id)
    return None
