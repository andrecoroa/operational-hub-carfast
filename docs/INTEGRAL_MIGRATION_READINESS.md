# Integral migration readiness gate

Status: **REAL REHEARSAL SUSPENDED**. No Blue role, read-only window, or real payload is permitted until every item below is evidenced on one immutable commit and configuration.

## State machine

| State | Entry evidence | Success transition | Fail-closed action |
|---|---|---|---|
| Preflight | release/config fingerprints; `source-staging`; HMAC snapshot; Python and PG tools; staging ownership/grants/search path; disk; listener/probe | temporary source role | no Blue mutation |
| Source role | LOGIN, CONNECT, USAGE, SELECT on exactly 162 relations; write/DDL/sequence denials | Blue read-only | revoke/drop role |
| Blue read-only | timestamp and verified write denial; reads remain available | concurrent DB/storage dump | restore writes, cancel bundle |
| Dump and spool | common bundle/cutoff/release; two AES-GCM spools; final sizes/digests/auth | `BUNDLE_SPOOL_ACCEPTED` | close sockets/pipes, terminate children, clean spools |
| Bundle accepted | both spools complete and coherent | Blue writes on | restore writes before consuming |
| Blue writes on | timestamp and verified application write capability | Phase A restore | no further Blue access |
| Phase A | empty isolated staging owned by staging role; real `pg_restore`; 162 inventory | source manifest | drop staging on failure |
| Source manifest | schema/PK/FK/count/digest/orphan equality | Alembic | drop staging on difference |
| Alembic | `ffae1f2a3b4c -> fff37f8a9b0d`; exactly four additive relations | sequences | drop staging on failure |
| Target reconcile | 162 preserved; additive contract; 166 target; storage paths/sizes/SHA-256 | rehearsal success | no promotion; clean staging |
| Cleanup | worker, staging, role, HMAC, spool absent; keys zeroed | readiness evidence | gate remains closed if any residue |

## Immutable runtime inventory

Evidence must record values, never secrets or payloads:

- commit/release and configuration fingerprint;
- Python version; `pg_dump`, `pg_restore`, `psql`, and PostgreSQL server major (all PG tools/server major 17);
- exact argv flags (password excluded), destination database identity, database/schema owner, effective grants, `search_path`;
- filesystem mount/type, free bytes, spool maximum and margin;
- private listener/health ports, probe type/path, deploy/restart lifecycle and all timeouts;
- HMAC snapshot SHA-256 equality between deployed receiver and sender, without exposing the key.

## Rehearsal evidence required

- Exact 162-relation schema derived from the pinned source release/schema-only metadata; relational synthetic fixtures only.
- Real `pg_dump -Fc`, real `pg_restore`, real Alembic, real manifests/reconciliation.
- Synthetic storage >= 1.17 GiB with representative nested paths, sizes and SHA-256 inventory.
- Three consecutive end-to-end green runs on the same commit/configuration; at least one on Render at full volume and representative duration.
- CI 2/2 green, all temporary resources removed, cumulative technical ledger conservatively below EUR 5.

## FMEA

| Failure | Detection before Blue read-only | Containment |
|---|---|---|
| invalid phase enum | exact `source-staging` preflight | stop before role/read-only |
| HMAC/config snapshot drift | deployed/sender fingerprints unequal | stop before role/read-only |
| PG binary/server mismatch | version and command smoke test | stop before role/read-only |
| staging ownership/grants/search path wrong | real negative+positive restore into equivalent empty staging | rebuild staging |
| partial/reset/truncate/trailing/replay/reorder | authenticated TCP adversarial suite | discard both spools |
| one bundle stream absent/mismatched | no common ACK | timeout, cleanup |
| lost/negative ACK | bounded client deadline | cancel, close sockets/pipes, terminate children |
| consumer/restore/Alembic failure | sanitized stage/rc/duration/stderr fingerprint | negative result, drop staging |
| subprocess/thread hang | cancel event and deadline joins | terminate/kill; gate fails |
| insufficient disk | declared totals plus safety margin | no listener acceptance |
| probe/restart collision | separate HTTP health listener and lifecycle rehearsal | fail deploy before Blue |
| schema/data/storage difference | zero-tolerance manifests | no promotion, cleanup |

## Final gate

A single final real rehearsal may be proposed only after this document is filled with three run IDs, immutable fingerprints, CI links, cleanup proof, durations and the cumulative ledger. It remains separate from cutover, DNS, integrations and production deployment.
