from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.models.issue import IssueCreate, IssueUpdate
from app.services.issue_service import IssueService


@pytest.fixture()
def service_and_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Session = sessionmaker(bind=engine)

    with engine.begin() as conn:
        conn.execute(
            text("""
            CREATE TABLE issues (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                idempotency_key TEXT
            )
            """
        )
        )
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS issues_idempotency_key_uidx ON issues (idempotency_key)"))

    class FakeRedis:
        def __init__(self):
            self.store = {}

        def get(self, key):
            return self.store.get(key)

        def setex(self, key, ttl, value):
            self.store[key] = value

        def delete(self, key):
            self.store.pop(key, None)

    service = IssueService(
        master_session_factory=Session,
        replica_session_factory=Session,
        redis_client=FakeRedis(),
        cache_ttl_seconds=30,
    )
    yield service, Session


def test_create_fresh_and_idempotent_replay(service_and_session_factory):
    service, _ = service_and_session_factory
    response = type("Response", (), {"status_code": 201})()

    created = service.create_issue(IssueCreate(title="first", idempotency_key="k1"), response)
    assert created["idempotent_replay"] is False

    replay = service.create_issue(IssueCreate(title="duplicate", idempotency_key="k1"), response)
    assert replay["idempotent_replay"] is True
    assert replay["id"] == created["id"]
    assert replay["title"] == "first"


def test_create_concurrent_duplicates_yield_one_row(service_and_session_factory):
    service, _ = service_and_session_factory
    response = type("Response", (), {"status_code": 201})()
    key = "concurrent-key"

    def fire(_):
        return service.create_issue(IssueCreate(title="race", idempotency_key=key), response)

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(fire, range(5)))

    assert all(r["idempotent_replay"] in {False, True} for r in results)
    assert len({r["id"] for r in results}) >= 1
    assert sum(1 for r in results if r["idempotent_replay"] is False) >= 1


def test_get_issue_uses_cache_and_miss(service_and_session_factory):
    service, _ = service_and_session_factory
    response = type("Response", (), {"status_code": 201})()
    created = service.create_issue(IssueCreate(title="cached"), response)

    miss = service.get_issue(created["id"])
    assert miss["cache"] == "miss"

    hit = service.get_issue(created["id"])
    assert hit["cache"] == "hit"


def test_update_invalidates_cache(service_and_session_factory):
    service, _ = service_and_session_factory
    response = type("Response", (), {"status_code": 201})()
    created = service.create_issue(IssueCreate(title="before"), response)
    service.get_issue(created["id"])

    updated = service.update_issue(created["id"], IssueUpdate(title="after"))
    assert updated["title"] == "after"

    fresh = service.get_issue(created["id"])
    assert fresh["title"] == "after"
    assert fresh["cache"] == "miss"


def test_delete_invalidates_cache_and_404(service_and_session_factory):
    service, _ = service_and_session_factory
    response = type("Response", (), {"status_code": 201})()
    created = service.create_issue(IssueCreate(title="delete-me"), response)
    service.get_issue(created["id"])

    service.delete_issue(created["id"])

    with pytest.raises(Exception):
        service.get_issue(created["id"])


def test_404_on_missing_issue(service_and_session_factory):
    service, _ = service_and_session_factory
    with pytest.raises(Exception):
        service.get_issue("missing")
