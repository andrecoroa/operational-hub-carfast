#!/bin/sh
# CI-only fixture provisioner: simulates Render API secret mounts before entrypoint.
set -eu
stage=bootstrap
on_exit() {
  rc=$?
  rm -f "${sender_envelope:-}" "${receiver_envelope:-}"
  if [ "$rc" -ne 0 ]; then
    echo "integral_fixture_failure_stage=$stage rc=$rc" >&2
  fi
  return "$rc"
}
trap on_exit EXIT INT TERM

run_id="${1:?run id required}"
storage_bytes="${2:?storage bytes required}"
host="${INTEGRAL_REHEARSAL_PGHOST:?external PostgreSQL host required}"
case "$host" in localhost|127.0.0.1|::1|rehearsal-postgres) exit 64;; esac
work_root="${INTEGRAL_REHEARSAL_WORK_ROOT:-/tmp}"
source_db="carfast_integral_source_${run_id}_test"
staging_db="carfast_integral_staging_${run_id}_test"
source_role="integral_source_ro_${run_id}"
staging_role="integral_stage_${run_id}"
source_password="synthetic-source-${run_id}"
staging_password="synthetic-stage-${run_id}"
managed_root="${INTEGRAL_MANAGED_SECRET_ROOT:-/etc/secrets}"
sender_envelope="$managed_root/integral-sender-$run_id.json"
receiver_envelope="$managed_root/integral-receiver-$run_id.json"
hmac_key="synthetic-integral-hmac-material-${run_id}-32bytes"
hmac_snapshot="$(printf %s "$hmac_key" | sha256sum | cut -d ' ' -f 1)"

umask 077
stage=managed_mount
mkdir -p "$managed_root" "$work_root"
sender_url="postgresql://$source_role:$source_password@$host:5432/$source_db"
receiver_url="postgresql://$staging_role:$staging_password@$host:5432/$staging_db"
sender_sha="$(INTEGRAL_ENVELOPE_DATABASE_URL_INPUT="$sender_url" INTEGRAL_ENVELOPE_TRANSFER_KEY_INPUT="$hmac_key" python -m scripts.build_integral_secret_envelope --role sender --output "$sender_envelope")"
receiver_sha="$(INTEGRAL_ENVELOPE_DATABASE_URL_INPUT="$receiver_url" INTEGRAL_ENVELOPE_TRANSFER_KEY_INPUT="$hmac_key" python -m scripts.build_integral_secret_envelope --role receiver --output "$receiver_envelope")"
chmod 0444 "$sender_envelope" "$receiver_envelope"

export INTEGRAL_RUNTIME_ROLE=synthetic_orchestrator INTEGRAL_MODE=synthetic
export PORT=10010
export INTEGRAL_ISOLATED_REHEARSAL=true
export RENDER_EMPTY_REHEARSAL=true REHEARSAL_DATABASE_HOST="$host"
export INTEGRAL_RELEASE_SHA="${GITHUB_SHA:?release required}" INTEGRAL_RUN_ID="$run_id" INTEGRAL_STORAGE_BYTES="$storage_bytes"
export INTEGRAL_REHEARSAL_DESTINATION_HOST="${INTEGRAL_REHEARSAL_DESTINATION_HOST:-carfast-integral-fixture}"
export INTEGRAL_SOURCE_SERVICE=srv-synthetic-source INTEGRAL_DESTINATION_SERVICE=srv-synthetic-destination
export INTEGRAL_CUTOFF_ID="cut-synthetic-$run_id" INTEGRAL_BUNDLE_ID="bundle-synthetic-$run_id"
export INTEGRAL_DESTINATION_HOST="$INTEGRAL_REHEARSAL_DESTINATION_HOST" INTEGRAL_EXPECTED_DESTINATION_HOST="$INTEGRAL_REHEARSAL_DESTINATION_HOST"
export INTEGRAL_DESTINATION_PORT=10001 INTEGRAL_EXPECTED_DESTINATION_PORT=10001
export INTEGRAL_HMAC_SNAPSHOT_SHA256="$hmac_snapshot" INTEGRAL_EXPECTED_HMAC_SNAPSHOT_SHA256="$hmac_snapshot"
export INTEGRAL_MAX_STREAM_BYTES=2147483648 INTEGRAL_CLIENT_TIMEOUT_SECONDS=1200 INTEGRAL_BUNDLE_TIMEOUT_SECONDS=900
export INTEGRAL_AUTHORIZATION_STATE_ROOT="$work_root/auth-$run_id"
export INTEGRAL_AUTHORIZATION_ID=none INTEGRAL_AUTHORIZATION_ISSUED_AT=none INTEGRAL_AUTHORIZATION_EXPIRES_AT=none
export REAL_DATA_ALLOWED=false EXTERNAL_INTEGRATIONS_ENABLED=false EMAIL_ENABLED=false JOBS_ENABLED=false WEBHOOKS_ENABLED=false PORTALS_ENABLED=false
export INTEGRAL_CUTOVER_REQUESTED=false INTEGRAL_PRODUCTION_DEPLOY_REQUESTED=false
export INTEGRAL_MANIFEST_SENDER_DATABASE_DUMP_PHASE=source-staging
export INTEGRAL_MANIFEST_SENDER_EXPECTED_DATABASE_HOST="$host" INTEGRAL_MANIFEST_SENDER_EXPECTED_DATABASE_NAME="$source_db"
export INTEGRAL_MANIFEST_RECEIVER_DATABASE_DESTINATION_PHASE=staging
export INTEGRAL_MANIFEST_RECEIVER_EXPECTED_DATABASE_HOST="$host" INTEGRAL_MANIFEST_RECEIVER_EXPECTED_DATABASE_NAME="$staging_db"
export INTEGRAL_MANIFEST_RECEIVER_DECLARED_BUNDLE_BYTES="$((storage_bytes + 64 * 1024 * 1024))"
export INTEGRAL_MANIFEST_RECEIVER_SOURCE_REVISION=ffae1f2a3b4c INTEGRAL_MANIFEST_RECEIVER_SPOOL_ROOT="$work_root"
export INTEGRAL_SECRET_ENVELOPE_FILE="$receiver_envelope" INTEGRAL_SECRET_ENVELOPE_ROLE=receiver INTEGRAL_SECRET_ENVELOPE_SHA256="$receiver_sha"
export INTEGRAL_EXPECTED_DATABASE_HOST="$host" INTEGRAL_EXPECTED_DATABASE_NAME="$staging_db"
export INTEGRAL_PRIVATE_DATABASE_SUFFIX="${INTEGRAL_PRIVATE_DATABASE_SUFFIX:?private suffix required}"
export INTEGRAL_SPOOL_ROOT="$work_root" INTEGRAL_DECLARED_BUNDLE_BYTES="$((storage_bytes + 64 * 1024 * 1024))"
export INTEGRAL_DATABASE_DESTINATION_PHASE=staging INTEGRAL_SOURCE_REVISION=ffae1f2a3b4c
export INTEGRAL_MEMORY_LIMIT_BYTES="${INTEGRAL_MEMORY_LIMIT_BYTES:-536870912}"
export INTEGRAL_ENTRYPOINT_DEADLINE_SECONDS=1800 INTEGRAL_TOMBSTONE_PATH="$work_root/tombstone-$run_id.json"
export INTEGRAL_SENDER_SECRET_ENVELOPE_FILE="$sender_envelope" INTEGRAL_SENDER_SECRET_ENVELOPE_SHA256="$sender_sha"
export INTEGRAL_RECEIVER_SECRET_ENVELOPE_FILE="$receiver_envelope" INTEGRAL_RECEIVER_SECRET_ENVELOPE_SHA256="$receiver_sha"

stage=config_manifest
manifest="$(python -m scripts.build_integral_config_manifest)"
export INTEGRAL_CONFIG_MANIFEST="$manifest"
export INTEGRAL_CONFIG_SHA256="$(printf %s "$manifest" | sha256sum | cut -d ' ' -f 1)"

stage=entrypoint
python -m scripts.integral_render_entrypoint
stage=complete
