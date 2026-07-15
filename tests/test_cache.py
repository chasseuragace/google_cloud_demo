"""
Claim under test: the cache is a *shared* cache (Redis), so a cache entry
populated by a read on one worker is visible to every other worker --
not a per-process in-memory dict that would silently give each worker its
own inconsistent cache.
"""
import requests


def test_cache_hit_on_worker1_is_visible_on_worker3(worker_urls):
    create = requests.post(f"{worker_urls['worker1']}/issues", json={"title": "cache-check"}, timeout=5)
    assert create.status_code == 201
    issue_id = create.json()["id"]

    # First read on worker1: populates the shared cache (a DB read, "miss").
    r1 = requests.get(f"{worker_urls['worker1']}/issues/{issue_id}", timeout=5)
    assert r1.status_code == 200
    assert r1.json()["cache"] == "miss"

    # Reading the SAME issue via a DIFFERENT worker should now be a cache
    # HIT -- only possible if the cache is actually shared (Redis), not an
    # in-process dict local to worker1.
    r2 = requests.get(f"{worker_urls['worker3']}/issues/{issue_id}", timeout=5)
    assert r2.status_code == 200
    assert r2.json()["cache"] == "hit", (
        "Expected worker3 to see a cache hit populated by worker1 -- if "
        "this is 'miss', the cache is not actually shared across workers."
    )


def test_cache_is_invalidated_on_update_across_workers(worker_urls):
    create = requests.post(f"{worker_urls['worker2']}/issues", json={"title": "before-update"}, timeout=5)
    issue_id = create.json()["id"]

    # Warm the cache via worker2.
    requests.get(f"{worker_urls['worker2']}/issues/{issue_id}", timeout=5)

    # Update via a different worker (worker1) -- must invalidate the shared entry.
    upd = requests.put(f"{worker_urls['worker1']}/issues/{issue_id}", json={"title": "after-update"}, timeout=5)
    assert upd.status_code == 200

    # Reading via worker3 must reflect the update, not stale cached data.
    r = requests.get(f"{worker_urls['worker3']}/issues/{issue_id}", timeout=5)
    assert r.json()["title"] == "after-update", (
        "Stale cached value served after an update on a different worker -- "
        "cache invalidation is not propagating across the shared cache."
    )
