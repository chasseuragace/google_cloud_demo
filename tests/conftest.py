import time
import subprocess

import psycopg2
import pytest
import requests

LB_URL = "http://localhost:8080"
WORKER_URLS = {
    "worker1": "http://localhost:8001",
    "worker2": "http://localhost:8002",
    "worker3": "http://localhost:8003",
}
MASTER_DSN = "dbname=issues user=postgres password=password host=localhost port=5433"
REPLICA_DSN = "dbname=issues user=postgres password=password host=localhost port=5434"


def _wait_for(url, timeout=60):
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            r = requests.get(url, timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException as e:
            last_err = e
        time.sleep(1)
    raise RuntimeError(f"{url} never became healthy: {last_err}")


@pytest.fixture(scope="session", autouse=True)
def wait_for_stack():
    """
    Every test in this suite assumes `docker compose up -d` has already been
    run (see README). We just wait for things to be reachable rather than
    starting/stopping compose ourselves, so tests stay fast to re-run.
    """
    _wait_for(f"{LB_URL}/health")
    for url in WORKER_URLS.values():
        _wait_for(f"{url}/health")


@pytest.fixture
def lb_url():
    return LB_URL


@pytest.fixture
def worker_urls():
    return WORKER_URLS


@pytest.fixture
def master_conn():
    conn = psycopg2.connect(MASTER_DSN)
    yield conn
    conn.close()


@pytest.fixture
def replica_conn():
    conn = psycopg2.connect(REPLICA_DSN)
    yield conn
    conn.close()


def docker_compose(*args):
    return subprocess.run(
        ["docker", "compose", *args],
        cwd=__file__.rsplit("/tests/", 1)[0],
        capture_output=True,
        text=True,
    )
