#!/usr/bin/env bash
set -euo pipefail

: "${CARFAST_REHEARSAL_BYTES:=1256277934}"
: "${CARFAST_REHEARSAL_RUNS:=3}"
: "${CARFAST_FINAL_BUDGET_SECONDS:=900}"
: "${CARFAST_SSH_PORT:=22222}"

for command in age age-keygen ssh python docker sha256sum; do
  command -v "${command}" >/dev/null || { echo "missing_command=${command}" >&2; exit 20; }
done
test "$(id -u)" -ne 0 || { echo "root_execution_forbidden" >&2; exit 21; }
test -d /dev/shm || { echo "tmpfs_missing" >&2; exit 22; }
printf 'age_version=%s\n' "$(age --version)"
docker pull postgres:17-bookworm >/dev/null
docker run --rm postgres:17-bookworm pg_dump --version | grep -E ' 17([. ]|$)'
docker image inspect postgres:17-bookworm --format 'postgres_image={{index .RepoDigests 0}}'

work="$(mktemp -d /dev/shm/carfast-standard-XXXXXX)"
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
    >"${work}/storage-${run}.json"
  grep -q '"result": "PASS"' "${work}/storage-${run}.json"
  transfer_generated "preseed-${run}" "${CARFAST_REHEARSAL_BYTES}"

  database="carfast_standard_${run}"
  restored="carfast_standard_restored_${run}"
  docker run --rm --network host -e PGPASSWORD=carfast postgres:17-bookworm \
    psql -h 127.0.0.1 -U carfast -d carfast_test -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${database}" -c "CREATE DATABASE ${database}" >/dev/null
  DATABASE_URL="postgresql+psycopg://carfast:carfast@127.0.0.1:5432/${database}" \
    python -m alembic upgrade ffae1f2a3b4c
  DATABASE_URL="postgresql+psycopg://carfast:carfast@127.0.0.1:5432/${database}" \
    python -m scripts.validate_integral_migration_contract source
  start_ns="$(python -c 'import time; print(time.monotonic_ns())')"
  docker run --rm --network host -e PGPASSWORD=carfast postgres:17-bookworm \
    pg_dump -h 127.0.0.1 -U carfast -d "${database}" -Fc --no-owner --no-acl |
    tee >(sha256sum | cut -d' ' -f1 >"${work}/db-${run}.source.sha256") |
    age -r "${recipient}" |
    ssh "${ssh_options[@]}" "${USER}@127.0.0.1" \
      "cat > '${work}/db-${run}.age.partial' && sync '${work}/db-${run}.age.partial' && mv '${work}/db-${run}.age.partial' '${work}/db-${run}.age'"
  age -d -i "${work}/age.identity" <"${work}/db-${run}.age" >"${work}/db-${run}.dump"
  test "$(sha256sum "${work}/db-${run}.dump" | cut -d' ' -f1)" = \
    "$(cat "${work}/db-${run}.source.sha256")"
  delta_bytes="$(python -c "import json; print(json.load(open('${work}/storage-${run}.json'))['delta_bytes'])")"
  transfer_generated "delta-${run}" "${delta_bytes}"
  test -s "${work}/db-${run}.age"
  test -s "${work}/delta-${run}.age"
  printf 'bundle=%s ack=BUNDLE_CAPTURED\n' "${run}"
  end_ns="$(python -c 'import time; print(time.monotonic_ns())')"
  docker run --rm --network host -e PGPASSWORD=carfast postgres:17-bookworm \
    psql -h 127.0.0.1 -U carfast -d carfast_test -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS ${restored}" -c "CREATE DATABASE ${restored}" >/dev/null
  docker run --rm --network host -i -e PGPASSWORD=carfast postgres:17-bookworm \
    pg_restore -h 127.0.0.1 -U carfast -d "${restored}" --no-owner --no-acl \
    <"${work}/db-${run}.dump"
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
