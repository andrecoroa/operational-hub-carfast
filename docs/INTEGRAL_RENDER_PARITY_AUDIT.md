# Integral migration: closed CI-to-Render parity audit

Status: **no real-data attempt is permitted by this document**.  Immutable code,
API payloads and evidence must be reviewed again at the action-time gate.

Canonical container command: `umask 077 && exec /opt/carfast-venv/bin/python -m
scripts.integral_render_entrypoint`, with the base image pinned by digest.
Canonical topology file: `render.integral.yaml`. Direct execution of the historical
Render shell script or the internal E2E worker is rejected with exit code 64.

## Fixed release contract

The next synthetic evidence release is the commit that contains this document and
passes both PR checks.  Sender and receiver use the same image digest and commit.
The source contract is 162 application tables; the deterministic target contract is
166 relations after Alembic `ffae1f2a3b4c -> fff37f8a9b0d`.  The common bundle contains
independent AES-GCM database and storage spools and is accepted only after both final
sizes, hashes, authorization, bundle ID, cutoff and release agree.

## Requirement-to-evidence matrix

| Requirement | CI/synthetic value | Observed Render value | Difference | Closed control | Required evidence |
|---|---|---|---|---|---|
| Creation | Docker/service fixtures | Render API resources | CI never exercises API defaults | Versioned exact request + read-back allowlist/SKU/region/disk/commit/autodeploy | Sanitized request hash and read-back JSON |
| PostgreSQL exposure | Docker private network | Per-resource API field returned `ipAllowList: null` after requesting `[]`; external libpq refused | Representation differs | Require request `ipAllowList: []`, read back no entries, external connection must fail, internal must pass; abort+delete otherwise | API response, failed external probe class, successful internal `select 1` |
| Private DNS | Docker alias | Internal hostname `dpg-…-a` resolves only privately | DNS implementation differs | Bind exact read-back internal host in manifest/authorization and reject every alternative | Receiver DNS/host fingerprint and connection result |
| Region/network | Local bridge | Frankfurt private network | Different routing/egress | Both temporary resources Frankfurt; receiver never receives Blue URL; destination host/port closed claims | API read-back and config fingerprint |
| Image/release | CI-built checkout | Digest-pinned PG17/Python Docker image | Render builds the same Dockerfile | Pin commit and base digest; record Python, requirements, entrypoint and executable version fingerprints before listener | Runtime preflight JSON |
| PG tools/driver | PostgreSQL 17 container | Native image toolchain was not fully evidenced in the failed real preflight | Known parity gap | Require `pg_dump`, `pg_restore`, `psql`, server all major 17; psycopg v3 URL; exact command/flag hash | `--version` hashes and command fingerprint |
| User/umask | CI container user | Render process user; managed secret mount not mode 0600 | Confirmed mismatch | Start with `umask 077`; record uid/gid; managed source is read once, never consumed directly | uid/gid/umask and private-file stat evidence |
| Managed secret | CI creates mode 0600 file | Render mount permissions triggered `permissions are too broad` | Confirmed cause | Accept only allowlisted regular, non-symlink source owned by root/process and not group/other-writable; copy once to process-owned 0700 tmpfs directory and 0600 file; validate fingerprint/closed claims there; unlink in `finally` | Adversarial tests plus sanitized source/private stat classes and absence proof |
| Secret transport | Local env/file creation | Web Shell bracketed paste previously contaminated input | Confirmed cause | API-created secret file only; no shell/paste; URL parser rejects markers/control/whitespace/unknown host/database; HMAC/auth fingerprints only | Negative tests and matching sender/receiver fingerprints |
| Filesystem | Temporary CI paths | 5 GB persistent disk at `/var/data`; `/dev/shm` ephemeral | Capacity/lifecycle differ | Secrets only in `/dev/shm/carfast-integral`; spools/tombstone on `/var/data`; verify mount types, ownership and free bytes | statvfs/mount-class evidence, no path contents |
| Capacity | CI full run 1,256,277,934 bytes | 5 GB disk | Runtime disk accounting differs | Declared total >=1.17 GiB plus 128 MiB margin before listener; check again before each spool | declared/free/max evidence |
| Start/health | Shell/CI process | Render probes and deploy lifecycle | Different supervision | One fixed exec path; health listener is separate and never signals migration readiness; no command mutation after deploy | command hash, health/process state |
| Restart/one-shot | CI exits once | Render may restart failed service | Replay risk | Durable `/var/data/carfast-integral-one-shot.state` created before consuming authorization; any existing state serves health only and cannot open listener/stream | restart adversarial and tombstone read-back |
| Environment/config | CI explicitly exports values | API/env injection can omit/drift values | Confirmed missing-variable class | Closed manifest; reject missing/unknown/drifted claims and mismatched HMAC snapshots before material resources/role/read-only/listener | sender/receiver config SHA-256 equality and all omission mutations |
| Authorization | Synthetic fixture | Real signed one-use claim | Mode difference | Synthetic has `REAL_DATA_ALLOWED=false`; real rehearsal requires <=15-minute signed ID bound to source/destination/release/bundle/cutoff and replay state | adversarial authorization suite |
| Database ownership | Fixture owner | Temporary DB user/owner | Must be discovered | Preflight requires empty DB, current role owns DB, DB/schema CREATE true, search path exactly `public` or `$user,public` | SQL aggregate preflight |
| Dump/restore | Real PG17 CLI in E2E | Same commands required | Render flags had not all executed after latest config | Hash exact argv; custom-format dump; no `--clean`; restore staging only; sanitized rc/duration/stderr fingerprint | command fingerprint and restore evidence |
| Migration/reconcile | Real Alembic and fixtures | Same release/staging required | None accepted without full proof | Phase A zero tolerance on 162; Alembic to 166; four-additive contract; sequences; manifests/FKs/orphans/storage hashes | aggregate manifests and comparison results |
| TCP/bundle | Real TCP adversarials locally | Render private TCP/proxy lifecycle | Reset/ACK behavior historically differed | Two independent framed spools; authenticated `BUNDLE_SPOOL_ACCEPTED` only after both finals; half-close; timeouts; final result separate | reset/truncation/replay/reorder/ACK-loss tests |
| Deadlines/cancel | Unit/integration deadlines | Render scheduling/network may delay | Timing differs | Fixed connect/read/bundle/consumer/join deadlines; cancellation closes sockets/pipes and kills child process group | duration evidence and no-live-child proof |
| Memory | Local host | Starter memory | Different limit | Streaming bounded frames; no plaintext bundle in memory; record cgroup limit/peak; abort before stream if below fixed minimum | cgroup limit and peak RSS |
| Cleanup | pytest/temp cleanup | API deletion and persistent disk | Cloud deletion is separate | On any outcome: close streams, kill children, remove secret environment references and cryptographic key objects, remove private copy/spools/staging, revoke auth/key, delete worker+disk+DB, verify 404/absence | cleanup checklist and API/UI read-back |

## Historical causes and preventive proof

| Confirmed cause | Prevention | Test/evidence required |
|---|---|---|
| Source 162 was incorrectly compared directly with target 166 | Two-phase 162→162, Alembic, explicit four-additive 166 contract | Missing/extra relation, column, seed and revision negatives |
| HTTP/proxy transport reset on representative payload | Private framed TCP, encrypted spool-first, half-close and authenticated two-phase ACK | >=1.17 GiB plus reset/truncation/ACK-loss tests |
| Socket-only destination topology was not executable on Render | Managed temporary PG17 on private DNS with no public allowlist | API read-back, external fail/internal pass |
| Receiver discovered missing `INTEGRAL_EXPECTED_DATABASE_HOST` at runtime | Closed symmetric configuration manifest | Every required claim removed or changed aborts before listener/material effects |
| Web Shell paste introduced bracketed-paste bytes | API secret injection only; strict base64/URL parsing | paste markers, newline, truncation, quoting, encoding and host alteration negatives |
| Restore/target contract failures were discovered after transfer | Non-consuming PG17/ownership/search-path/empty-schema/command preflight and real synthetic restore | Real negative and positive pg_restore; 162 and 166 validators |
| Sender could hang after consumer/ACK failure | Shared cancellation, socket/pipe close, child termination and deadline joins | negative consumer, lost/duplicate ACK, defunct-child and timeout tests |
| Completed one-shot workload could restart | Durable tombstone checked before listener or authorization consumption | restart twice; second process proves no socket/stream |
| Render-managed secret file permissions differed from CI mode 0600 | One-read managed-source bootstrap into private 0600 tmpfs copy | broad-readable immutable source passes; writable/symlink/special/owner mismatch fails; copy absent afterward |

No claim that all runtime problems are known is valid until the full-scale Render
proof below passes with every evidence cell populated.

## One secret mechanism

Use a Render secret file created only by API at
`/etc/secrets/integral-envelope.json`.  The start bootstrap fixes `umask 077`,
requires the source to resolve under `/etc/secrets`, rejects symlink/special files,
unexpected owner and group/other write bits, and copies it exactly once to a random
file below `/dev/shm/carfast-integral` (directory 0700, file 0600, process owner).
Only the copy is parsed and fingerprinted.  Closed claims, URL allowlist and signed
authorization are then validated.  The copy is unlinked in `finally`; secret values
are never printed.  Environment secrets are rejected as the primary path because
their exact lifecycle and accidental subprocess inheritance are less observable.

## Exact synthetic Render topology and runtime

- API-only PG17, Frankfurt, Basic-256mb, 1 GB, generated temporary DB/user,
  explicitly `ipAllowList: []`.
- API-only private service, Frankfurt, Starter, 5 GB disk at `/var/data`, pinned
  commit, Auto-Deploy off, no public URL, same repository release.
- No Blue/Green URL, credential, ID or network mutation is supplied.
- Start via one immutable script with `umask 077`; record uid/gid, Python and PG17
  executable fingerprints, psycopg version, mount classes, disk free, cgroup memory,
  env-name/boolean snapshot and closed config fingerprint.
- Health is a separate local process.  Migration readiness is never inferred from
  health.  Tombstone is durable and blocks every second execution.
- Database/search path/ownership/empty state, DNS, external refusal/internal success,
  deadlines and cleanup are preflight gates before opening the private listener.

## Stopping conditions

Abort, delete and report NO-GO on: request/read-back drift; any public DB access;
private DNS mismatch; release/config/HMAC/auth mismatch; unknown/missing claim;
managed-source violation; private copy residue; wrong uid/umask/tool/server/driver;
non-empty or wrongly owned staging; insufficient disk/memory; listener before all
preflights; restart without tombstone block; timeout/reset/replay/reorder/truncation;
missing or premature bundle ACK; subprocess surviving cancellation; any 162/166,
PK/FK/orphan/count/digest/sequence/storage difference; effect flag enabled; cleanup
residue; or projected cumulative technical ledger exceeding €5.

## Single full-scale synthetic proof specification

One action-time-authorized creation cycle uses the exact topology above.  It runs
all read-backs and adversarials first, then three consecutive logical E2E executions
inside the one worker lifecycle, with the final execution carrying independent DB
and storage streams totaling at least **1,256,277,934 bytes**.  It executes real
PG17 dump/restore, Phase A 162, real Alembic to 166, sequences and zero-tolerance
manifests; exercises reverse stream order, absent/duplicate/mismatched bundle,
reset, half-close, trailing bytes, replay, ACK loss, consumer failure, disk/memory
preflight, restart/tombstone and cleanup.  Evidence is sanitized metadata only.

Estimated incremental cost for <=2 hours is conservatively below US$0.05 before
tax (PG $6.30/month + worker $7/month + 5 GB disk $1.25/month, prorated); invoice
and current Render pricing are authoritative.  The action-time gate must authorize
exactly one PG, worker and disk, secret/API-key creation and their irrevocable
cleanup.  Success authorizes only a readiness report, never a real-data attempt.
