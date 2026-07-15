from pydantic import BaseModel


class IssueCreate(BaseModel):
    title: str
    status: str = "open"
    idempotency_key: str | None = None


class IssueUpdate(BaseModel):
    title: str | None = None
    status: str | None = None


class IssueRead(BaseModel):
    id: str
    title: str
    status: str
    created_at: str | None = None
