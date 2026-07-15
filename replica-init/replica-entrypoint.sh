#!/bin/bash
# This is what the original document's docker-compose.yml was missing entirely:
# an actual mechanism to clone the master's data and attach as a streaming
# replica. Without this, "postgres_replica" is just an empty, unrelated database.
set -e

PGDATA=${PGDATA:-/var/lib/postgresql/data}

if [ -z "$(ls -A "$PGDATA" 2>/dev/null)" ]; then
    echo "Replica data dir empty. Waiting for master to accept connections..."
    until PGPASSWORD=replicator_pw pg_isready -h postgres_master -U replicator -d postgres; do
        sleep 1
    done

    echo "Cloning master with pg_basebackup..."
    PGPASSWORD=replicator_pw pg_basebackup \
        -h postgres_master \
        -D "$PGDATA" \
        -U replicator \
        -v -P \
        -R \
        --wal-method=stream

    # -R writes standby.signal + primary_conninfo into postgresql.auto.conf for us
    # (Postgres 12+ recovery mechanism), so this replica will start in hot standby
    # mode and begin streaming WAL from the master automatically.

    chmod 700 "$PGDATA"
fi

exec docker-entrypoint.sh postgres
