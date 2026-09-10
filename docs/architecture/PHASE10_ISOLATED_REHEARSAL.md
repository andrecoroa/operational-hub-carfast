# Phase 10 — isolated technical rehearsal checkpoint

## Authorized rehearsal

This branch prepares and executes only the reusable clean-install path against disposable test infrastructure. The executable guard requires `APP_ENV=test`, a local PostgreSQL hostname and a database name ending in `_test`. It refuses production mode, remote hosts and non-test database names before opening a database connection.

The CI sequence remains: create isolated PostgreSQL, apply the unique Alembic head, downgrade/upgrade, seed only versioned reference/configuration data, assert all operational tables are empty, then emit a machine-readable reconciliation report. Synthetic unit evidence also verifies unexplained count deltas fail and that document object accessibility, byte size and SHA-256 remain stable.

## Reconciliation expected in CI

- Alembic: one head (`fff37f8a9b0d`) and reversible upgrade/downgrade cycle.
- Clean installation: every table listed in `OPERATIONAL_TABLES` remains at zero rows.
- Reference seed: module catalogue exists and is stable across the read-only check.
- Objects: synthetic-only hash/size/accessibility checks; no CarFast document is read.
- Application: the existing clean-bootstrap and modular test matrices remain green.

This is not the CarFast-data migration rehearsal. Counts and hashes for real documents, processes, tasks, emails, users, permissions, events and audit cannot be produced without later authorization for an isolated anonymized copy and its corresponding storage snapshot.

## Rollback

The preparation is code-only. Rollback is removal of the report primitives, guarded script, CI command and tests. The disposable CI database is destroyed with the GitHub runner. There is no migration, seed change, external storage write or dual-write.

For a future CarFast rehearsal, rollback must be rehearsed as restoration of both the PostgreSQL snapshot and the matched immutable document-storage snapshot. Database and object storage checkpoints must share one cut-off identifier; partial rollback is prohibited.

## Risks

1. Synthetic data cannot reveal undocumented production-only values or hidden route consumers.
2. Object reconciliation is only meaningful when database metadata and storage are captured at the same cut-off.
3. Workshop legacy/phased dual storage needs explicit process-level mapping before real rehearsal.
4. External email/webhook/jobs must remain disabled or sandboxed to prevent side effects.
5. Performance results from CI are not representative of production volume.

## Decision required before the next step

Strategy must explicitly approve all of the following before a CarFast-data rehearsal: an anonymized PostgreSQL copy, a matched isolated document-storage copy, access controls and retention period, a non-production execution environment, secrets/sandbox integrations, responsible reviewers, reconciliation tolerances and rollback checkpoint. Any paid staging resource also requires approval.

No staging, real-data access, secret, production migration, Render action, deploy or merge proposal to `v2/production` is included or requested here.
