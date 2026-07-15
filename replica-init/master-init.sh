#!/bin/bash
# Runs once, on first boot of the master, via Postgres's docker-entrypoint-initdb.d hook.
set -e

echo "Creating replication role..."
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD 'replicator_pw';
EOSQL

# Allow the replica container to connect for replication.
# (Docker compose network is trusted/internal here; this is a learning setup, not production hardening.)
echo "host replication replicator 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"
echo "host all all 0.0.0.0/0 md5" >> "$PGDATA/pg_hba.conf"

cat <<-EOCONF >> "$PGDATA/postgresql.conf"
wal_level = replica
max_wal_senders = 10
max_replication_slots = 10
hot_standby = on
EOCONF
