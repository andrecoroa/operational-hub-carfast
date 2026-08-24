#!/bin/sh
set -eu

test "${INTEGRAL_ENTRYPOINT_DELEGATED:-0}" = 1 || {
  echo "legacy_integral_e2e_direct_invocation_rejected=true" >&2
  exit 64
}

run_id="${1:?run id required}"
storage_bytes="${2:?storage bytes required}"
case "$run_id" in *[!0-9]*) exit 2;; esac

host="${INTEGRAL_REHEARSAL_PGHOST:-rehearsal-postgres}"
case "$host" in localhost|127.0.0.1|::1|rehearsal-postgres) echo "external_postgres_required=true" >&2; exit 64;; esac
admin_role="${INTEGRAL_REHEARSAL_ADMIN_ROLE:-carfast}"
admin_password="${INTEGRAL_REHEARSAL_ADMIN_PASSWORD:-carfast}"
source_db="carfast_integral_source_${run_id}_test"
staging_db="carfast_integral_staging_${run_id}_test"
source_role="integral_source_ro_${run_id}"
staging_role="integral_stage_${run_id}"
source_password="synthetic-source-${run_id}"
staging_password="synthetic-stage-${run_id}"
work_root="${INTEGRAL_REHEARSAL_WORK_ROOT:-/tmp}"
storage_root="$work_root/integral-e2e-${run_id}-source"
staging_root="$work_root/integral-e2e-${run_id}-staging"
receiver_pid=""
sender_envelope="${INTEGRAL_SENDER_SECRET_ENVELOPE_FILE:?managed sender envelope required}"
receiver_envelope="${INTEGRAL_RECEIVER_SECRET_ENVELOPE_FILE:?managed receiver envelope required}"
sender_envelope_sha="${INTEGRAL_SENDER_SECRET_ENVELOPE_SHA256:?sender envelope fingerprint required}"
receiver_envelope_sha="${INTEGRAL_RECEIVER_SECRET_ENVELOPE_SHA256:?receiver envelope fingerprint required}"
export INTEGRAL_PRIVATE_SECRET_ROOT="$work_root/integral-private-secrets-$run_id"

cleanup() {
  exit_status=$?
  if [ -n "$receiver_pid" ] && kill -0 "$receiver_pid" 2>/dev/null; then
    kill "$receiver_pid" 2>/dev/null || true
    wait "$receiver_pid" 2>/dev/null || true
  fi
  PGPASSWORD="$admin_password" psql -h "$host" -U "$admin_role" -d postgres \
    -v ON_ERROR_STOP=1 -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$source_db', '$staging_db') AND pid <> pg_backend_pid()" \
    >/dev/null 2>&1 || true
  if [ "$exit_status" -ne 0 ] && [ -f "/tmp/integral-receiver-$run_id.log" ]; then
    echo "synthetic_receiver_diagnostic_begin" >&2
    tail -n 80 "/tmp/integral-receiver-$run_id.log" >&2
    echo "synthetic_receiver_diagnostic_end" >&2
  fi
  rm -f "/tmp/integral-receiver-$run_id.log" "/tmp/integral-preflight-$run_id.json"
  rm -f "$work_root"/carfast-integral-*.spool
  rm -rf "$INTEGRAL_PRIVATE_SECRET_ROOT"
  rm -rf "$storage_root" "$staging_root"
  PGPASSWORD="$admin_password" dropdb -h "$host" -U "$admin_role" --if-exists "$source_db" || true
  PGPASSWORD="$admin_password" dropdb -h "$host" -U "$admin_role" --if-exists "$staging_db" || true
  PGPASSWORD="$admin_password" psql -h "$host" -U "$admin_role" -d postgres \
    -v ON_ERROR_STOP=1 -c "DROP ROLE IF EXISTS $source_role; DROP ROLE IF EXISTS $staging_role" \
    >/dev/null || true
  if find "$work_root" -maxdepth 1 -name 'carfast-integral-*.spool' -print -quit | grep -q .; then
    echo "rehearsal cleanup found residual spool" >&2
    exit 1
  fi
  return "$exit_status"
}
trap cleanup EXIT INT TERM

PGPASSWORD="$admin_password" psql -h "$host" -U "$admin_role" -d postgres \
  -v ON_ERROR_STOP=1 <<SQL >/dev/null
CREATE ROLE $source_role LOGIN PASSWORD '$source_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
CREATE ROLE $staging_role LOGIN PASSWORD '$staging_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
SQL
PGPASSWORD="$admin_password" createdb -h "$host" -U "$admin_role" -O "$admin_role" "$source_db"
PGPASSWORD="$admin_password" createdb -h "$host" -U "$admin_role" -O "$staging_role" "$staging_db"

DATABASE_URL="postgresql+psycopg://$admin_role:$admin_password@$host:5432/$source_db" \
  python -m alembic upgrade ffae1f2a3b4c
DATABASE_URL="postgresql+psycopg://$admin_role:$admin_password@$host:5432/$source_db" \
  python -m scripts.validate_integral_migration_contract source
PGPASSWORD="$admin_password" psql -h "$host" -U "$admin_role" -d "$source_db" \
  -v ON_ERROR_STOP=1 <<SQL >/dev/null
INSERT INTO permissions (id, code, name, description) VALUES (900000 + $run_id, 'integral.fixture.$run_id', 'Integral fixture $run_id', NULL);
GRANT CONNECT ON DATABASE $source_db TO $source_role;
GRANT USAGE ON SCHEMA public TO $source_role;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO $source_role;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM $source_role;
SQL

mkdir -p "$storage_root/documents/vehicles/fixture-$run_id" "$storage_root/email/attachments" "$staging_root"
first=$((storage_bytes / 2))
second=$((storage_bytes - first - 4096))
truncate -s "$first" "$storage_root/documents/vehicles/fixture-$run_id/archive.bin"
truncate -s "$second" "$storage_root/email/attachments/message.bin"
dd if=/dev/zero of="$storage_root/root-manifest.bin" bs=4096 count=1 status=none

destination_host="${INTEGRAL_REHEARSAL_DESTINATION_HOST:-carfast-integral-fixture}"
test "${INTEGRAL_MODE:?}" = synthetic
test "${REAL_DATA_ALLOWED:?}" = false
test "${INTEGRAL_EXPECTED_DATABASE_HOST:?}" = "$host"
common_env=""

sender_secret_env="INTEGRAL_SECRET_ENVELOPE_FILE=$sender_envelope INTEGRAL_SECRET_ENVELOPE_ROLE=sender INTEGRAL_SECRET_ENVELOPE_SHA256=$sender_envelope_sha"
receiver_secret_env="INTEGRAL_SECRET_ENVELOPE_FILE=$receiver_envelope INTEGRAL_SECRET_ENVELOPE_ROLE=receiver INTEGRAL_SECRET_ENVELOPE_SHA256=$receiver_envelope_sha"

env $common_env $sender_secret_env INTEGRAL_DATABASE_DUMP_PHASE=source-staging \
  INTEGRAL_EXPECTED_DATABASE_HOST="$host" INTEGRAL_EXPECTED_DATABASE_NAME="$source_db" \
  python -m scripts.preflight_integral_config --role sender
env $common_env $receiver_secret_env INTEGRAL_DATABASE_DESTINATION_PHASE=staging \
  INTEGRAL_DECLARED_BUNDLE_BYTES="$((storage_bytes + 64 * 1024 * 1024))" \
  INTEGRAL_EXPECTED_DATABASE_HOST="$host" INTEGRAL_EXPECTED_DATABASE_NAME="$staging_db" \
  INTEGRAL_SOURCE_REVISION=ffae1f2a3b4c INTEGRAL_SPOOL_ROOT="$work_root" \
  python -m scripts.preflight_integral_config --role receiver

env $common_env $receiver_secret_env \
  INTEGRAL_DATABASE_DESTINATION_PHASE=staging INTEGRAL_SOURCE_REVISION=ffae1f2a3b4c \
  INTEGRAL_EXPECTED_DATABASE_HOST="$host" \
  STAGING_DATABASE_URL="postgresql://$staging_role:$staging_password@$host:5432/$staging_db" \
  INTEGRAL_EXPECTED_DATABASE_NAME="$staging_db" INTEGRAL_SPOOL_ROOT="$work_root" \
  INTEGRAL_DECLARED_BUNDLE_BYTES="$((storage_bytes + 64 * 1024 * 1024))" \
  python -m scripts.preflight_integral_runtime >/tmp/integral-preflight-$run_id.json

# Exercise the exact real pg_restore binary/flags negatively before the valid archive.
restore_started="$(date +%s)"
set +e
printf 'synthetic-invalid-archive' | PGPASSWORD="$staging_password" pg_restore \
  --clean --if-exists --dbname="$staging_db" --host="$host" --username="$staging_role" \
  --single-transaction --exit-on-error --no-owner --no-privileges \
  >/dev/null 2>"/tmp/integral-negative-restore-$run_id.err"
negative_rc=$?
set -e
test "$negative_rc" -ne 0
negative_bytes="$(wc -c <"/tmp/integral-negative-restore-$run_id.err")"
negative_sha="$(sha256sum "/tmp/integral-negative-restore-$run_id.err" | cut -d ' ' -f 1)"
rm -f "/tmp/integral-negative-restore-$run_id.err"
tables_after_negative="$(
  PGPASSWORD="$staging_password" psql -h "$host" -U "$staging_role" \
    -d "$staging_db" -Atqc "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
)"
test "$tables_after_negative" -eq 0
restore_finished="$(date +%s)"
restore_duration=$((restore_finished - restore_started))
echo "negative_restore_stage=pg_restore rc=$negative_rc duration_seconds=$restore_duration stderr_bytes=$negative_bytes stderr_sha256=$negative_sha"

env $common_env $receiver_secret_env APP_ENV=test \
  INTEGRAL_RUNTIME_ROLE=receiver INTEGRAL_MODE=synthetic PORT=10000 \
  INTEGRAL_TOMBSTONE_PATH="$work_root/tombstone-$run_id-receiver.json" \
  INTEGRAL_ENTRYPOINT_DEADLINE_SECONDS=1800 \
  INTEGRAL_DATABASE_DESTINATION_PHASE=staging INTEGRAL_DECLARED_BUNDLE_BYTES="$((storage_bytes + 64 * 1024 * 1024))" \
  INTEGRAL_SOURCE_REVISION=ffae1f2a3b4c INTEGRAL_SPOOL_ROOT="$work_root" \
  INTEGRAL_EXPECTED_DATABASE_HOST="$host" \
  DATABASE_URL="postgresql+psycopg://$staging_role:$staging_password@$host:5432/$staging_db" \
  INTEGRAL_EXPECTED_DATABASE_NAME="$staging_db" \
  INTEGRAL_STORAGE_STAGING_ROOT="$staging_root" \
  python -m scripts.integral_render_entrypoint >/tmp/integral-receiver-$run_id.log 2>&1 &
receiver_pid=$!
sleep 2
env $common_env $sender_secret_env \
  INTEGRAL_RUNTIME_ROLE=sender INTEGRAL_MODE=synthetic PORT=10002 \
  INTEGRAL_TOMBSTONE_PATH="$work_root/tombstone-$run_id-sender.json" \
  INTEGRAL_ENTRYPOINT_DEADLINE_SECONDS=1800 \
  INTEGRAL_DATABASE_DUMP_PHASE=source-staging INTEGRAL_EXPECTED_DATABASE_HOST="$host" \
  DATABASE_URL="postgresql+psycopg://$source_role:$source_password@$host:5432/$source_db" \
  INTEGRAL_EXPECTED_DATABASE_NAME="$source_db" \
  INTEGRAL_STORAGE_SOURCE_ROOT="$storage_root" \
  python -m scripts.integral_render_entrypoint
wait "$receiver_pid"
receiver_pid=""

DATABASE_URL="postgresql+psycopg://$staging_role:$staging_password@$host:5432/$staging_db" \
  python -m scripts.validate_integral_migration_contract target
echo "integral_e2e_run=$run_id storage_bytes=$storage_bytes status=green"
