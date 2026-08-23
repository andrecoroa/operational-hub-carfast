# Migration, validation and roadmap

## 1. Two separate delivery paths

### Path A — Existing CarFast installation

Goal: move the existing company installation to the target architecture without losing or invalidating any operational or historical evidence.

Preservation set includes:

- documents and physical objects, attachments and previews;
- active and historical processes, phases, statuses, assignees, dates and context;
- tasks/tickets, comments, recurrence, SLA and assignment history;
- email threads, messages, attachments, webhook/delivery evidence;
- vehicles, Workshop, Sales, Stock, purchasing and partner records;
- users, roles, permission grants, scopes and organization;
- links, events, imports, notifications and audit history.

Migration characteristics:

- additive before subtractive;
- idempotent and resumable;
- explicit compatibility windows;
- rehearsed only on isolated PostgreSQL/storage copies;
- counts, links, hashes and business-state reconciliation;
- backup and rollback proof before production approval.

### Path B — Reusable clean installation

Goal: create a new company from the same code and migrations with no CarFast operational/configuration data.

Sequence:

```text
empty PostgreSQL + empty storage
  -> Alembic base..head
  -> versioned reference seeds
  -> installation onboarding
  -> first organization + administrator
  -> initial module selection
  -> installation-specific branding/endpoints/secrets
```

It must contain no CarFast users, documents, email, processes, tasks, vehicles, suppliers, stock, audit events, domains or branding. Its seeds contain only technical codes/states/types, canonical permissions and the module catalogue. Production cleaning/anonymization is forbidden as a creation method.

## 2. Data classification gate

Before a seed or migration is approved, every affected record/table is classified:

| Class | Versioning | Clean install | CarFast migration |
|---|---|---|---|
| schema | Alembic | create | upgrade |
| reference data | explicit idempotent seed/migration | include | reconcile/update |
| installation configuration | onboarding/admin | create new | preserve/transform |
| operational data | business workflows/imports | exclude | preserve/reconcile |

The existing `seed_initial_data` remains a compatibility bootstrap until its CarFast-specific organization/mailbox/module defaults are separated.

## 3. Test strategy

### Characterization tests

Freeze current observable behaviour before moving a slice:

- route/status/permission and server-validation outcomes;
- primary queries and record counts;
- state transitions and audit writes;
- post-action destinations/context;
- document/storage access;
- background job and integration behaviour;
- representative HTML/component behaviour where contract-relevant.

Tests should identify intentional current behaviour versus known debt; they must not blindly make every legacy outcome canonical.

### Contract tests

Each port/event/reference has producer and consumer tests for version, authorization, idempotency, unavailable owner, disabled module, retry and historical snapshot.

### Module-combination tests

Minimum matrix:

| Core | SD | Docs | Auto | Stock | Partners | Expected |
|---:|---:|---:|---:|---:|---:|---|
| on | off | off | off | off | off | login/Admin core/recovery work |
| on | on | off | off | off | on | tasks/process/email without archive/vehicle/stock |
| on | off | on | off | off | off | autonomous upload/triage/archive |
| on | off | off | on | off | on | vehicle/Fleet/Workshop/Sales without Stock |
| on | off | off | off | on | on | autonomous Stock/Purchasing |
| on | on | on | on | on | on | full CarFast integration |
| on | mixed capabilities | on | on | on | on | capability-level composition works |

Each combination tests navigation, direct URL, permissions, Admin, search, notifications, jobs, history and controlled degradation.

### Clean-install tests

- migrate empty PostgreSQL base-to-head;
- seed twice with identical results;
- assert zero operational/configuration-specific records and files;
- onboard company/admin/modules;
- start and health-check app;
- exercise supported module combinations;
- prove no outbound email/webhook/network integration;
- validate per-install branding/endpoints/secrets.

### Preservation/reconciliation tests

| Layer | Checks |
|---|---|
| database | table/domain counts, PK sets, nullability, unique/FK/orphan checks |
| workflows | open-state/phase/assignee/date/context equivalence |
| documents | metadata count, object existence, size, SHA-256, readable sample, link targets |
| email | thread/message/attachment/delivery ordering and IDs |
| authorization | users, roles, grants, scopes, effective-access samples |
| audit | event count/order/actor/entity/correlation and immutability |
| financial/stock | totals, immutable ledger balances and proposal/order amounts |

Reports are machine-readable and retained as release evidence. Any unexplained mismatch blocks cutover.

## 4. Incremental roadmap

### Phase 0 — Remote foundation (complete)

Outcome: Codespaces, PostgreSQL CI, Alembic head check, clean-bootstrap control, repository instructions and branch workflow.

### Phase 1 — Target specification (this phase)

Deliverables: architecture, ownership, dependencies, contracts, permissions, UI/post-action system, legacy strategy, two migration paths, tests and roadmap.

Acceptance:

- all approved decisions represented;
- statements labelled fact/decision/recommendation/hypothesis;
- no functional code/schema changes;
- ownership covers every current model table family;
- decisions pending explicitly listed;
- Strategy approval before Phase 2.

### Phase 2 — Characterization and composition foundation

Dependencies: Phase 1 approval.

Work:

1. capture and freeze baseline routes, permissions, post-actions/destinations,
   current composition and data invariants;
2. introduce module manifest interfaces and a read-only registry, validated only
   with a fictitious technical module;
3. add the minimum catalogue/`installation_modules` schema only if its detailed
   proposal, PostgreSQL migration, unique Alembic head and reversal path are clear;
4. compose navigation/Admin/settings/jobs behind a feature gate, with legacy
   composition selected by default;
5. implement a policy-decision API and legacy mapping without changing effective
   access;
6. add characterization/differential tests and prove Core starts without importing
   the fictitious module.

Reversibility: feature-gated composer; legacy composition remains selectable.

Acceptance: no visible functional regression or permission delta; inactive test
module contributes nothing; legacy composer remains the default; Core starts
without importing the fictitious module.

### Phase 3 — Shared UI and post-action foundation

Dependencies: token/component decisions and Phase 2 registry.

Work: tokens, shell, key primitives, ReturnContext, accessibility/responsive test harness. Apply first to a low-risk representative surface, not a broad redesign.

Reversibility: old templates/routes remain behind route-level switch.

Acceptance: 320 px no body overflow, keyboard/focus/contrast gates, deterministic Save/Close/Cancel/Back tests.

### Phase 4 — Partners boundary

Rationale: removes Stock ownership from a widely referenced entity and creates a reusable reference pattern.

Work: Partners application facade over existing tables, stable partner reference, adapters for `StockSupplier`, Email/Suppliers pages and Documents. No destructive rename initially.

Reversibility: facade delegates to current storage.

Acceptance: Stock/Email/Workshop use contracts; partner history and all supplier links reconcile.

### Phase 5 — Document Management boundary

Dependencies: reference/event contracts and storage reconciliation tooling.

Work: document application services, binary-object contract, source adapters, replace cross-domain writes, reconcile direct FKs and generic links without deletion.

Reversibility: dual-read comparison and old routes retained.

Acceptance: standalone Documents combination passes; every object/metadata/link reconciles.

### Phase 6 — Service Desk boundary

Dependencies: Core policy/composition and Documents contract.

Work: package Tasks, Processes and Email capabilities; characterize management centre; separate internal contracts; normalize permissions and post-actions.

Reversibility: legacy routes map to new application commands.

Acceptance: capability on/off matrix, mailbox restrictions, SLA/process/task history and email delivery evidence reconcile.

### Phase 7 — Stock & Purchasing boundary

Dependencies: Partners and Documents contracts.

Work: isolate ledger/purchasing services; remove direct Workshop imports; material request/fulfilment contract; location/cost restrictions.

Reversibility: Workshop adapter can remain manual.

Acceptance: Stock operates without Workshop; ledger totals and immutable movements reconcile exactly.

### Phase 8 — Automotive & Fleet boundary

Dependencies: Documents, Partners, Service Desk and Stock contracts.

Work: vehicle core facade, Fleet/Workshop/Sales capability packages, phased/legacy Workshop bridge, source projections and process preservation.

Reversibility: dual-read/compare legacy Workshop, no deletion.

Acceptance: open processes preserve phase/responsible/dates/actions; Fleet without Workshop/Sales and Workshop without Stock pass.

### Phase 9 — Legacy retirement preparation

Dependencies: all domain boundaries stable and observed.

Work: classify every adapter/table/route, freeze legacy writes, export evidence, run retention windows and propose removals individually.

Reversibility: read-only legacy readers retained until approval.

Acceptance: zero unexplained usage, complete reconciliation and explicit functional/legal approval per candidate.

### Phase 10 — CarFast rehearsal and production proposal

Dependencies: green characterization/contract/module/clean-install suites.

Work only after separate authorization: restore isolated DB/storage, run idempotent rehearsal, reconcile, performance test, rollback rehearsal and produce cutover dossier.

No production execution is implied.

#### Accepted eight-table pilot and integral preparation (2026-08-23)

PR #24 was accepted and merged only into `integration/modular-architecture` at
`657b5dfbaa3aece57fbda394b11e376fc611a5ef`. The real pilot reconciled all eight
approved tables, returned zero measured orphans, proved the temporary read-only role and
write denials, and completed full resource/credential cleanup. Blue and permanent Green
remained intact.

The release now declares 166 relations, superseding the earlier inventory of 163. The
integral fixture path covers the complete declared inventory plus storage with exact
schema/PK/FK/count/full-row/object hashes and zero-tolerance comparison. The reusable clean
installation classifies every declared table and requires all non-reference relations to be
empty. See `INTEGRAL_BLUE_GREEN_REHEARSAL.md` for the executable synthetic controls and the
separate authorization gate for the first real Green rehearsal.

### Approved final transition — blue-green

The final transition must use a dedicated blue-green release, independently of
the temporary pilot in Phase 10:

- **Blue** is the current production service and remains operational and intact
  throughout construction and validation.
- **Green** is a permanent, independent Render Web Service/environment with its
  own URL, PostgreSQL and storage. A PR Preview is not Green.
- Green receives data only through a separately approved controlled rehearsal;
  integrations, email, jobs, webhooks, portals and all external effects remain
  disabled until cutover.
- Cutover requires integral reconciliation of IDs/FKs, document and attachment
  hashes, active and historical processes, permissions and audit, plus a proven
  rollback. Blue becomes read-only before a common database/storage delta
  cut-off; tolerance for unexplained reconciliation differences is zero.
- Green is activated and the primary domain is changed only inside an approved
  short window. Concurrent writes to independent Blue and Green databases are
  prohibited.
- Blue remains read-only and available for rollback for an approved stabilization
  period. Archive/deletion follows acceptance and a separately approved retention
  gate.
- The reusable empty installation is produced from the same Green release using
  migrations and explicit seeds, never by cleaning production.

Costs, permanent resources, domains, database/storage creation, real copying,
cutover and later destruction each remain separate approval gates. This decision
does not authorize any current production or Render change.

## 5. Migration mechanics

For each slice:

```text
characterize
 -> add target schema/contracts
 -> backfill idempotently
 -> dual-read compare
 -> switch writes through owner
 -> observe/reconcile
 -> freeze legacy writes
 -> retain read adapter
 -> propose retirement separately
```

Migration PR rules:

- one objective/branch;
- unique Alembic head before and after integration;
- never mechanically cherry-pick divergent migrations;
- PostgreSQL empty upgrade plus representative isolated-copy rehearsal;
- transaction/batch strategy documented;
- restart/resume markers and idempotency keys;
- backup/rollback and reconciliation commands reviewed;
- no document object move without hash and accessibility verification.

## 6. Risks and controls

| Risk | Severity | Control |
|---|---:|---|
| hidden legacy consumer | critical | telemetry + characterization + compatibility window |
| document/object mismatch | critical | metadata/object/hash/link reconciliation |
| active process loses context | critical | state snapshot and workflow-specific acceptance tests |
| permission broadening | critical | old/new effective-decision differential tests; default deny |
| divergent migrations | critical | semantic reconciliation and unique-head CI |
| circular module dependency | high | manifest validation and architecture import tests |
| dual-write drift | high | owner transaction + outbox; differential reports |
| visual rewrite scope explosion | high | component-first representative slices |
| disabled module causes 500/jobs | high | module-combination and degradation tests |
| clean seed contains CarFast data | high | explicit classification and forbidden-value/zero-data assertions |
| automatic preview/deploy resources | high | verify Render/GitHub settings before each integration |

## 7. Release gates

No structural slice is merge-ready unless:

1. ownership and contracts are approved;
2. characterization is green or intentional deltas are approved;
3. authorization is enforced server-side and navigation matches;
4. unique Alembic head and PostgreSQL upgrade pass;
5. clean-install baseline remains empty/idempotent;
6. affected module combinations pass;
7. reconciliation has no unexplained mismatch;
8. degradation and rollback are tested;
9. documentation and audit evidence are current;
10. production deploy behaviour is explicitly authorized.

## 8. Approved Phase 2 guardrails and remaining approvals

The ten architectural definitions are approved: catalogue states, default-deny
permission decision, immutable versioned references/events, ownership resolutions,
clean seed boundary, existing CSS/macro technology with WCAG 2.2 AA, authorized
read-only history for disabled modules, synthetic-only initial rehearsals and
automatic PR Previews disabled before structural work.

Phase 2 may decide only implementation details that preserve those definitions.
An anonymized production copy, staging/paid resources, production rehearsal,
effective permission change, real-module movement and any legacy removal require a
new approval.
