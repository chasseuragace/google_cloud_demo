"""
Claims under test (from the original architecture doc):

  1. "Replicas are exact copies that sync automatically from the Master."
  2. "Replicas handle reads... only the Master handles writes."
  3. Attempting INSERT/UPDATE/DELETE directly against a replica is denied
     BY THE DATABASE because it is a replica -- not merely "happens to work
     since nobody built write logic for it."

These are NOT "does the CRUD endpoint work" tests. They connect straight to
Postgres, bypassing the FastAPI app entirely, so a bug in application code
can't fake a passing result.
"""
import time
import uuid

import psycopg2
import pytest


def test_write_on_master_propagates_to_replica(master_conn, replica_conn):
    """A row inserted on the Master must eventually appear when read from
    the Replica, with no application code involved -- this is Postgres's
    own streaming replication doing the work."""
    issue_id = str(uuid.uuid4())
    title = f"repl-check-{issue_id}"

    with master_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO issues (id, title, status) VALUES (%s, %s, 'open')",
            (issue_id, title),
        )
        master_conn.commit()

    deadline = time.time() + 10
    found = False
    while time.time() < deadline:
        with replica_conn.cursor() as cur:
            cur.execute("SELECT title FROM issues WHERE id = %s", (issue_id,))
            row = cur.fetchone()
        if row is not None:
            found = True
            break
        replica_conn.rollback()  # refresh snapshot before next poll
        time.sleep(0.2)

    assert found, (
        "Row written to Master never appeared on Replica within 10s -- "
        "streaming replication is not actually working."
    )


def test_replication_lag_is_small(master_conn, replica_conn):
    """The doc claims replication lag is 'milliseconds'. Measure it directly
    rather than taking that on faith."""
    issue_id = str(uuid.uuid4())
    t0 = time.time()
    with master_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO issues (id, title, status) VALUES (%s, %s, 'open')",
            (issue_id, f"lag-check-{issue_id}"),
        )
        master_conn.commit()

    lag_seconds = None
    deadline = time.time() + 10
    while time.time() < deadline:
        with replica_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM issues WHERE id = %s", (issue_id,))
            if cur.fetchone():
                lag_seconds = time.time() - t0
                break
        replica_conn.rollback()
        time.sleep(0.05)

    assert lag_seconds is not None, "Row never replicated"
    # Generous bound for a laptop/Docker Desktop environment; real production
    # streaming replication on decent hardware is usually well under 100ms.
    assert lag_seconds < 5, f"Replication lag was {lag_seconds:.2f}s, expected sub-second"


def test_replica_rejects_direct_writes(replica_conn):
    """This is the claim most likely to be silently false: the original
    docker-compose.yml span up two independent, freshly-initialized Postgres
    containers with no replication wired up at all. In that setup, the
    'replica' is just a normal writable database, and this test would
    incorrectly pass for the wrong reason (no error, because it's not
    actually a replica). With real streaming replication configured, this
    write MUST fail with a read-only-transaction error from Postgres itself.
    """
    replica_conn.autocommit = False
    with pytest.raises(psycopg2.errors.ReadOnlySqlTransaction):
        with replica_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO issues (id, title, status) VALUES (%s, %s, 'open')",
                (str(uuid.uuid4()), "should-never-be-allowed"),
            )
    replica_conn.rollback()


def test_replica_is_actually_in_recovery_mode(replica_conn):
    """Directly ask Postgres whether this instance considers itself a hot
    standby. This is the ground-truth check -- it's what pg_is_in_recovery()
    is for, and it can't be faked by application-level conventions."""
    with replica_conn.cursor() as cur:
        cur.execute("SELECT pg_is_in_recovery()")
        (in_recovery,) = cur.fetchone()
    assert in_recovery is True, (
        "postgres_replica is NOT in recovery/standby mode -- it is a "
        "regular standalone database, not a real replica of the master."
    )
