"""
Claims under test:

  1. "Requests are distributed to 3 workers" -- the LB isn't secretly always
     hitting the same one worker.
  2. Losing a worker doesn't take down the API -- the whole point of having
     multiple stateless workers behind a load balancer.

Each response from the app includes `handled_by: <worker_id>` specifically
so these tests can verify distribution from outside the system, the same
way you'd verify it against a real production load balancer.
"""
import subprocess
import time
from collections import Counter

import requests


def test_load_balancer_distributes_across_multiple_workers(lb_url):
    seen = Counter()
    for _ in range(60):
        r = requests.get(f"{lb_url}/health", timeout=5)
        assert r.status_code == 200
        seen[r.json()["worker_id"]] += 1

    assert len(seen) > 1, (
        f"All {sum(seen.values())} requests were handled by a single worker "
        f"({dict(seen)}) -- the load balancer is not actually distributing "
        f"traffic, it's just forwarding everything to one backend."
    )
    # With nginx's default round-robin, 60 requests across 3 workers should
    # come reasonably close to a 20/20/20 split -- not e.g. 58/1/1.
    counts = sorted(seen.values())
    assert counts[0] > 5, (
        f"Distribution is too skewed to call this real load balancing: {dict(seen)}"
    )


def test_api_survives_a_worker_going_down(lb_url):
    """Kill one worker container mid-run and confirm the API, as seen through
    the load balancer, keeps serving successfully. This is the actual
    payoff of horizontal scaling: you can lose a node without an outage.
    """
    project_dir = __file__.rsplit("/tests/", 1)[0]

    kill = subprocess.run(
        ["docker", "compose", "stop", "worker2"],
        cwd=project_dir, capture_output=True, text=True,
    )
    assert kill.returncode == 0, f"Failed to stop worker2 for the test: {kill.stderr}"

    try:
        time.sleep(2)  # give nginx a moment to notice failed upstream
        failures = 0
        for _ in range(30):
            try:
                r = requests.get(f"{lb_url}/health", timeout=5)
                if r.status_code != 200:
                    failures += 1
            except requests.RequestException:
                failures += 1

        assert failures <= 3, (
            f"{failures}/30 requests failed after taking down one worker -- "
            "the load balancer is not actually providing fault tolerance."
        )
    finally:
        restart = subprocess.run(
            ["docker", "compose", "start", "worker2"],
            cwd=project_dir, capture_output=True, text=True,
        )
        assert restart.returncode == 0, f"Failed to restart worker2: {restart.stderr}"
        # Give it a moment to come back healthy before the next test runs.
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if requests.get("http://localhost:8002/health", timeout=2).status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1)
