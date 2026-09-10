# Phase 9 — controlled legacy consolidation

## Outcome

This slice consolidates the five real manifests into one validated, read-only catalogue, routes canonical authorization decisions through the existing exact legacy adapters, formalizes the gated post-action decision and versions the active compatibility inventory. It removes no legacy surface and changes no runtime route, permission, data or composition default.

The full catalogue exposed one accidental manifest spelling mismatch (`service-desk` versus the approved `service_desk` code). Correcting the declaration makes the cross-module dependency machine-valid without changing activation or runtime behavior.

## Active legacy and duplication inventory

| Surface | Classification | Conceptual owner | Current compatibility | Exit evidence required |
|---|---|---|---|---|
| `stock_suppliers` and its FKs | adapter | Partners | `PartnersFacade`, stable partner reference, unchanged table/IDs | complete ID/link reconciliation for every consumer |
| document legacy workflow status | adapter | Documents | derived multidimensional state | state differential, retention/legal approval |
| `email_intakes` family | adapter | Service Desk | inbound compatibility feeding canonical email lifecycle | message/attachment/hash reconciliation; zero unexplained writes |
| Task/Process/Email legacy routes/templates | historical reader | Service Desk | current URLs and authorization remain | telemetry, post-action parity, functional approval |
| `workshop_processes` versus phased Workshop | adapter/duplication | Automotive | both stores remain writable by their current flows | process, phase, responsible, dates, actions and history reconciliation |
| Fleet/Workshop/Sales legacy routes/templates | historical reader | Automotive | unchanged URLs and experience gate | telemetry and equivalent gated destination |
| legacy permission aliases | adapter | Core | canonical policy dispatcher maps exact grants; default deny | profile-by-profile differential with zero access delta |
| Clean and legacy navigation | adapter | Core | legacy composer remains default | gate-off snapshot equality and authorized gate-on parity |

No surface is classified as safe to remove. `historical_read_only` describes the target retirement posture, not a write freeze applied by this PR. Freezing existing writes would alter active flows and therefore remains a later, individually approved operation after telemetry and reconciliation.

## Ownership and acoupling still active

- Physical supplier storage remains named and linked under Stock although Partners owns identity.
- Documents still contains compatibility workflow semantics and cross-domain vehicle links.
- Service Desk has intake/canonical email and legacy/Clean route pairs.
- Automotive has two Workshop process generations and a large shared web router.
- Navigation and permission composition still originates in legacy runtime structures; manifest composition remains gated off by default.

The new `CANONICAL_REGISTRY` proves all declared dependencies together and supplies one inventory for future navigation/Admin/settings/jobs composition. `decide_canonical_permission()` centralizes adapters but is not wired into effective access in this phase. `decide_post_action()` returns the current path while disabled and only accepts signed internal ReturnContext destinations when explicitly enabled.

## Reversibility and gates

- Code-only rollback; no Alembic revision or operational-data operation.
- Existing `MODULAR_COMPOSER_ENABLED` behavior remains legacy by default.
- Post-action consolidation is opt-in per caller (`enabled=False`).
- Existing URLs, tables, IDs, FKs, documents, history and audit remain unchanged.
- Export command: `python -m scripts.export_legacy_inventory`; it reads only the versioned catalogue.

## Remaining risks and decisions

1. Workshop dual storage is the highest preservation risk and needs a synthetic reconciliation harness before any write freeze.
2. Route usage cannot be inferred from code; retention windows require approved telemetry, never production-data access in this phase.
3. Permission aliases cannot be retired until all real profiles pass a differential evaluation on an authorized, anonymized dataset.
4. No removal proposal is valid without functional/legal approval per individual candidate.

The next authorized step is Phase 10 as an isolated technical rehearsal using synthetic data and a clean installation only. It must stop before real data, paid staging, secrets, production migration or any proposal to merge into `v2/production`.
