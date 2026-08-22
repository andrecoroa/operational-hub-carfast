# CarFast modular target architecture

Status: **Phases 1–2 approved; Phase 3 visual/post-action slice in progress**

Baseline: `integration/modular-architecture` at `be2f5bce7ed6079e2135ce48111c209ed580760c`

Production baseline: Render remains at `58a150c701221b64c43bd14fcb671683f3722ebe`

This specification translates the approved structural diagnosis into an incremental modular-monolith target. It does not authorize code, schema, data or production changes.

## Reading guide

- [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md): logical/technical architecture, module catalogue, composition, contracts, permissions, Administration, visual system and post-action behaviour.
- [ENTITY_OWNERSHIP.md](ENTITY_OWNERSHIP.md): current table inventory, proposed ownership, dependencies and legacy classification.
- [MIGRATION_AND_ROADMAP.md](MIGRATION_AND_ROADMAP.md): separate CarFast/clean-install paths, tests, reconciliation, phases, reversibility, risks and acceptance gates.
- [PHASE2_FOUNDATION.md](PHASE2_FOUNDATION.md): frozen baseline, compatibility APIs, additive catalogue and reversal path.
- [PHASE3_VISUAL_FOUNDATION.md](PHASE3_VISUAL_FOUNDATION.md): gated visual primitives, signed ReturnContext, representative slice and migration gates.
- [PHASE4_PARTNERS_BOUNDARY.md](PHASE4_PARTNERS_BOUNDARY.md): Partners ownership facade, stable references, compatibility adapters and reconciliation.
- [PHASE5_DOCUMENT_MANAGEMENT_BOUNDARY.md](PHASE5_DOCUMENT_MANAGEMENT_BOUNDARY.md): document ownership facade, ingestion/link contracts, object reconciliation and standalone composition.

## Statement labels

- **FACT** — observed in the current repository or production baseline.
- **DECISION** — explicitly approved by Strategy.
- **RECOMMENDATION** — technical target proposed by this specification.
- **HYPOTHESIS** — must be validated through characterization or implementation evidence.

## Architectural invariants

1. One independent installation per company.
2. A shared codebase and Alembic chain create both CarFast and clean installations.
3. The target starts as a modular monolith with one PostgreSQL database.
4. Core never imports an operational module.
5. Modules contribute navigation, Administration, permissions, settings and jobs declaratively.
6. Cross-module writes occur through explicit application contracts; direct table mutation is forbidden.
7. Disabling a module never deletes its data or historical evidence.
8. Documents, attachments, tasks, processes, email, links, users, permissions, events and audit history are preserved.
9. A clean installation is created from migrations and explicit seeds, never by cleaning production.
10. Visual and post-action contracts are transversal release gates.

## Scope boundary

Current modules are Core, Service Desk, Document Management, Automotive & Fleet, Stock & Purchasing, and Partners & Suppliers. Administration is a composition surface. WhatsApp, Webex, portals and AI are used only as extensibility tests; no requirements for those capabilities are defined here.

## Deliverable traceability

| Required deliverable | Primary section |
|---|---|
| 1. Logical/technical architecture | Target Architecture §§1–4 |
| 2. Entity/table ownership | Entity Ownership §§2–3 |
| 3. Current/allowed dependencies | Entity Ownership §4 |
| 4. Contracts/references/events/degradation | Target Architecture §§7–8 |
| 5. Module catalogue/configuration | Target Architecture §5 |
| 6. Declarative composition | Target Architecture §6 |
| 7. Permission matrix | Target Architecture §9 |
| 8. Administration taxonomy | Target Architecture §10 |
| 9. Visual system | Target Architecture §11 |
| 10. Post-action contract | Target Architecture §12 |
| 11. Legacy strategy | Entity Ownership §§5–6; Migration §5 |
| 12. CarFast migration/clean bootstrap | Migration §§1–2 |
| 13. Tests/reconciliation | Migration §3 |
| 14. Incremental roadmap/risks/acceptance | Migration §§4–7 |
| 15. Decisions before code | Target Architecture §14; Migration §8 |
