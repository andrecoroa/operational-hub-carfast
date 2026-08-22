# Phase 5 — Document Management boundary

Status: implementation slice on `integration/modular-architecture`; no production deployment.

## Facts preserved

- `documents`, `document_links`, `document_events`, `document_workflow_states`, OCR/profile tables,
  all foreign keys and every storage path remain physically unchanged.
- A document continues to own its metadata and object/link identity. Source modules continue to own
  the operational entity referenced by `entity_type` and `entity_id`.
- No file, metadata row, link, extraction, preview, classification, state or audit event is moved,
  renamed or deleted by this slice.
- `VISUAL_FOUNDATION_ENABLED` and the modular composer remain disabled by default.

## Boundary introduced

`app.documents` provides stable references, immutable summaries, source references, link-ingestion,
query/link/event application operations, compatibility adapters, a Core-only manifest and canonical
permission mapping. Permission-safe historical snapshots deliberately exclude storage paths.

Email ingestion now creates metadata, its source link and creation event through the facade. Workshop
link-backed evidence writes through the compatibility adapter. Tables and effective permissions stay
unchanged.

## Standalone and controlled degradation

The manifest depends only on Core, so Documents composes without Service Desk. If a source module is
unavailable, authorized users retain a minimal summary and generic link without importing that module.
Unauthorized snapshot restoration fails closed.

Remote/link providers are not fetched by verification code. Local synthetic objects are reconciled by
accessibility, byte count and SHA-256. This avoids treating a network outage as object loss.

## Reconciliation and reversibility

Tests prove the same ORM mapper/table/IDs, one metadata/link/event ingestion set, local hash/size,
preservation of all current FKs, standalone composition and exact legacy permission mapping. Rollback
is code-only: there is no migration or data rewrite.

## Remaining direct coupling

Legacy direct access remains until individually characterized. Priority next slices are Task/Evolution
links, Stock invoice ingestion, a binary object-store contract, and explicit version/retention models
only after preservation design approval. Visão 360 and import/export must consume contracts rather than
tables. None of these items authorizes table renames, object moves or real-data migration.

## Validation note outside the slice

The exact CI matrix and the document/workshop regression suites pass. An exploratory full vehicle-
document file run exposes a pre-existing assertion mismatch: the frozen test expects only `claim` and
`glass` under the Automotive `other` vocabulary, while the unchanged base also contains `keys`,
`battery`, `lighting` and `wash`. Neither side was changed here because resolving that vocabulary is an
Automotive functional decision, not a Document Management correction.
