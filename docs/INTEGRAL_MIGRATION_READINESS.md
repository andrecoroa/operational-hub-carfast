# Integral migration: final readiness and real-rehearsal gate

## Contract v2 correction after the pre-Blue NO-GO

The immutable `3a5aa61f` attempt stopped before any Blue role, read-only window or
stream because schema v1 required `REAL_DATA_ALLOWED=false` unconditionally. Schema
v2 removes that contradiction without weakening the default:

- `mode=synthetic` requires `REAL_DATA_ALLOWED=false` and the exact sentinel
  authorization; it cannot consume an authorization or carry real data;
- `mode=real_rehearsal` requires `REAL_DATA_ALLOWED=true` plus a unique signed
  authorization ID, timezone-aware issue/expiry timestamps and a lifetime no longer
  than 15 minutes;
- the signature binds mode, authorization ID, source/destination service and database
  hosts, private destination host/port, release, bundle, cutoff and timestamps;
- sender and receiver use the same closed manifest and fingerprint. Each atomically
  consumes its role-scoped authorization marker before opening a process or socket;
- integrations, email, jobs, webhooks and portals must remain false. Cutover and
  production-deploy requests are closed false-only claims in both modes;
- missing/unknown/expired/drifted/ambiguous claims, bad signatures and replay fail
  closed. Non-consuming preflight precedes resource/role/read-only orchestration;
  the actual sender/receiver entrypoints perform the one-use consume.

Preventive tests cover every missing/divergent shared and role claim, unknown claims,
fingerprint drift, synthetic-with-real-data, valid signed real rehearsal, absent and
expired authorization, signature drift, replay, every external-effect switch and both
cutover/production switches. Transfer ordering tests prove rejection precedes dump
processes, listeners and staging writes.

Report closed: 2026-08-24, Europe/Lisbon. Status: **synthetic readiness accepted; real rehearsal closed pending one explicit authorization**.

## Immutable release and evidence

- PR #25 targets `integration/modular-architecture`.
- Executable release: `e4a545374e562678f7c60aab240617e3b70bba01` (`e4a54537`). This report may be added by a documentation-only successor, but executable files, image, commands and configuration remain byte-identical to `e4a54537`.
- GitHub reconfirmation: 2/2 checks green at `e4a54537`; no conflict reported by the PR UI. Reconfirm immediately before any merge. This report authorizes neither merge nor production deployment.
- Three consecutive isolated end-to-end runs passed on the same executable HEAD/config, using PostgreSQL 17, real CLI commands, real Alembic, manifests, TCP bundle handling and cleanup.
- Full-scale Render: private service `srv-da5oj9qjobas73fdhddg`, deploy `dep-da5ojaajobas73fdhge0`, Frankfurt, Starter plus temporary 5 GB disk at `/var/data`. Synthetic only; service and disk deleted after evidence.
- Lisbon timestamps: source `162 valid=true` 01:02:26; negative restore diagnostic 01:02:28; `BUNDLE_SPOOL_ACCEPTED` 01:02:52; consumer accepted 01:03:56; target `166 valid=true` 01:03:58; run green 01:03:59; cleanup verified 01:04:00. Contract interval: 93 s; bundle ACK to consumer result: 64 s.
- Synthetic storage: 1,256,277,934 bytes (>=1.17 GiB), reconciled by path/size/SHA-256 manifest.
- Cleanup: no worker, disk, database, role, HMAC, spool or staging remains. Blue stayed writable and untouched; permanent Green stayed untouched.

The frozen contract binds one `bundle_id`, cut-off, release, source, private destination, DB stream and storage stream. An authenticated bundle ACK is emitted only after both encrypted spools pass auth, final-frame, size and digest validation.

## Runtime and command inventory

| Control | Frozen requirement |
|---|---|
| Runtime | `.github/rehearsal.Dockerfile`; Python fingerprint recorded; `pg_dump`, `pg_restore`, `psql` and PostgreSQL server all major 17 |
| Dump | `pg_dump -Fc`; phase exactly `source-staging`; temporary role limited to LOGIN, CONNECT, USAGE and SELECT on exactly 162 relations; no sequences/write/DDL/ownership/default privileges/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS |
| Restore | `pg_restore --exit-on-error --single-transaction --no-owner --no-privileges`; data-only path adds `--data-only`; failure evidence contains only stage, rc, duration, stderr byte count and SHA-256 |
| Staging | empty isolated `carfast_integral_staging_*`; ephemeral role owns DB; schema CREATE available; initial public table count zero |
| Ownership/grants | target identity, owners and effective grants captured; production ownership/grants never imported |
| Search path | exactly `public` or `$user,public`, normalized and checked before Blue mutation |
| Migration | `ffae1f2a3b4c -> fff37f8a9b0d`; preserve 162 and deterministically add four relations to reach 166; sequences reset only in isolated target |
| Auth | random ephemeral in-memory key; equal 64-character sender/receiver HMAC snapshots; one-use nonce and exact bundle/source/destination/release/cut-off scope; key never logged and zeroed/removed |
| Network | exact private host/port; framed TCP with version, monotonic sequence, declared limits, frame auth/hash and final digest; replay/reorder/duplicate/trailing/truncation rejected; HTTP health separate |
| Deadlines | bounded connect/I/O/bundle/process waits; proven client/consumer 1,200 s and bundle 900 s; cancellation closes sockets/pipes and terminates/kills subprocesses |
| Disk | declared total plus >=128 MiB free; proven per-stream max 2,147,483,648 bytes; full-scale Render used bounded 5 GB disk because `/tmp` is 2 GB |
| Effects | integrations/email/jobs/webhooks/portals OFF; only a separately authorized source read path may be enabled |

## FMEA: causes, corrections and prevention

| Confirmed cause | Proved correction | Preventive gate |
|---|---|---|
| Invalid phase enum | enforce exact `source-staging` | preflight fails before role/read-only |
| v1 forced synthetic safety claim during a real gate | explicit mutually-exclusive v2 modes and signed short-lived real authorization | synthetic-real contradiction, expiry, signature, replay and effects/cutover adversarials |
| HMAC/config drift after restart | immutable equal fingerprints | mismatch test before role/read-only |
| Restore diagnostics discarded | sanitized stage/rc/duration/stderr-size/SHA | real negative restore every rehearsal |
| Sender hang after negative consumer | cancel event, socket/pipe close, bounded joins/process termination | negative consumer, lost ACK and restore failure prove no hang/residue |
| Sequence reset rejected valid isolated staging | gated isolated-target guard | positive/negative isolated target tests |
| Render private self-DNS failed in single-instance synthetic run | localhost only under explicit isolated flag | Render self-connect test; real private allowlist unchanged |
| Fixed 30 s join shorter than legitimate restore | configured bounded consumer deadline | delayed consumer passes; overrun fails closed |
| Render `/tmp` 2 GB exhausted | 5 GB temporary disk and explicit spool root | disk preflight plus full 1.256 GB Render run |
| Partial/reset/truncate/trailing/replay/reorder/duplicate | authenticated framed spool-first protocol | adversarial TCP suite discards both spools |
| Missing/mixed DB-storage bundle | coherent bundle state; ACK after both validate | missing/inverse/mismatched/reset-between-streams tests |
| Probe/restart collision | separate HTTP health listener | Render lifecycle rehearsal |
| Disk/decrypt/hash/restore/Alembic/reconcile failure | no consume before validation; negative result and target drop | failure tests plus cleanup assertion |

No known configuration is deferred until after read-only. Residual real-data and platform risks remain below.

## One final real rehearsal: exact runbook

1. Pin source, destination, image and configuration to executable `e4a54537`. Reconfirm PR HEAD, 2/2 checks, no conflicts and ledger headroom; abort on drift.
2. Create only an authorized private worker and empty isolated staging. Record IDs, Frankfurt placement, private host/port, disk/free space, health and projected cost. Do not touch permanent Green.
3. Before a Blue role or read-only: verify Python/PG CLI/server 17, argv fingerprints, `source-staging`, HMAC snapshots, scoped IDs, private endpoint, staging name/owner/grants/search path/zero tables, declared sizes, disk margin, probes, deadlines, cancellation and effects OFF. Run real negative `pg_restore` against empty staging. Stop on any failure.
4. Confirm exact Blue DB and frozen 162 inventory. Create ephemeral SELECT-only role; prove SELECT succeeds and INSERT/UPDATE/DELETE/DDL/sequence access fails. Revoke immediately on excess privilege.
5. Start Blue read-only clock only now; reads stay available and write denial is proved. Maximum 20 minutes.
6. At one cut-off, create PostgreSQL 17 custom dump and storage manifest/stream. Send DB and storage into independent AES-GCM spools sharing bundle/cut-off/release. Do not decrypt/restore yet.
7. Validate auth, finals, sizes and complete digests. Emit authenticated `BUNDLE_SPOOL_ACCEPTED` only after both streams are coherent. Missing/negative/lost ACK is no-go.
8. On verified ACK restore Blue writes immediately, timestamp and prove application writes, revoke/drop source role and destroy its credential. No further Blue access.
9. Decrypt only into staging. Phase A requires exact source-to-staging equality at 162 for schema/columns/PK/FK/counts/digests/orphans. Stage storage only at manifest paths and reconcile set/path/size/SHA-256.
10. Run Alembic exactly to `fff37f8a9b0d`, reset/verify sequences, preserve all 162 and validate the four additive relation contracts. Require exactly 166 and zero unexplained difference.
11. Emit separate authenticated final result. Do not promote staging, copy to permanent Green, change DNS, deploy/merge production, enable integrations or cut over.
12. Always zero keys, close sockets/pipes, terminate children, remove spools/partial storage, drop staging/role, delete worker/disk/token and prove absence by IDs. Retain sanitized aggregates only.

## Stopping conditions and rollback

Immediate no-go: fingerprint/version/target drift; unexpected cost/SKU; public exposure; excess privilege; write during read-only; read-only >20 minutes; auth/nonce/scope failure; missing/mixed/replayed/truncated bundle; size/digest/path mismatch; disk shortage; process/lifecycle deadline; restore/Alembic/sequence failure; relation count other than 162 then 166; any schema/PK/FK/count/digest/orphan/storage difference; external effect; or incomplete cleanup.

Rollback never mutates Blue data: restore writes, revoke/drop role, cancel transfer, discard both spools, drop staging, delete worker/disk/token, remove keys and leave permanent Green unpromoted. Blue remains production.

## Cost ledger

- Previously reported technical-test total before this closure: <USD 0.046.
- Four minute-scale Starter attempts and one short-lived 5 GB disk put the deliberately conservative cumulative ceiling at **<USD 0.10 (<EUR 0.10 before tax)**, below EUR 5. The posted Render invoice is authoritative.
- Plan one Starter private worker plus bounded 5 GB disk for at most two hours. Conservative incremental allowance: **EUR 0.10**; abort before creation if quote plus ledger could reach EUR 5. Permanent Green cost is excluded.

## Residual risks

- Real distribution, compression, long-tail objects and concurrency can differ from schema-exact fixtures; manifests and the 20-minute limit contain but cannot pre-eliminate this.
- Render scheduling, networking and billing may change; recheck placement, health, free space, quote and deadlines.
- Source schema is pinned to Blue release `58a150c7`; any later schema/config change invalidates the gate.
- Success proves migration integrity, not user acceptance, delta cutover, authentication acceptance, integrations, domain/DNS or production cutover; those remain separate gates.

## Operator plan and authorization

The synthetic Render command remains `sh scripts/run_integral_render_rehearsal.sh`. A real run starts only after `python -m scripts.preflight_integral_runtime` succeeds and then follows the numbered state machine. Capture commands, IDs and sanitized fingerprints; never record credentials, keys, payload or SQL. No compatibility edits and no `pg_restore --clean` against live Green.

**Authorization required:** “Autorizo uma única tentativa integral real final no HEAD executável `e4a545374e562678f7c60aab240617e3b70bba01`, segundo este runbook, com Blue read-only até 20 minutos, recursos temporários dentro do ledger total de EUR 5, sem cutover, DNS, integrações, produção ou promoção do Green.”
