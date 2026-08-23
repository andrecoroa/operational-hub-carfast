# Integral blue-green rehearsal gate

## Current evidence

- PR #24 was accepted and merged only into `integration/modular-architecture` at
  merge commit `657b5dfbaa3aece57fbda394b11e376fc611a5ef`.
- The real eight-table pilot reconciled `9/3/536/184/668/43/2714/5042` rows and
  reported zero orphans in the four measured relationships.
- The temporary role, services, PostgreSQL, environment and project were removed.
- Blue remained live at `58a150c701221b64c43bd14fcb671683f3722ebe` and permanent
  Green remained healthy and independently live at
  `8b34e913fc5b40e2b4363a9eb918c0b7300efb70` after the merge.

The pilot is accepted evidence for the transfer controls, not evidence that the
integral migration is reconciled.

## Integral release inventory

The current model declares **166 relations**. This supersedes the earlier 163-relation
inventory and is an intentional fail-closed gate: CI fails if the declared inventory
shrinks, and the rehearsal manifest fails if PostgreSQL has any missing or unexpected
application relation.

For every relation, `build_integral_reconciliation_manifest` records only aggregate
evidence:

- ordered full-row SHA-256 across every column and every row;
- ordered primary-key SHA-256 and exact row count;
- schema SHA-256 including column order/type/nullability, PK and FK definitions;
- exact orphan count for every declared FK, including composite keys.

For storage, the manifest contains the complete relative path set, byte size and SHA-256
of every regular file. Symlinks, special files, duplicate/unsafe paths, truncation,
unexpected trailing bytes and digest mismatches fail closed. Import occurs only into an
empty staging root and any failure empties that staging root.

`compare_integral_reconciliation_manifests` has zero tolerance: release SHA, relation
evidence and storage evidence must be byte-for-byte equivalent. It emits no row values or
file contents.

## Synthetic and clean-install gates

The isolated CI now performs:

1. empty PostgreSQL migration base-to-head, bootstrap and clean-install validation;
2. classification of all 166 tables: 16 versioned reference/configuration relations and
   150 relations that must remain empty;
3. synthetic full PostgreSQL clone using PostgreSQL 17 `pg_dump -Fc | pg_restore` in one
   transaction;
4. binary storage streaming into a separate empty staging root;
5. independent source/target integral manifests and zero-tolerance comparison;
6. adversarial tests for relation/count/row/FK drift, orphan detection, release mismatch,
   storage traversal, truncation, digest mismatch and rollback.

These gates use only test databases ending in `_test`, fixture objects and an internal
Docker network. They neither connect to Blue/Green nor contain production credentials.

## Exact future gate: first integral Green rehearsal

This section is a request boundary, not current authorization.

### Proposed window and cost

- reserve a two-hour controlled window in Frankfurt;
- make Blue application writes read-only for up to **20 minutes** while acquiring the
  common PostgreSQL/storage source cut;
- keep Blue serving reads; restore normal Blue writes immediately after the source cut is
  sealed and fingerprinted;
- create one temporary Standard private source worker pinned to the approved integration
  release for no more than two hours: estimated incremental compute **at most US$0.08**
  before tax at the current US$25/month rate;
- use the already-paid permanent Green PostgreSQL/disk capacity; no extra persistent
  storage is proposed. Abort before creation if Render presents any other paid SKU.

### Required authorization

The gate must explicitly authorize all of the following together:

1. manual deploy of one green integration release to permanent Green, Auto-Deploy still off;
2. a temporary Blue database login with `CONNECT`, schema `USAGE` and `SELECT` only across
   the complete, frozen 166-relation manifest; no writes, DDL, sequences, default privileges
   or role-management capability;
3. the short Blue application read-only interval needed for one consistent database and
   storage cut;
4. private, authenticated, single-use streaming of the full PostgreSQL archive and storage
   archive into Green staging; no public endpoint, redirects or intermediate persistent file;
5. replacement of the currently empty Green database/storage only after source evidence is
   sealed, while email, jobs, webhooks, portals, integrations and external tokens remain off;
6. immediate destruction/revocation of the source worker, login, HMAC material and any
   incomplete Green staging after reconciliation.

### Execution and no-go rules

1. Pin source, destination and evidence tooling to the same approved release SHA.
2. Reconfirm Blue/Green resource IDs, private database hosts and empty Green target.
3. Prove source SELECT succeeds and INSERT/UPDATE/DELETE/DDL/sequence access fail.
   After restore, reconstruct Green-owned integer primary-key sequences only from
   target table maxima; source sequence state is never read, and the next generated
   key must be collision-free before reconciliation is accepted.
4. Enter Blue read-only; acquire PostgreSQL repeatable source cut and storage manifest;
   no concurrent source object mutation is allowed during this cut.
5. Stream PostgreSQL with PostgreSQL 17 custom format and transactional restore. Stream
   storage through the validated framed protocol into an empty staging root.
6. Run Alembic to the pinned release head only if the copied source precedes that head.
7. Build independent source/target manifests and require all 166 relations, every FK orphan
   count, every PK/row/schema digest and every object path/size/hash to match exactly.
8. Run focused workflow, authorization, document-readability, clean-install and effects-off
   regressions. Keep Green inaccessible through the primary domain.

Abort and roll back Green staging on any schema drift, missing/unexpected table or object,
orphan, count/digest/hash mismatch, broken stream, write-capable source role, external effect,
unexpected cost or unexplained timing difference. Tolerance is zero.

### Rollback

- Before source cut: destroy the temporary worker/role; Green stays at the known empty release.
- During transfer: terminate both streams, drop the incomplete Green database/staging root,
  recreate Green from migrations plus versioned clean seeds, and prove the clean manifest.
- After a reconciled rehearsal: keep Green isolated for validation; Blue remains the production
  system. No DNS, production merge or cutover follows without a separate gate.

No real database row, document, attachment or storage object may be copied under the current
authorization.
