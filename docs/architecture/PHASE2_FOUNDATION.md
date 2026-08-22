# Phase 2 — Characterization and composition foundation

## Scope and invariants

This slice starts at `integration/modular-architecture@0491b84d`. It does not move
or refactor a real module. Existing routers, UI, authorization, navigation and
post-action behaviour remain operational.

- `MODULAR_COMPOSER_ENABLED=false` by default.
- The legacy composer is returned unchanged while the gate is off.
- The policy adapter returns exactly legacy permission-set membership.
- The manifest proof uses only the fictitious `technical_probe` defined by tests.
- Core imports no fictitious or real domain module through the platform package.
- No operational data is read or migrated; tests use empty PostgreSQL and synthetic objects.

## Frozen baseline

`scripts/capture_architecture_baseline.py` records deterministic counts and hashes
for routes, permissions, legacy aliases, navigation composition, redirects, form
actions and SQLAlchemy tables. It contains no record values or secrets.

```bash
python -m scripts.capture_architecture_baseline
python -m scripts.capture_architecture_baseline --check
```

Any drift requires explained review; updating the JSON is not an automatic fix.

## Additive catalogue and reversibility

Migration `fff37f8a9b0d` adds `module_definitions`, `module_capabilities`,
`module_dependencies` and `installation_modules`. Only `available`, `active`,
`disabled` and `retiring` are accepted. It inserts only the mandatory technical
`core` catalogue/state rows, does not infer a business module and touches no
operational row.

Before the feature gate is enabled, behaviour is independent of these tables.
Downgrade drops them in dependency order, removing only the new technical rows.
CI must prove upgrade, downgrade to `ffae1f2a3b4c`, re-upgrade, unique head and
model/schema compatibility on isolated PostgreSQL.

## Compatibility APIs

- `ModuleManifest` is immutable and validates capabilities/dependencies.
- `ManifestRegistry` is explicitly constructed and read-only after creation.
- `compose()` returns legacy output unless explicitly gated.
- `PolicyDecision` supplies a common UI/server result; this slice exposes only the
  legacy adapter, leaving effective access unchanged and denying missing grants.

No HTTP endpoint or visible UI is added.

## Remaining risks and approvals

Real-module manifests, enabling the composer, anonymized data, staging, production
rehearsal, effective permission changes and legacy removal require later approval.
`installation_key="default"` reflects one installation per company; a future
installation identity table needs a separate proposal.
