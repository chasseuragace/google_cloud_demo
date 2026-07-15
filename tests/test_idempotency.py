"""
Claim under test: POST /issues with the same idempotency_key never creates
more than one row, even under concurrent duplicate requests (the classic
"double-click" or "client retried after a timeout" scenario) -- and the
second (and further) request(s) get back the original row, not an error.
"""
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests


def test_same_idempotency_key_creates_one_row_sequentially(lb_url):
    key = str(uuid.uuid4())

    r1 = requests.post(f"{lb_url}/issues", json={"title": "first", "idempotency_key": key}, timeout=5)
    assert r1.status_code == 201
    assert r1.json()["idempotent_replay"] is False
    original_id = r1.json()["id"]

    r2 = requests.post(f"{lb_url}/issues", json={"title": "duplicate-retry", "idempotency_key": key}, timeout=5)
    assert r2.status_code == 200, "Replayed request with a known key should not be treated as a fresh create"
    assert r2.json()["idempotent_replay"] is True
    assert r2.json()["id"] == original_id, "Replay must return the ORIGINAL row, not a new one"
    assert r2.json()["title"] == "first", "Replay must not overwrite the original row's data"


def test_concurrent_duplicate_requests_yield_exactly_one_row(lb_url, master_conn):
    """The real test: fire the same idempotency_key from many concurrent
    requests at once. A check-then-insert implementation would race and
    create duplicates here; an atomic ON CONFLICT upsert cannot."""
    key = str(uuid.uuid4())

    def fire(_):
        return requests.post(
            f"{lb_url}/issues",
            json={"title": "race", "idempotency_key": key},
            timeout=10,
        )

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = list(pool.map(fire, range(20)))

    assert all(r.status_code in (200, 201) for r in responses), (
        f"Unexpected status codes: {[r.status_code for r in responses]}"
    )

    ids = {r.json()["id"] for r in responses}
    assert len(ids) == 1, f"Expected exactly one distinct row, got {len(ids)}: {ids}"

    exactly_one_created = sum(1 for r in responses if r.json()["idempotent_replay"] is False)
    assert exactly_one_created == 1, (
        f"Expected exactly 1 of 20 concurrent requests to report a real "
        f"creation, got {exactly_one_created} -- duplicates were created."
    )

    with master_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM issues WHERE idempotency_key = %s", (key,))
        (row_count,) = cur.fetchone()
    assert row_count == 1, f"Database has {row_count} rows for this idempotency_key, expected 1"
