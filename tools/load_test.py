"""
Deliberately simple load test. It does not try to be k6 or Locust -- it's a
fixed-duration, fixed-concurrency worker pool hammering a realistic
read-heavy mix (80% reads of individual issues, 20% writes), which is
representative of an issue tracker's actual traffic shape.

It reports only the key indicators, on purpose:
  - throughput (successful requests / second)
  - p50 / p95 / p99 latency (ms)
  - error rate

Usage:
    python3 load_test.py --url http://localhost:8080 --label scalable \
        --duration 20 --concurrency 40 --out results_scalable.json
"""
import argparse
import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

READ_WEIGHT = 0.8  # 80% reads, 20% writes -- typical issue-tracker traffic shape
SEED_COUNT = 30


def seed_issues(base_url, count=SEED_COUNT):
    ids = []
    for i in range(count):
        r = requests.post(f"{base_url}/issues", json={"title": f"seed-{i}"}, timeout=10)
        r.raise_for_status()
        ids.append(r.json()["id"])
    return ids


def worker_loop(base_url, seeded_ids, stop_at, latencies_ms, lock, counters):
    while time.time() < stop_at:
        is_read = random.random() < READ_WEIGHT
        t0 = time.time()
        try:
            if is_read:
                issue_id = random.choice(seeded_ids)
                r = requests.get(f"{base_url}/issues/{issue_id}", timeout=10)
            else:
                r = requests.post(f"{base_url}/issues", json={"title": "load-test-write"}, timeout=10)
            ok = r.status_code in (200, 201)
        except requests.RequestException:
            ok = False

        elapsed_ms = (time.time() - t0) * 1000

        with lock:
            counters["total"] += 1
            if ok:
                counters["success"] += 1
                latencies_ms.append(elapsed_ms)
            else:
                counters["errors"] += 1


def percentile(sorted_values, pct):
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * pct
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def run(base_url, label, duration, concurrency, out_path):
    print(f"[{label}] Waiting for {base_url}/health ...")
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            if requests.get(f"{base_url}/health", timeout=2).status_code == 200:
                break
        except requests.RequestException:
            pass
        time.sleep(1)
    else:
        raise RuntimeError(f"{base_url} never became healthy")

    print(f"[{label}] Seeding {SEED_COUNT} issues...")
    seeded_ids = seed_issues(base_url)

    print(f"[{label}] Running load test: {duration}s at concurrency {concurrency}...")
    latencies_ms = []
    lock = threading.Lock()
    counters = {"total": 0, "success": 0, "errors": 0}

    stop_at = time.time() + duration
    start = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(worker_loop, base_url, seeded_ids, stop_at, latencies_ms, lock, counters)
            for _ in range(concurrency)
        ]
        for f in futures:
            f.result()
    actual_duration = time.time() - start

    sorted_latencies = sorted(latencies_ms)
    result = {
        "label": label,
        "url": base_url,
        "duration_s": round(actual_duration, 2),
        "concurrency": concurrency,
        "total_requests": counters["total"],
        "successful_requests": counters["success"],
        "errors": counters["errors"],
        "error_rate_pct": round(100 * counters["errors"] / counters["total"], 2) if counters["total"] else None,
        "throughput_rps": round(counters["success"] / actual_duration, 2),
        "p50_ms": round(percentile(sorted_latencies, 0.50), 1) if sorted_latencies else None,
        "p95_ms": round(percentile(sorted_latencies, 0.95), 1) if sorted_latencies else None,
        "p99_ms": round(percentile(sorted_latencies, 0.99), 1) if sorted_latencies else None,
        "avg_ms": round(sum(sorted_latencies) / len(sorted_latencies), 1) if sorted_latencies else None,
    }

    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[{label}] Done. Results written to {out_path}")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8080")
    parser.add_argument("--label", required=True, help="e.g. 'scalable' or 'monolith'")
    parser.add_argument("--duration", type=int, default=20, help="seconds")
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--out", required=True, help="path to write JSON results")
    args = parser.parse_args()

    run(args.url, args.label, args.duration, args.concurrency, args.out)
