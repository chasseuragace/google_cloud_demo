"""
The "before" architecture: one FastAPI process, one Postgres instance,
no read replica, no shared cache, no load balancer. Same CRUD surface as
the scalable version, so a load test comparison is apples-to-apples on
behavior -- the only variable being compared is the architecture.
"""
import os
import time
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL, pool_size=5, pool_pre_ping=True)
Session = sessionmaker(bind=engine)

app = FastAPI(title="Issues API (Monolith)")


def init_schema():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS issues (
                id UUID PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """))


class IssueCreate(BaseModel):
    title: str
    status: str = "open"


class IssueUpdate(BaseModel):
    title: str | None = None
    status: str | None = None


@app.on_event("startup")
def on_startup():
    for _ in range(30):
        try:
            init_schema()
            return
        except Exception:
            time.sleep(1)
    init_schema()


@app.get("/health")
def health():
    return {"worker_id": "monolith", "status": "ok"}


@app.post("/issues", status_code=201)
def create_issue(payload: IssueCreate):
    issue_id = str(uuid.uuid4())
    with Session() as session:
        session.execute(
            text("INSERT INTO issues (id, title, status) VALUES (:id, :title, :status)"),
            {"id": issue_id, "title": payload.title, "status": payload.status},
        )
        session.commit()
    return {"id": issue_id, "title": payload.title, "status": payload.status, "handled_by": "monolith"}


@app.get("/issues")
def list_issues():
    with Session() as session:
        rows = session.execute(text("SELECT id, title, status, created_at FROM issues ORDER BY created_at")).mappings().all()
    return {"issues": [dict(r) for r in rows], "handled_by": "monolith"}


@app.get("/issues/{issue_id}")
def get_issue(issue_id: str):
    with Session() as session:
        row = session.execute(
            text("SELECT id, title, status, created_at FROM issues WHERE id = :id"),
            {"id": issue_id},
        ).mappings().first()
    if not row:
        raise HTTPException(404, "Issue not found")
    return {**dict(row), "handled_by": "monolith"}


@app.put("/issues/{issue_id}")
def update_issue(issue_id: str, payload: IssueUpdate):
    fields = {k: v for k, v in payload.dict().items() if v is not None}
    if not fields:
        raise HTTPException(400, "No fields to update")
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    with Session() as session:
        result = session.execute(
            text(f"UPDATE issues SET {set_clause} WHERE id = :id"),
            {**fields, "id": issue_id},
        )
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Issue not found")
    return {"id": issue_id, **fields, "handled_by": "monolith"}


@app.delete("/issues/{issue_id}", status_code=204)
def delete_issue(issue_id: str):
    with Session() as session:
        result = session.execute(text("DELETE FROM issues WHERE id = :id"), {"id": issue_id})
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(404, "Issue not found")
    return None
