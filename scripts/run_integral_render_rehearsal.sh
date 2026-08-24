#!/bin/sh
set -eu

test "${REAL_DATA_ALLOWED:-false}" = false
test "${EXTERNAL_INTEGRATIONS_ENABLED:-false}" = false
test "${INTEGRAL_MODE:-synthetic}" = synthetic
test "${EMAIL_ENABLED:-false}" = false
test "${JOBS_ENABLED:-false}" = false
test "${WEBHOOKS_ENABLED:-false}" = false
test "${PORTALS_ENABLED:-false}" = false
test "${INTEGRAL_CUTOVER_REQUESTED:-false}" = false
test "${INTEGRAL_PRODUCTION_DEPLOY_REQUESTED:-false}" = false

export PGDATA=/var/data/carfast-render-postgres
one_shot_state=/var/data/carfast-integral-one-shot.state
if [ -e "$one_shot_state" ]; then
  echo "render_integral_one_shot=blocked prior_state_present=true"
  python -m http.server "${PORT:-10000}" --bind 0.0.0.0 >/tmp/integral-health.log 2>&1 &
  wait "$!"
fi

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

finish_one_shot() {
  result="$1"
  tmp_state="${one_shot_state}.tmp"
  umask 077
  printf 'version=1\nrelease=%s\nresult=%s\n' "${GITHUB_SHA:-unknown}" "$result" >"$tmp_state"
  mv "$tmp_state" "$one_shot_state"
}

export INTEGRAL_REHEARSAL_PGHOST=localhost
export INTEGRAL_REHEARSAL_DESTINATION_HOST=localhost
export INTEGRAL_REHEARSAL_WORK_ROOT=/var/data
export INTEGRAL_REHEARSAL_ADMIN_ROLE=carfast
export INTEGRAL_REHEARSAL_ADMIN_PASSWORD=synthetic-only
python -m pytest -q tests/test_integral_config.py tests/test_integral_secrets.py
echo "render_config_and_secret_adversarials=true before_window=true"
set +e
sh scripts/run_integral_e2e_rehearsal.sh 4 1256277934
rehearsal_rc=$?
set -e
if [ "$rehearsal_rc" -ne 0 ]; then
  finish_one_shot "no-go"
  echo "render_integral_full_scale=false cleanup=verified one_shot=true rc=$rehearsal_rc"
  sleep "${RENDER_REHEARSAL_HOLD_SECONDS:-600}"
  exit "$rehearsal_rc"
fi
finish_one_shot "pass"
echo "render_integral_full_scale=true bytes=1256277934 cleanup=verified"

# Hold only for evidence collection. The service is deleted immediately afterwards.
sleep "${RENDER_REHEARSAL_HOLD_SECONDS:-600}"
