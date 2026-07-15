# Scalability Demo: Issues CRUD API

A minimal FastAPI CRUD app behind an Nginx load balancer, backed by a
**real** PostgreSQL master + streaming-replication replica -- unlike the
original architecture doc's `docker-compose.yml`, which named a replica
but never actually configured replication (two independent blank databases).

This project fixes that, and ships a test suite that checks the
*scalability claims themselves* (replication, load distribution, fault
tolerance, throughput scaling) rather than basic CRUD correctness.

## Prerequisites

- Docker Desktop running on your Mac
- Python 3.9+ (for running the test suite from the host)

## 1. Start the stack

```bash
docker compose up -d --build
```

This starts:
- `postgres_master` (port 5433 on host)
- `postgres_replica` (port 5434 on host) -- clones the master via
  `pg_basebackup` on first boot, then streams changes continuously
- `worker1` / `worker2` / `worker3` (ports 8001-8003 on host, for
  bypassing the LB in tests)
- `loadbalancer` (nginx, port 8080 on host) -- the actual entrypoint

Give it ~15-20 seconds on first run for the replica to finish cloning.
Check with:

```bash
docker compose logs -f postgres_replica
```

You should see `pg_basebackup` output, then normal Postgres startup logs.

## 2. Try the API

```bash
curl -X POST localhost:8080/issues -H 'Content-Type: application/json' \
  -d '{"title": "Login button broken"}'

curl localhost:8080/issues
```

Note the `"handled_by"` field in every response -- that's which worker
container served the request, useful for eyeballing load distribution.

## 3. Run the scalability test suite

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r tests/requirements.txt
pytest tests/ -v -s
```

## What the tests actually check

| File | Claim being verified |
|---|---|
| `test_replication.py` | Writes to Master really do propagate to Replica (measured, not assumed); Replica genuinely runs in Postgres hot-standby/recovery mode; Replica rejects direct writes *because it's a replica*, not by app-level convention |
| `test_load_balancing.py` | Nginx actually spreads requests across all 3 workers (not silently pinned to one); the API keeps serving successfully when one worker is killed |
| `test_throughput_scaling.py` | Hitting the system through the load balancer (3 workers) yields meaningfully higher throughput under concurrent load than hitting a single worker directly |

None of these tests check "does POST return 201" -- that's trivial CRUD
correctness and would pass or fail the same way on a single-machine,
non-replicated, non-load-balanced setup. These tests are specifically
designed to fail if the *scalability infrastructure* is fake or misconfigured
(as the original doc's compose file was).

## Google Cloud Run preparation (no credentials required)

This branch is intentionally focused on understanding the difference between the current Docker/Nginx model and a Cloud Run deployment model. No Google Cloud credentials or account are required to follow along.

### What changes when moving to Cloud Run?

With the current Docker Compose setup:
- Nginx is the explicit entrypoint.
- The upstream pool contains three fixed workers: `worker1`, `worker2`, and `worker3`.
- You manually decide how requests are routed and which services are available.

With Cloud Run:
- You deploy a single service instead of managing a fixed worker pool.
- Google handles request distribution across dynamically created instances.
- You do not need to manage `worker1/worker2/worker3` in your own config.
- The app should be stateless and rely on shared services such as Cloud SQL and Memorystore/Redis.

### What changed in this repository for that preparation?

- The container startup now honors a `PORT` environment variable so it can work in Cloud Run-style environments.
- The app accepts both the existing `DATABASE_MASTER_URL` / `DATABASE_REPLICA_URL` values and cloud-style `DATABASE_URL` / `DATABASE_URL_READ` values.
- A Cloud Run deployment template and a deployment script stub are included for later use with real credentials.
- The app is still compatible with the existing local Docker Compose flow.

### Files added for the cloud-prep branch

- [cloudbuild.yaml](cloudbuild.yaml) – a Google Cloud Build template for building and deploying the service.
- [scripts/deploy-cloudrun.sh](scripts/deploy-cloudrun.sh) – a shell template showing the deployment flow.
- [.gcloudignore](.gcloudignore) – a cloud-build-friendly ignore file for lighter uploads.
- [docs/cloud-run-prep.md](docs/cloud-run-prep.md) – a concise explanation of the migration path from manual workers to managed Cloud Run instances.

### What you would do later with real Cloud Run credentials

In a real Cloud Run setup, you would typically:
1. Build and push the image to Artifact Registry.
2. Deploy the service with `gcloud run deploy`.
3. Configure environment variables for the database and Redis endpoints.
4. Enable autoscaling and set memory/CPU limits.

For now, the goal is to understand the architecture shift rather than actually deploy anything.

## Tear down

```bash
docker compose down -v
```

## Shared Redis cache

`GET /issues/{id}` now checks a shared Redis cache before hitting the
replica (`"cache": "hit"` or `"miss"` in the response), with a 30s TTL.
Writes (`PUT`/`DELETE`) invalidate the cache entry. Because it's Redis
(one shared instance) rather than an in-process dict, a cache entry
populated by a read on `worker1` is immediately visible on `worker2` and
`worker3` -- `tests/test_cache.py` verifies exactly that, plus that
invalidation propagates across workers on update.

## Monolith vs. Scalable: load test comparison

`monolith/` is a deliberately minimal "before" architecture: one FastAPI
process, one Postgres instance, no replica, no cache, no load balancer --
same CRUD behavior as the scalable app, so the comparison isolates
architecture rather than functionality.

Because both stacks are resource-heavy to run at once on a single laptop,
the comparison is **two sequential phases on the same machine**, not a
simultaneous side-by-side:

```bash
chmod +x tools/run_comparison.sh
./tools/run_comparison.sh          # defaults: 20s duration, concurrency 40
# or override: ./tools/run_comparison.sh 30 60
```

This will:
1. Bring up the scalable stack, run a fixed-duration load test
   (80% reads of individual issues / 20% writes -- a realistic issue-tracker
   traffic shape), capture results to `results_scalable.json`, tear down.
2. Bring up the monolith, run the *same* load test against the *same* URL
   (`localhost:8080` in both phases), capture to `results_monolith.json`,
   tear down.
3. Generate `comparison_report.md` -- a table over the key indicators only:

   | Metric | Meaning |
   |---|---|
   | Throughput (req/s) | successful requests per second under sustained concurrent load |
   | p50 / p95 / p99 latency | response time distribution, not just the average |
   | Error rate | % of requests that failed or timed out |

You can also run each phase manually if you want more control:

```bash
docker compose up -d --build
python3 tools/load_test.py --url http://localhost:8080 --label scalable --out results_scalable.json
docker compose down -v

docker compose -f docker-compose.monolith.yml up -d --build
python3 tools/load_test.py --url http://localhost:8080 --label monolith --out results_monolith.json
docker compose -f docker-compose.monolith.yml down -v

python3 tools/compare_report.py results_scalable.json results_monolith.json
```

**What this test is (and isn't) proving:** it isolates *architecture*,
not raw hardware -- both runs happen sequentially on the same machine. It
should show the scalable stack's advantage coming from three things
working together: multiple workers absorbing concurrent load, the read
replica taking read traffic off the write path, and Redis serving warm
reads without touching Postgres at all. If any of those aren't actually
buying you anything, the numbers will show it -- that's the point of
measuring instead of assuming.
