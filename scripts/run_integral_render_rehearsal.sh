#!/bin/sh
set -eu

test "${REAL_DATA_ALLOWED:-false}" = false
test "${EXTERNAL_INTEGRATIONS_ENABLED:-false}" = false

export PGDATA=/var/data/carfast-render-postgres
install -d -o postgres -g postgres "$PGDATA" /var/run/postgresql
gosu postgres initdb -U carfast --auth-local=trust --auth-host=trust >/dev/null
gosu postgres pg_ctl -o "-c listen_addresses=127.0.0.1 -c unix_socket_directories=/var/run/postgresql" -w start >/dev/null

python -m http.server "${PORT:-10000}" --bind 0.0.0.0 >/tmp/integral-health.log 2>&1 &
health_pid=$!
cleanup() {
  kill "$health_pid" 2>/dev/null || true
  gosu postgres pg_ctl -m fast -w stop >/dev/null 2>&1 || true
  rm -rf "$PGDATA" /tmp/integral-health.log
}
trap cleanup EXIT INT TERM

export INTEGRAL_REHEARSAL_PGHOST=localhost
export INTEGRAL_REHEARSAL_DESTINATION_HOST=localhost
export INTEGRAL_REHEARSAL_WORK_ROOT=/var/data
export INTEGRAL_REHEARSAL_ADMIN_ROLE=carfast
export INTEGRAL_REHEARSAL_ADMIN_PASSWORD=synthetic-only
sh scripts/run_integral_e2e_rehearsal.sh 4 1256277934
echo "render_integral_full_scale=true bytes=1256277934 cleanup=verified"

# Hold only for evidence collection. The service is deleted immediately afterwards.
sleep "${RENDER_REHEARSAL_HOLD_SECONDS:-600}"
