#!/usr/bin/env bash
set -euo pipefail

: "${CARFAST_REHEARSAL_BYTES:=1256277934}"
: "${CARFAST_REHEARSAL_RUNS:=3}"
: "${CARFAST_FINAL_BUDGET_SECONDS:=900}"
: "${CARFAST_SSH_PORT:=22222}"
: "${CARFAST_POSTGRES_IMAGE:?CARFAST_POSTGRES_IMAGE must be an immutable RepoDigest}"

[[ "${CARFAST_POSTGRES_IMAGE}" =~ ^[^[:space:]@]+@sha256:[0-9a-f]{64}$ ]] || {
  echo postgres_image_not_digest >&2; exit 19;
}

for command in age age-keygen ssh python docker sha256sum; do
  command -v "${command}" >/dev/null || { echo "missing_command=${command}" >&2; exit 20; }
done
test "$(id -u)" -ne 0 || { echo "root_execution_forbidden" >&2; exit 21; }
test -d /dev/shm || { echo "tmpfs_missing" >&2; exit 22; }
printf 'age_version=%s\n' "$(age --version)"
docker pull "${CARFAST_POSTGRES_IMAGE}" >/dev/null
docker run --rm "${CARFAST_POSTGRES_IMAGE}" pg_dump --version | grep -E ' 17([. ]|$)'
docker image inspect "${CARFAST_POSTGRES_IMAGE}" --format 'postgres_image={{index .RepoDigests 0}}'

work="$(mktemp -d /dev/shm/carfast-standard-XXXXXX)"
[[ "${work}" == /dev/shm/carfast-standard-* ]] || { echo "unsafe_work_path" >&2; exit 23; }
cleanup() {
  find "${work}" -type f -exec shred -u -n 1 {} + 2>/dev/null || true
  rm -rf -- "${work}"
}
trap cleanup EXIT INT TERM
umask 077

age-keygen -o "${work}/age.identity" 2>"${work}/age-keygen.stderr"
age-keygen -y "${work}/age.identity" >"${work}/age.recipient"
chmod 0600 "${work}/age.identity"
recipient="$(cat "${work}/age.recipient")"
ssh_options=(
  -p "${CARFAST_SSH_PORT}"
  -o BatchMode=yes
  -o IdentitiesOnly=yes
  -o ForwardAgent=no
  -o StrictHostKeyChecking=yes
  -o "UserKnownHostsFile=${CARFAST_KNOWN_HOSTS:?}"
  -i "${CARFAST_SSH_IDENTITY:?}"
)
ssh "${ssh_options[@]}" "${USER}@127.0.0.1" 'printf CARFAST_STANDARD_SSH_OK' |
  grep -qx CARFAST_STANDARD_SSH_OK

generate_bytes() {
  python - "$1" <<'PY'
import sys
remaining = int(sys.argv[1]); chunk = b"C" * (1024 * 1024)
while remaining:
    part = chunk[:remaining]; sys.stdout.buffer.write(part); remaining -= len(part)
PY
}

digest_bytes() {
  python - "$1" <<'PY'
import hashlib
import sys
remaining = int(sys.argv[1]); chunk = b"C" * (1024 * 1024); digest = hashlib.sha256()
while remaining:
    part = chunk[:remaining]; digest.update(part); remaining -= len(part)
print(digest.hexdigest())
PY
}

transfer_generated() {
  local label="$1" bytes="$2" expected actual
  expected="$(digest_bytes "${bytes}")"
  generate_bytes "${bytes}" | age -r "${recipient}" |
    ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
      "cat > '${work}/${label}.age.partial' && sync '${work}/${label}.age.partial' && mv '${work}/${label}.age.partial' '${work}/${label}.age'"
  actual="$(ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
    "age -d -i '${work}/age.identity' < '${work}/${label}.age' | sha256sum | cut -d' ' -f1")"
  test "${actual}" = "${expected}"
}

record_artifact() {
  local label="$1" role="$2"
  python -m scripts.hash_age_artifact --artifact "${work}/${label}.age" \
    --identity "${work}/age.identity" --role "${role}" \
    --output "${work}/${label}.evidence.json"
}

transfer_tar() {
  local label="$1" root="$2" list="${3:-}"
  if [[ -n "${list}" ]]; then
    tar -C "${root}" -cf - --null --verbatim-files-from --files-from="${list}"
  else
    tar -C "${root}" -cf - .
  fi | age -r "${recipient}" |
    ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
      "cat > '${work}/${label}.age.partial' && sync '${work}/${label}.age.partial' && mv '${work}/${label}.age.partial' '${work}/${label}.age' && sync '${work}'"
  record_artifact "${label}" "${label%%-*}"
}

# Closed adversarials before consuming any full-volume run.
bad_known_hosts="${work}/bad_known_hosts"
ssh-keygen -q -t ed25519 -N '' -f "${work}/wrong-host"
printf '[127.0.0.1]:%s %s\n' "${CARFAST_SSH_PORT}" "$(cat "${work}/wrong-host.pub")" >"${bad_known_hosts}"
if ssh -p "${CARFAST_SSH_PORT}" -o BatchMode=yes -o StrictHostKeyChecking=yes \
  -o "UserKnownHostsFile=${bad_known_hosts}" -i "${CARFAST_SSH_IDENTITY}" \
  "${USER}@127.0.0.1" true 2>/dev/null; then
  echo host_key_negative_failed >&2; exit 30
fi
generate_bytes 16777216 | age -r "${recipient}" |
  ssh "${ssh_options[@]}" "${USER}@127.0.0.1" "cat > '${work}/resume.age.partial'"
ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
  "test -s '${work}/resume.age.partial' && test ! -e '${work}/resume.age'"
transfer_generated resume 33554432
transfer_generated adversarial 1048576
cp "${work}/adversarial.age" "${work}/truncated.age"
truncate -s -1 "${work}/truncated.age"
if age -d -i "${work}/age.identity" <"${work}/truncated.age" >/dev/null 2>&1; then
  echo truncation_negative_failed >&2; exit 31
fi
age-keygen -o "${work}/wrong.identity" 2>/dev/null
if age -d -i "${work}/wrong.identity" <"${work}/adversarial.age" >/dev/null 2>&1; then
  echo wrong_key_negative_failed >&2; exit 32
fi

durations=()
for run in $(seq 1 "${CARFAST_REHEARSAL_RUNS}"); do
  python -m scripts.rehearse_storage_preseed_delta \
    --bytes "${CARFAST_REHEARSAL_BYTES}" \
    --final-budget-seconds "${CARFAST_FINAL_BUDGET_SECONDS}" \
    --workspace "${work}/fixture-${run}" \
    >"${work}/storage-${run}.json"
  grep -q '"result": "PASS"' "${work}/storage-${run}.json"
  transfer_tar "preseed-${run}" "${work}/fixture-${run}/preseed_snapshot"
  python - "${work}/storage-${run}.json" "${work}/delta-${run}.list" <<'PY'
import json
import sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
with open(sys.argv[2], "wb") as handle:
    for path in payload["delta_copy_paths"]:
        handle.write(path.encode("utf-8") + b"\0")
PY

  database="carfast_standard_${run}"
  restored="carfast_standard_restored_${run}"
  docker run --rm --network host -e PGPASSWORD=carfast "${CARFAST_POSTGRES_IMAGE}" \
    psql -h 127.0.0.1 -U carfast -d carfast_test -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${database}" -c "CREATE DATABASE ${database}" >/dev/null
  DATABASE_URL="postgresql+psycopg://carfast:carfast@127.0.0.1:5432/${database}" \
    python -m alembic upgrade ffae1f2a3b4c
  docker run --rm --network host -e PGPASSWORD=carfast "${CARFAST_POSTGRES_IMAGE}" \
    psql -h 127.0.0.1 -U carfast -d "${database}" -v ON_ERROR_STOP=1 \
    -c "INSERT INTO audit_log(action, detail) SELECT 'synthetic.rehearsal', repeat(md5(g::text), 32768) FROM generate_series(1,208) AS g" >/dev/null
  DATABASE_URL="postgresql+psycopg://carfast:carfast@127.0.0.1:5432/${database}" \
    python -m scripts.validate_integral_migration_contract source
  start_ns="$(python -c 'import time; print(time.monotonic_ns())')"
  docker run --rm --network host -e PGPASSWORD=carfast "${CARFAST_POSTGRES_IMAGE}" \
    pg_dump -h 127.0.0.1 -U carfast -d "${database}" -Fc --no-owner --no-acl |
    age -r "${recipient}" |
    ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
      "cat > '${work}/db-${run}.age.partial' && sync '${work}/db-${run}.age.partial' && mv '${work}/db-${run}.age.partial' '${work}/db-${run}.age'"
  record_artifact "db-${run}" db
  delta_bytes="$(python -c "import json; print(json.load(open('${work}/storage-${run}.json'))['delta_bytes'])")"
  transfer_tar "delta-${run}" "${work}/fixture-${run}/source" "${work}/delta-${run}.list"
  test -s "${work}/db-${run}.age"
  test -s "${work}/delta-${run}.age"
  head -c 32 /dev/urandom >"${work}/ack-${run}.secret"
  chmod 0600 "${work}/ack-${run}.secret"
  python - "${work}" "${run}" "$(git rev-parse HEAD)" <<'PY'
import json
import sys
from datetime import datetime, timezone
root, run, release = sys.argv[1:]
storage = json.load(open(f"{root}/storage-{run}.json", encoding="utf-8"))
preseed_objects = json.load(open(f"{root}/fixture-{run}/preseed-manifest.json", encoding="utf-8"))
final_objects = json.load(open(f"{root}/fixture-{run}/final-manifest.json", encoding="utf-8"))
deletion_paths = storage["delta_remove_paths"]
artifacts = [json.load(open(f"{root}/{name}-{run}.evidence.json", encoding="utf-8"))
             for name in ("preseed", "db", "delta")]
payload = {"bundle_id": f"synthetic-{run}", "cutoff_utc": datetime.now(timezone.utc).isoformat(),
           "source_release": release, "target_release": release,
           "preseed_manifest_sha256": storage["preseed_manifest_sha256"],
           "final_manifest_sha256": storage["final_manifest_sha256"],
           "preseed_objects": preseed_objects, "final_objects": final_objects,
           "deletion_paths": deletion_paths,
           "deletion_manifest_sha256": __import__("hashlib").sha256(
               json.dumps(deletion_paths, sort_keys=True, separators=(",", ":")).encode()
           ).hexdigest(),
           "deletion_count": storage["delta_remove_objects"], "artifacts": artifacts}
with open(f"{root}/bundle-{run}.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle, sort_keys=True)
PY
  ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
    "cat > '${work}/bundle-receiver-${run}.json.partial' && sync '${work}/bundle-receiver-${run}.json.partial' && mv '${work}/bundle-receiver-${run}.json.partial' '${work}/bundle-receiver-${run}.json' && sync '${work}'" \
    <"${work}/bundle-${run}.json"
  cutoff="$(python -c "import json; print(json.load(open('${work}/bundle-${run}.json'))['cutoff_utc'])")"
  release="$(git rev-parse HEAD)"
  ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
    "cd '$(pwd)' && python -m scripts.standard_bundle_ack emit --manifest '${work}/bundle-receiver-${run}.json' --secret '${work}/ack-${run}.secret' --ack '${work}/ack-${run}.json' --artifact-root '${work}' --identity '${work}/age.identity' --plaintext-root '${work}/received-${run}' --expected-bundle-id 'synthetic-${run}' --expected-cutoff-utc '${cutoff}' --expected-source-release '${release}' --expected-target-release '${release}'"
  python -m scripts.standard_bundle_ack verify \
    --manifest "${work}/bundle-${run}.json" --secret "${work}/ack-${run}.secret" \
    --ack "${work}/ack-${run}.json"
  end_ns="$(python -c 'import time; print(time.monotonic_ns())')"
  test -d "${work}/received-${run}/preseed"
  test -d "${work}/received-${run}/delta"
  test -s "${work}/received-${run}/db.dump"
  python - "${work}" "${run}" <<'PY'
import json
import sys
from app.platform.integral_reconciliation import StorageEvidence
from app.platform.storage_preseed_delta import (
    assert_secure_storage_exact, calculate_delta, secure_sync_manifest,
)
from pathlib import Path
root = Path(sys.argv[1]); run = sys.argv[2]
preseed = tuple(StorageEvidence(**item) for item in json.load(open(root / f"fixture-{run}/preseed-manifest.json", encoding="utf-8")))
final = tuple(StorageEvidence(**item) for item in json.load(open(root / f"fixture-{run}/final-manifest.json", encoding="utf-8")))
delta = calculate_delta(preseed, final)
target = root / f"received-{run}/preseed"
secure_sync_manifest(root / f"received-{run}/delta", target, delta.copy,
                     remove=delta.remove, synthetic_only=True)
assert_secure_storage_exact(target, final, synthetic_only=True)
PY
  docker run --rm --network host -e PGPASSWORD=carfast "${CARFAST_POSTGRES_IMAGE}" \
    psql -h 127.0.0.1 -U carfast -d carfast_test -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${restored}" -c "CREATE DATABASE ${restored}" >/dev/null
  docker run --rm --network host -i -e PGPASSWORD=carfast "${CARFAST_POSTGRES_IMAGE}" \
    pg_restore -h 127.0.0.1 -U carfast -d "${restored}" --no-owner --no-acl \
    <"${work}/received-${run}/db.dump"
  DATABASE_URL="postgresql+psycopg://carfast:carfast@127.0.0.1:5432/${restored}" \
    python -m scripts.validate_integral_migration_contract staging
  DATABASE_URL="postgresql+psycopg://carfast:carfast@127.0.0.1:5432/${restored}" \
    python -m alembic upgrade head
  DATABASE_URL="postgresql+psycopg://carfast:carfast@127.0.0.1:5432/${restored}" \
    python -m scripts.validate_integral_migration_contract target

  storage_final="$(python -c "import json; print(json.load(open('${work}/storage-${run}.json'))['final_phase_seconds'])")"
  duration="$(python -c "print(((${end_ns}-${start_ns})/1_000_000_000)+${storage_final})")"
  durations+=("${duration}")
  printf 'run=%s preseed_bytes=%s delta_bytes=%s final_phase_seconds=%s result=PASS\n' \
    "${run}" "${CARFAST_REHEARSAL_BYTES}" "${delta_bytes}" "${duration}"
  docker run --rm --network host -e PGPASSWORD=carfast "${CARFAST_POSTGRES_IMAGE}" \
    psql -h 127.0.0.1 -U carfast -d carfast_test -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE ${database}" -c "DROP DATABASE ${restored}" >/dev/null
  rm -rf -- "${work}/fixture-${run}" "${work}/received-${run}"
  find "${work}" -maxdepth 1 -type f -name "*-${run}.*" -exec shred -u -n 1 {} +
done

python - "${CARFAST_FINAL_BUDGET_SECONDS}" "${durations[@]}" <<'PY'
import statistics
import sys
budget = float(sys.argv[1]); values = [float(value) for value in sys.argv[2:]]
p95 = max(values) if len(values) < 20 else statistics.quantiles(values, n=100)[94]
if p95 > budget:
    raise SystemExit(f"p95_budget_failed={p95:.6f}")
print(f"runs={len(values)} p95_seconds={p95:.6f} budget_seconds={budget:.6f} result=PASS")
PY
