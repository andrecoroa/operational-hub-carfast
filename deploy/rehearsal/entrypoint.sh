#!/bin/sh
set -eu

test "${REAL_DATA_ALLOWED:-false}" = "false"
test "${EXTERNAL_INTEGRATIONS_ENABLED:-false}" = "false"

PGDATA=/var/data/postgresql
export PGDATA
install -d -o postgres -g postgres "$PGDATA" /var/run/postgresql
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  su postgres -c "initdb --auth-local=trust --auth-host=reject"
fi
su postgres -c "pg_ctl -o \"-c listen_addresses='' -c unix_socket_directories=/var/run/postgresql\" -w start"
su postgres -c "createdb carfast_anonymized_test" 2>/dev/null || true

export PATH="/opt/carfast-venv/bin:$PATH"
export LOCAL_POSTGRES_SOCKET=/var/run/postgresql
export DATABASE_URL="postgresql+psycopg:///carfast_anonymized_test?host=/var/run/postgresql"
exec python -m scripts.render_empty_rehearsal
