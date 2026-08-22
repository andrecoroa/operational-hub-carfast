# Phase 4 — Partners & Suppliers compatibility boundary

Status: controlled implementation slice for review; no production change.

## Storage and ownership

**FACT:** partner identity, legal/display data and the historical primary contact/address
fields are stored in `stock_suppliers`. Contacts, addresses, classifications and module
roles already use that stable numeric ID. Email templates and Stock operational records
also reference it directly.

**DECISION:** Partners owns the identity concept. In this phase `stock_suppliers` remains
the physical compatibility storage and every existing foreign key, URL and numeric ID is
unchanged. `PartnerRecord`, `Supplier` and `StockSupplier` are aliases of the same SQLAlchemy
mapper; there is no copy, dual write or migration.

## Contracts

- `PartnerReference` is serialized as `partner:v1:<id>` and rejects unsupported forms.
- `PartnerSummary` is the minimal versioned query/snapshot payload for consumers.
- `PartnersFacade` owns live record lookup, filtered summary queries and authorized
  historical degradation.
- historical snapshots are returned only when the caller has Partners read authority;
  invalid snapshots fail closed.
- module-specific records keep their existing supplier ID and remain owned by their
  module (orders/articles by Stock, templates/threads by Email, documents by Documents).

The contracts leave extension points for a future read-only 360 view and versioned
import/export, but neither an editor nor an import framework is implemented here.

## Dependency change

Priority consumers now import the Partners compatibility boundary rather than declaring
the legacy Stock model as their conceptual owner:

| Consumer | Before | Phase 4 |
|---|---|---|
| Partners pages | `app.models.stock.StockSupplier` | facade + compatibility record |
| Email | Stock model import | Partners compatibility boundary |
| Stock web/application service | own identity model import | Partners compatibility boundary |
| bootstrap | Stock model import | Partners compatibility boundary |

Workshop and Documents did not import `StockSupplier` directly in the frozen slice. Their
existing document/workshop references remain untouched; future live partner lookups must
use `PartnersFacade`.

The ORM registration file `app.models.suppliers` retains a direct alias to the physical
storage model. Importing the application facade from the model layer creates a circular
dependency during metadata registration; this storage-level exception is explicit and is
not available to application consumers.

## Manifest, permissions and gate

The real `partners` manifest contributes records navigation, configuration Administration
and classification settings. Composition remains behind the existing
`MODULAR_COMPOSER_ENABLED` gate and legacy composition remains the default.

Canonical permissions use `partners.records.read|create|update|configure`. The adapter maps
them to the exact current legacy permission sets. Unknown permissions default-deny; no
stored grant or effective access changes in this phase.

Visual primitives are applied only to the touched Partners list/detail when
`VISUAL_FOUNDATION_ENABLED=true`; the default remains false.

Synthetic browser evidence at a requested 320 px viewport produced a 305 px document
client area after browser scrollbar allocation:

| Surface | Document scroll/client | Local component | DOM elements | Result |
|---|---:|---|---:|---|
| Partners list | 305 / 305 px | table 251 client / 852 scroll | 201 | no document overflow; table scroll is local |
| Partner detail | 305 / 305 px | summary layout collapsed to one 281.8 px column | 330 | no document overflow |

Evidence files are `evidence/phase4-partners-list-320.png` and
`evidence/phase4-partner-detail-320.png`. Only synthetic names, contacts and identifiers
were used.

## Reconciliation and rollback

Tests prove mapper identity, unchanged `stock_suppliers` storage, stable IDs, all current
foreign-key targets, route/link compatibility, permission equivalence, gated composition
and authorized snapshots. No Alembic revision is added.

Rollback consists of reverting the application imports/facade. There is no schema or data
rollback because no schema or operational data changed.

## Remaining coupling and next slice

Physical foreign keys still name `stock_suppliers`; this is intentional compatibility, not
authorization to rename them. Stock-specific article references, orders, receipts and
invoice matching still query the shared ORM record through the facade alias. A later slice
should introduce explicit application query calls in those operations and add partner
snapshots to cross-module historical events before considering any additive canonical
table or 360 read model.
