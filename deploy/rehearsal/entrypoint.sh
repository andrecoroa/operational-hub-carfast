#!/bin/sh
set -eu

test "${REAL_DATA_ALLOWED:-false}" = "false"
test "${EXTERNAL_INTEGRATIONS_ENABLED:-false}" = "false"

PGDATA=/var/data/postgresql
export PGDATA
install -d -o postgres -g postgres "$PGDATA" /var/run/postgresql
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  gosu postgres initdb --auth-local=trust --auth-host=reject
fi
gosu postgres pg_ctl \
  -o "-c listen_addresses='' -c unix_socket_directories=/var/run/postgresql" -w start
gosu postgres createdb carfast_anonymized_test 2>/dev/null || true

export PATH="/opt/carfast-venv/bin:$PATH"
export LOCAL_POSTGRES_SOCKET=/var/run/postgresql
export DATABASE_URL="postgresql+psycopg://postgres@/carfast_anonymized_test?host=/var/run/postgresql"
export LOCAL_POSTGRES_DSN="postgresql://postgres@/carfast_anonymized_test?host=/var/run/postgresql"
export PYTHON_BIN=/opt/carfast-venv/bin/python
exec python -m scripts.render_empty_rehearsal
