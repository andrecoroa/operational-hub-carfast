# Phase 8 — Automotive & Fleet boundary

## Scope and ownership

`automotive` owns the stable vehicle identity and exposes Fleet, Workshop and Sales as independently permissioned capabilities. Existing `vehicles`, `workshop_*` and `vehicle_sale_*` tables remain compatibility storage; no table, foreign key, identifier, process or historical row is moved or rewritten.

Fleet source projections remain traceable to the immutable import/raw snapshot. Workshop process snapshots preserve vehicle reference, plate snapshot, state, phase, responsible person and operational dates. Sales keeps its separate lifecycle while referring to the same stable vehicle identity.

## Dependencies and degradation

The manifest declares Core, Documents, Partners and Service Desk. Stock is deliberately optional: Workshop may request materials through the existing Stock adapter, but Automotive discovery and Fleet operation do not import or require Stock. If Stock is inactive, material fulfilment is unavailable while the Workshop process and its historical snapshot remain readable to authorized users. Fleet and Sales do not require Workshop activation.

Documents own binaries and document workflow; Automotive owns the operational association. Partners own partner identity; Automotive stores only operational references/snapshots. Service Desk owns tasks and communications associated with Automotive references.

## Compatibility and reversibility

- Existing URLs, routers, permission checks and writes remain unchanged.
- Canonical `automotive.<capability>.<action>` decisions map to the exact legacy grants and default deny.
- The real manifest is declarative and remains behind the existing composer gate.
- The facade is read-only in this slice; rollback is removal of the new package/tests/docs.
- There is no Alembic migration and no data reconciliation is required beyond stable ID/snapshot characterization.

## Next controlled slice

Route priority read consumers through `AutomotiveFacade`, then introduce explicit Documents, Partners, Service Desk and optional Stock ports one consumer at a time. Only after differential tests prove equivalence should writes move behind commands. The legacy and phased Workshop models require an explicit reconciliation plan before either can be retired.
