# Conventional Render-to-Green migration gate

Status: **PRE-WINDOW NO-GO**. This runbook is the only permitted conventional
path. It does not authorize a real capture. The custom Render transport and the
preseed/delta implementation are historical and must not be used here.

## Immutable scope

- Blue service: `srv-d8145e7aqgkc73al90ig`, release `58a150c7`.
- Green service: `srv-da5dk9bm8hqs73camds0`; release and database identity must
  be read back immediately before action.
- Regional SSH endpoint: `ssh.frankfurt.render.com`, with a freshly read-back
  pinned host-key fingerprint.
- Relay: dedicated GitHub Codespace in Europe West. It pipes ciphertext only;
  payload files, artifacts, ports, agent forwarding and payload logging are
  forbidden.
- PostgreSQL client/server major: 17. `pg_dump -Fc --no-owner --no-acl` and
  `pg_restore --exit-on-error --no-owner --no-acl`; never `--clean` against the
  permanent Green database.
- Encryption: pinned static `age` 1.2.1, SHA-256
  `7df45a6cc87d4da11cc03a539a7470c15b1041ab2b396af088fe9990f7c79d50`
  for the official release archive. The identity exists only on Green, mode
  0600; Blue receives only its recipient.
- Hard stop: restore Blue writes before 60 minutes. Operational abort starts at
  50 minutes, leaving ten minutes for recovery. No cutover, DNS or integrations.

## Closed pre-window gate

Every item must have machine-readable evidence and an independent PASS:

1. Read back exact Blue/Green IDs, releases, region, mounted storage roots,
   database hosts (host fingerprint only), and external-effect booleans.
2. Verify `age`, `pg_dump`, `pg_restore`, `psql`, `tar`, `sha256sum`, `timeout`,
   free bytes and free inodes on the exact instances and paths. No installation
   is permitted during the window.
3. Freeze nominal source and target manifests. Source must be exactly 162
   application relations. Target contract must be exactly 166. Explain any
   extra/missing relation and every non-empty target table against the seed
   contract. Current read-back (2026-08-24) is 167 public tables and about 490
   estimated rows on Green, so this item currently fails.
4. Prove one Alembic head and the ordered source revision -> `ffae1f2a3b4c` ->
   `fff37f8a9b0d` path, including the four additive relations, constraints,
   indexes, sequences, ownership, grants, search path and allowed seeds.
5. Provision a separate empty staging database/schema on the Green side with a
   tested rollback. Restore source 162 there, run Phase A tolerance-zero, and
   only then run Alembic to the target contract. Never restore with `--clean`
   over the permanent Green database.
6. Prove a single quiesce mechanism that blocks and drains web mutations,
   uploads/filesystem writes, email, jobs, webhooks, portals and integrations;
   enforce database read-only as an additional control. Record zero active write
   transactions and two identical storage manifests before setting `CUTOFF_UTC`.
   `default_transaction_read_only` alone is explicitly insufficient.
7. Rehearse the exact inverse operation before the window and install an
   independent watchdog that restores application and database writes no later
   than 60 minutes, even if the operator SSH session dies.
8. Reject symlinks, devices, FIFOs, sockets, absolute paths, `..`, mount crossing
   and unstable files. The storage snapshot records normalized path, size, mode,
   mtime and SHA-256, and two consecutive manifests must match while quiesced.
9. Prove capacity for DB ciphertext, storage ciphertext, decrypted restore and
   storage staging concurrently, plus safety margin and inodes.
10. Run the synthetic dry-run below on the same instances, users, binaries,
    mounts, SSH options and paths. Project measured throughput to complete capture
    and immutable validation before minute 50.

Any failed item is a pre-window NO-GO. No role, read-only mode or real stream may
be created or started.

## Exact synthetic dry-run

All variables are populated from read-back; secrets are never command arguments
or output. `SSH_OPTS` always includes `IdentitiesOnly=yes`, `ForwardAgent=no`,
`StrictHostKeyChecking=yes` and the dedicated pinned `UserKnownHostsFile`.

```bash
set -Eeuo pipefail
umask 077
BLUE=srv-d8145e7aqgkc73al90ig@ssh.frankfurt.render.com
GREEN=srv-da5dk9bm8hqs73camds0@ssh.frankfurt.render.com
: "${AGE_RECIPIENT:?read back from Green}"

# Synthetic bytes are generated on Blue, encrypted before stdout leaves Blue,
# piped by the relay, and persisted only as ciphertext in Green staging.
timeout 900 ssh ${SSH_OPTS} "$BLUE" \
  "set -Eeuo pipefail; python -c 'import sys; sys.stdout.buffer.write((b\"CarFastSynthetic\\0\"*1048576)[:16777216])' | /tmp/carfast-age -r '$AGE_RECIPIENT'" \
| timeout 900 ssh ${SSH_OPTS} "$GREEN" \
  'set -Eeuo pipefail; umask 077; mkdir -p /var/data/.migration-synthetic; cat > /var/data/.migration-synthetic/payload.age.partial; mv /var/data/.migration-synthetic/payload.age.partial /var/data/.migration-synthetic/payload.age'

ssh ${SSH_OPTS} "$GREEN" \
  'set -Eeuo pipefail; /tmp/carfast-age -d -i /tmp/carfast-integral.agekey /var/data/.migration-synthetic/payload.age | sha256sum; wc -c < /var/data/.migration-synthetic/payload.age'
```

The representative dry-run additionally uses synthetic PG17 source/staging
databases and a synthetic storage tree at least as large as the observed combined
footprint. It runs the real dump, encrypted transfer, `pg_restore`, Alembic,
Phase A/Phase B manifests, storage validation and cleanup. Three consecutive
runs are required; one must use full representative volume. Exit codes from both
SSH endpoints and every pipeline stage are captured separately. Stdout is payload
only; diagnostics go to sanitized stderr.

## Real action sequence (still gated)

1. Arm watchdog and verify rollback channel; create ephemeral SELECT-only role for
   the frozen 162-table list and prove writes/DDL/sequences denied.
2. Quiesce all application/filesystem writers, drain sessions, enforce DB
   read-only, then set `WINDOW_START_UTC`, `CUTOFF_UTC` and the 60-minute deadline.
3. Capture encrypted DB and storage streams into `.partial` files on Green staging.
   Bind sizes, ciphertext SHA-256, releases, bundle and cutoff in one manifest.
4. Validate both ciphertexts are complete and decryptable; validate the DB archive
   list and storage tar list without restoring. Only then emit the local
   `BUNDLE_CAPTURED` ACK.
5. Restore Blue writes immediately, record `WINDOW_END_UTC`, prove application
   write capability and remove the temporary role. Do not wait for Green restore.
6. Restore into empty Green-side staging. Phase A proves source 162 unchanged;
   Alembic creates the deterministic target; Phase B proves target relations,
   sequences, FKs/orphans/counts/digests. Materialize storage into a separate tree
   and compare path/size/mode/mtime/SHA-256 tolerance-zero.
7. Promote neither DB nor storage unless both validations PASS. On PASS, promote
   the reconciled DB and storage together and keep Green populated as the durable
   CarFast QA/future-production baseline, with every external effect still OFF.
   Blue remains production; this is not cutover authorization.

## Durable Green baseline and later cutover delta

The successful integral migration is reusable state, not a disposable rehearsal.
Persist a signed/versioned baseline report containing the common cutoff, Blue and
Green releases, source-162 and target-166 manifests, DB aggregate digests, storage
path/size/mode/mtime/SHA-256 manifest, Alembic path, reconciliation results and
external-effect booleans. Do not retain credentials or plaintext export artifacts.

At a separately authorized cutover, do **not** recopy the baseline storage. Quiesce
Blue under a new short cutoff, create a fresh standard PG17 logical dump, and build
a final Blue storage manifest with the same canonicalization rules. Compute:

- `copy = final paths absent from baseline OR metadata/hash changed`;
- `delete = baseline paths absent from final`;
- unchanged paths are never transferred.

Transfer copies with standard tar/age/SSH, materialize them into a clone/staging
tree, apply deletes only there, and atomically promote only after its complete
manifest equals final Blue tolerance-zero. Re-running the same copy/delete plan
against the same baseline/final pair must be a no-op and produce the same manifest
digest; interruption leaves only `.partial` files and is safely resumable. Renames
are deterministic delete+copy unless identical content-addressed reuse is proven.
The fresh DB restore and storage delta share the final cutoff and are promoted only
after full reconciliation. DNS, domain and integrations remain separate gates.

## Independent clean-installation output

The same immutable release must also produce a separate reusable clean-install
artifact exclusively through Alembic migrations, versioned reference/configuration
seeds and first-run onboarding. It must never derive from deleting or anonymizing
the migrated CarFast database.

Automated clean-install gates must prove the frozen 166-relation contract, one
Alembic head, bootstrap idempotence, module catalogue/selection and base permissions,
while all operational tables are empty. In particular there must be zero CarFast
vehicles, partners, processes, tasks, emails, documents/attachments, audit events,
operational users/credentials or other tenant data, and the storage root must be
empty. Only Core, the module catalogue, base permissions and strictly versioned
reference data are permitted by an explicit seed allowlist. The artifact is a
migration/seed manifest plus reproducible commands and evidence; creating another
permanent environment is a later cost gate.

## Rollback, stopping conditions and cleanup

- Missing/drifting inventory, writer, unstable storage manifest, unexpected
  relation/seed, non-zero pipeline RC, timeout, digest mismatch, insufficient
  space/inodes or any external effect causes immediate NO-GO.
- Failure after either capture restores writes via watchdog, removes partials and
  drops the role. Failure during restore deletes only the proven staging targets;
  permanent Green is not cleaned or overwritten.
- In NO-GO, remove Green synthetic/staging material. In PASS, retain only the
  promoted, reconciled Green baseline and its non-secret evidence; remove all
  staging/partial/export material. In both outcomes remove age identity and
  binaries, relay tmpfs material and repository public-key file; revoke only the
  named Render key; delete the dedicated Codespace; prove Blue writable, Green
  unchanged, temporary resources absent and ledger within the approved ceiling.

## Current gate result

Pre-window **NO-GO** until the 167-vs-166 and ~490-row Green discrepancies are
classified, the separate staging/rollback is proven, common DB+filesystem quiesce
and watchdog are implemented, and the exact full-volume synthetic dry-run passes
independent review. Blue remains writable and no real payload has started.
