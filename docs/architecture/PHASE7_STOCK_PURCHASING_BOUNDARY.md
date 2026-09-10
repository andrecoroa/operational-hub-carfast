# Phase 7 — Stock & Purchasing boundary

Status: reversible slice on `integration/modular-architecture`; no production deployment.

## Preserved facts

- Articles, locations, immutable movements, costs, minimums, inventories, invoice imports, receipts,
  purchase orders, delivery documents and discrepancies retain their existing tables, IDs and links.
- `stock_suppliers` remains compatibility storage, but partner resolution is performed by the Partners
  facade. Stock does not acquire partner identity ownership.
- Document metadata/audit writes for invoice intake and validation pass through Documents contracts.
- No quantity, cost, object, document, supplier, order or movement is migrated or rewritten.

## Boundary and optional Workshop integration

`app.stock_domain` provides stable references, a ledger facade, balance snapshots, canonical permissions
and a real manifest. Its required dependencies are Core, Partners and Documents; Workshop is absent.

Workshop material requests are isolated in `stock_domain.workshop_adapter`. The Stock package does not
import that adapter. The current UI may use it when Workshop is available; Stock ledger, purchasing,
inventory and invoice operations remain usable without importing Workshop domain models.

Delivery remains the single moment that records the Stock exit. The adapter then returns the movement
reference and cost snapshot to the Workshop need. This preserves the existing transaction boundary and
does not create dual writes outside the current database transaction.

## Reconciliation and reversibility

Synthetic tests prove exact ledger balance before/after reversal, stable mapper/table identity, current
FK targets, Partners/Documents contract usage, manifest composition without Workshop and default-deny
permission mapping. Existing Stock MVP and final-reorganization suites remain green.

Rollback is code-only: the web adapter and facades delegate to existing services/tables. No migration or
data downgrade exists.

## Remaining work

- characterize each Workshop material status and failed-delivery rollback path;
- move remaining UI/API Stock mutations behind the facade incrementally;
- introduce a versioned material-request DTO before Automotive extraction;
- reconcile location and cost restrictions across every permission combination;
- preserve external references when Workshop is disabled and show authorized history read-only.

No item authorizes negative-stock semantics changes, supplier cleanup, data migration or legacy removal.
