"""
Claim under test: adding workers behind a load balancer increases the
system's real request throughput, rather than just "sounding" scalable on
a diagram.

Method: fire the same number of concurrent requests (a) straight at a single
worker, bypassing the load balancer, and (b) through the load balancer
across all 3 workers. If horizontal scaling is real, (b) should complete
meaningfully faster / handle more requests per second than (a).

This is deliberately a load-shape comparison, not a hard absolute number --
absolute throughput depends on the laptop running it. The claim being
verified is *relative*: more workers => more throughput.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import requests

N_REQUESTS = 90
CONCURRENCY = 30


def _hammer(url, n_requests, concurrency):
    def one_request(_):
        t0 = time.time()
        r = requests.get(url, timeout=10)
        return r.status_code == 200, time.time() - t0

    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one_request, range(n_requests)))
    total_time = time.time() - start

    successes = sum(1 for ok, _ in results if ok)
    throughput = successes / total_time
    return throughput, successes


def test_seed_some_data(lb_url):
    """A handful of rows so /issues reads aren't trivially empty-table scans."""
    for i in range(20):
        r = requests.post(f"{lb_url}/issues", json={"title": f"seed-{i}"}, timeout=5)
        assert r.status_code == 201


def test_load_balanced_throughput_beats_single_worker(lb_url, worker_urls):
    single_worker_url = f"{worker_urls['worker1']}/issues"
    lb_throughput_url = f"{lb_url}/issues"

    single_throughput, single_ok = _hammer(single_worker_url, N_REQUESTS, CONCURRENCY)
    lb_throughput, lb_ok = _hammer(lb_throughput_url, N_REQUESTS, CONCURRENCY)

    assert single_ok == N_REQUESTS, f"Single-worker run had failures: {single_ok}/{N_REQUESTS}"
    assert lb_ok == N_REQUESTS, f"Load-balanced run had failures: {lb_ok}/{N_REQUESTS}"

    print(
        f"\nSingle worker throughput: {single_throughput:.1f} req/s | "
        f"Load-balanced (3 workers) throughput: {lb_throughput:.1f} req/s"
    )

    # We're not asserting a full 3x -- Postgres and Docker networking are
    # shared bottlenecks, and this is a laptop, not production hardware.
    # But if horizontal scaling is doing anything real, distributing the
    # same request volume across 3 workers should beat one worker by a
    # clear margin, not be roughly equal or worse.
    assert lb_throughput > single_throughput * 1.15, (
        f"Load-balanced throughput ({lb_throughput:.1f} req/s) was not "
        f"meaningfully higher than single-worker throughput "
        f"({single_throughput:.1f} req/s) -- horizontal scaling isn't "
        f"actually buying you anything in this setup."
    )
