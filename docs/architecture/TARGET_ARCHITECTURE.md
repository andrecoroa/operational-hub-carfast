# Target architecture

## 1. Executive target

**DECISION:** CarFast becomes a modular monolith. Each installation serves one company and has its own database, storage, secrets, endpoints and module configuration.

```text
Installation boundary
│
├── Core platform
│   ├── installation + organization + identity
│   ├── authentication + authorization
│   ├── module catalogue + composition
│   ├── settings + audit + notifications + search + technical jobs
│   └── shared UI/post-action contracts
│
├── Service Desk
│   ├── Tasks / Tickets
│   ├── Processes
│   └── Email / Communications
│
├── Document Management
├── Automotive & Fleet
│   ├── Vehicle core
│   ├── Fleet
│   ├── Workshop
│   └── Vehicle Sales
│
├── Stock & Purchasing
└── Partners & Suppliers
```

**RECOMMENDATION:** retain a single deployable application and PostgreSQL database while enforcing package, service and ownership boundaries. Extraction into services is not a Phase 1 objective and is considered only if measured scaling, isolation or organizational needs later justify it.

## 2. Technical layering

Every domain package should converge on the same internal shape:

```text
app/modules/<module>/
├── domain/          # entities, value objects, policies; no FastAPI/SQLAlchemy orchestration
├── application/     # commands, queries, ports, transactions, events
├── infrastructure/  # SQLAlchemy repositories, external adapters, scheduled job adapters
├── web/             # FastAPI routes, forms/view models, module templates
├── admin/           # declarative administration contributions
└── manifest.py      # module identity, dependencies and all contributions
```

Core equivalents live under `app/core_platform/`. Shared code must have a named owner. A generic `utils` package cannot become a hidden cross-domain dependency.

Allowed dependency direction:

```text
web ──> application ──> domain
             ▲
infrastructure ────────┘

module application ──> core contracts
module A ──> declared port/event/reference ──> module B adapter
```

Forbidden directions:

- Core importing a module.
- A route importing another module's ORM model.
- A module writing another module's table.
- Templates or navigation testing arbitrary table existence.
- Jobs running for inactive modules without an explicit historical-maintenance reason.

## 3. Core platform

### Responsibilities

| Capability | Responsibility |
|---|---|
| Installation | identity, status, locale/timezone, branding keys, environment identity |
| Organization | organizational units, teams and membership |
| Identity | users, credentials, session/token lifecycle |
| Authorization | roles, permissions, scopes, restrictions and policy decision |
| Module catalogue | available modules/capabilities, dependency rules, installed version |
| Module configuration | active/disabled state and per-installation configuration |
| Composition | navigation, Administration, settings schemas and job registrations |
| Audit | immutable actor/action/entity/correlation evidence |
| Notifications | delivery-neutral notification records and user preferences |
| Search | provider registry and normalized result references |
| Jobs | registration, scheduling metadata, idempotency and execution audit |
| UI contract | tokens, component contracts and post-action semantics |

Core owns identifiers and policies, not operational business entities. Search indexes and notification payloads contain stable references/snapshots, not foreign ownership.

### Minimum availability

Authentication, authorization, audit and module-state evaluation must operate even when every optional module is disabled. Core Administration must still permit installation recovery and module configuration.

## 4. Module responsibilities

### 4.1 Service Desk

**DECISION:** one module with three internal capabilities that keep distinct lifecycle and permissions.

| Capability | Owns | Does not own |
|---|---|---|
| Tasks/Tickets | ticket lifecycle, assignment, SLA, participants, comments, recurrence, notifications | vehicle, document or supplier master data |
| Processes | orchestration instances, steps, state transitions, associations | source-domain entity lifecycle |
| Email/Communications | mailboxes, threads, messages, attachments-as-communication evidence, delivery/webhook state | document archive policy or supplier identity |

The module may be active while one capability is disabled. Email-to-ticket and process-to-task are internal contracts, not shared-table assumptions.

### 4.2 Document Management

Owns document metadata, binary-object identity, versions/extractions, workflow state, retention, classification, links and document audit. It accepts ingestion from upload or adapters and continues without Service Desk.

It does not own the source entity. `DocumentLink`-style references identify an external entity and may store a historical display snapshot. A source module being disabled cannot make the document inaccessible to authorized document users.

### 4.3 Automotive & Fleet

**DECISION:** one module with internal capabilities and separate permissions.

| Capability | Owns |
|---|---|
| Vehicle core | vehicle identity, identifiers, lifecycle and common status history |
| Fleet | operational allocation/status, financial/contract views and fleet-specific history |
| Workshop | repair/maintenance process, phases, checks, services, incidents and material requests |
| Vehicle Sales | sale profile, media, publication, lead and proposal lifecycle |

Vehicle core is the stable internal dependency. Fleet, Workshop and Sales communicate through vehicle application contracts, not direct mutation of the `vehicles` row.

### 4.4 Stock & Purchasing

Owns locations, categories, articles, balances/ledger, minimums, invoice imports, receipts, inventory, purchase orders, delivery documents and discrepancies. It depends on Core and Partners, not Workshop.

Workshop may request/reserve/consume stock through contracts. When Workshop is inactive, Stock remains fully usable. When Stock is inactive, Workshop keeps a material-request record and exposes a controlled pending/manual state.

### 4.5 Partners & Suppliers

Owns partner identity, legal/display data, contacts, addresses, classifications and module-specific roles. The current `stock_suppliers` table is treated as a compatibility storage detail until safely migrated; it no longer defines conceptual ownership.

Stock, Workshop, Email and Documents reference a partner through a stable partner ID and optional historical snapshot.

## 5. Module catalogue and installation configuration

### Canonical records

```text
module_definitions
  code, version, name_key, required, lifecycle_state

module_capabilities
  module_code, capability_code, independently_switchable

installation_modules
  installation_id, module_code, state, configured_version,
  enabled_at, disabled_at, changed_by, configuration_json

module_dependencies
  module_code, dependency_code, minimum_version, dependency_kind
```

States:

| State | New operations | Read history | Routes/jobs | Data |
|---|---|---|---|---|
| available | no | no module UI | not registered | untouched |
| active | yes | yes | registered | normal |
| disabled | no | policy-controlled | write jobs off; preservation jobs explicit | preserved |
| retiring | restricted | yes | migration/compatibility only | reconciled |
| removed-code | no | through retained reader/export policy | not loaded | preserved per retention |

`hidden` is not a module state; it is a per-user navigation outcome. Required Core cannot be disabled.
The catalogue records modules, capabilities, dependencies and installed/configured
version. Its only installation lifecycle states are `available`, `active`,
`disabled` and `retiring`; `removed-code` above describes a later retention
condition, not a selectable catalogue state.

### Manifest contract

```python
ModuleManifest(
    code="service_desk",
    version="1",
    dependencies=("core",),
    capabilities=(...),
    permissions=(...),
    navigation=(...),
    admin_sections=(...),
    settings=(...),
    jobs=(...),
    search_providers=(...),
    event_handlers=(...),
)
```

**RECOMMENDATION:** manifests are Python declarations validated at startup and mirrored into catalogue tables for installation state/audit. Database rows must not dynamically import arbitrary code.

## 6. Declarative composition

The composer evaluates, in order:

```text
manifest present
  ∩ module/capability active
  ∩ user permission
  ∩ organizational scope
  ∩ record/data restriction
  = visible and executable contribution
```

### Navigation contribution

Fields: stable code, parent/group, label key, route name, icon token, order, required permission, capability and active-context matcher. URLs are produced by route names, never duplicated strings.

### Administration contribution

Each module contributes overview/configuration/access/operations/audit entries. Core supplies the shell and transversal sections. An inactive module contributes only an authorized historical/configuration card when policy requires it.

### Settings contribution

Fields: stable setting code, owner, schema/type, default, secret flag, environment override policy, validation, UI component and audit behaviour. Secrets store references or encrypted values outside source control and are never returned to templates.

### Job contribution

Fields: code, owner, schedule/default-disabled state, handler, idempotency key, module-state policy, timeout, retry/dead-letter policy and audit events. An inactive module's operational jobs do not run.

## 7. Internal integration contracts

### Synchronous contracts

Use application ports for immediate validation/query and commands for owned writes.

| Contract | Owner | Consumers | Failure behaviour |
|---|---|---|---|
| `ResolveEntityReference` | referenced module | all | return unavailable snapshot, never 500 |
| `CreateTask` | Service Desk | any module | source action may complete with integration-pending if policy permits |
| `LinkDocument` | Documents | all | retain document and pending link on unavailable source |
| `GetVehicleSummary` | Automotive | Workshop/Sales/Docs/Stock | historical snapshot if capability disabled |
| `RequestMaterial` | Stock | Workshop | Workshop keeps request as manual/pending if Stock disabled |
| `GetPartnerSummary` | Partners | Stock/Workshop/Email/Docs | stored snapshot when partner unavailable |

### Optional references

Canonical shape:

```text
entity_type, entity_id, installation_id,
display_snapshot, contract_version, source_version, linked_at, linked_by
```

References are validated through the owner when active. Snapshots support historical readability but never become a second master record.
An `EntityReference` is immutable after publication, carries an explicit contract
version and retains the minimum display snapshot needed to read historical context
when the owner is disabled or unavailable. Corrections create a superseding
reference rather than rewriting published evidence.

### Events

Events are persisted in the same transaction using an outbox. Initial dispatch is in-process; no broker is required.

Envelope:

```text
event_id, event_type, schema_version, occurred_at,
installation_id, actor_id, correlation_id, causation_id,
owner_module, entity_reference, payload
```

Initial event families: task lifecycle, process lifecycle, communication received/delivered, document received/classified/linked, vehicle state changed, workshop material requested, stock movement recorded and partner changed.

Handlers must be idempotent. Failed optional handlers enter an audited retry/dead-letter state and do not roll back an already-valid owner transaction unless the contract explicitly requires atomicity.
Published events and their envelopes are immutable and versioned. Compatibility is
handled by version-aware consumers/upcasters; an emitted event is never edited in
place. The reference snapshot included in an event is deliberately minimal.

## 8. Controlled degradation

| Situation | Required behaviour |
|---|---|
| Service Desk disabled, email inbound endpoint called | reject/hold with explicit status; no message loss or implicit task |
| Documents disabled, email has attachments | retain communication attachment evidence; mark document archival integration unavailable |
| Stock disabled, Workshop requests material | keep Workshop request with manual/pending status |
| Workshop disabled, Stock used | all independent Stock operations remain available |
| Automotive disabled, historical document linked to vehicle | authorized document remains readable with reference snapshot |
| Partners disabled, historical purchase viewed | supplier snapshot remains readable; new partner selection blocked |
| Search provider inactive | omit live provider, optionally retain authorized historical index result marked unavailable |
| Module job disabled mid-run | finish/abort according to declared safe point and audit outcome |

Every degraded result uses a stable machine code, user-readable message, correlation ID and audit entry.

## 9. Permission model

Canonical permission key:

```text
<module>.<capability>.<action>
```

Effective decision:

```text
module active
AND permission granted
AND scope allows entity
AND restrictions allow fields/action
AND contextual policy passes
```

The default is deny. One policy-decision result is consumed by server-side
authorization and by UI composition; hiding a control never replaces server
enforcement. During transition, a legacy adapter translates current grants and
restrictions into the canonical decision without broadening effective access.

### Actions

`read`, `create`, `update`, `transition`, `assign`, `approve`, `close`, `delete_soft`, `export`, `configure`, `manage_access`, `execute_job`.

### Scope

`installation`, `organizational_unit`, `team`, `assigned`, `created`, `participating`, `record_set`, `self`.

### Restrictions

Examples: confidentiality level, mailbox, stock location, vehicle group, process type, amount threshold, field mask and time window.

### Initial target matrix

| Permission family | Typical scopes/restrictions |
|---|---|
| `core.users.*` | installation, organizational unit; credential actions separated |
| `core.roles.*` | installation; system roles protected |
| `core.modules.*` | installation; activation/configuration separately granted |
| `core.audit.read/export` | installation/unit; export separately granted |
| `service_desk.tasks.*` | assigned/team/unit/installation; ticket type and confidentiality |
| `service_desk.processes.*` | participant/team/unit; process type and transition |
| `service_desk.email.*` | mailbox/team/unit; send/approve/configure separated |
| `documents.records.*` | unit/installation; confidentiality/retention/field mask |
| `automotive.vehicles.*` | fleet group/unit; sensitive financial field mask |
| `automotive.workshop.*` | team/unit; phase transition and closure approval |
| `automotive.sales.*` | team/unit; proposal amount/approval threshold |
| `stock.articles.*` | location/unit; cost visibility restriction |
| `stock.movements.*` | location/unit; approve/adjust separated |
| `purchasing.orders.*` | unit; value approval threshold |
| `partners.records.*` | unit/installation; financial/confidential field mask |

Legacy permission codes remain mapped by a versioned compatibility adapter until role grants are reconciled. Navigation uses the same policy decision as server handlers.

## 10. Canonical Administration taxonomy

```text
Administration
├── Installation
│   ├── Company, branding, locale
│   ├── Modules and capabilities
│   └── Environment/integration status
├── Organization & Identity
│   ├── Units and teams
│   ├── Users
│   └── Authentication policy
├── Access
│   ├── Roles and permissions
│   ├── Scopes and restrictions
│   └── Access diagnostics
├── Platform
│   ├── Notifications
│   ├── Search
│   ├── Jobs
│   └── Shared settings
├── Modules
│   ├── Service Desk
│   ├── Document Management
│   ├── Automotive & Fleet
│   ├── Stock & Purchasing
│   └── Partners & Suppliers
├── Integrations
│   ├── Endpoints/adapters
│   └── Delivery/degradation status
└── Audit & Security
    ├── Audit trail and exports
    ├── Security events
    └── Retention/integrity controls
```

This replaces the current overlapping flat navigation, domain directory and technical module matrix. Module sections are supplied by manifests.

## 11. Visual system target

The incremental implementation uses CSS Custom Properties and the existing
template macros/components. No new CSS or JavaScript UI framework is introduced
for this consolidation.

### Tokens

- colour: semantic surface/text/border/action/success/warning/danger/info tokens;
- typography: font families, 7-step size scale, weights and line heights;
- spacing: 4 px base scale;
- sizing: control heights, icon sizes, content widths and touch targets;
- shape/elevation: radius, border and shadow levels;
- motion: duration/easing and reduced-motion alternatives;
- responsive breakpoints based on content stress, not device names.

No module defines raw brand colours, arbitrary control heights or competing page widths.

### Components

Required primitives: app shell, module navigation, page header, breadcrumbs/context bar, action bar, button/icon button, status badge, alert/toast, card, metric, tabs, filter bar, data table, pagination, empty/error/loading state, field/control, form section, stepper, modal, drawer/side panel, file preview, timeline/history and confirmation dialog.

### Layout contracts

| Layout | Use |
|---|---|
| list/index | filters + table/cards + persistent query state |
| record detail | context header + primary content + activity/related panel |
| workflow | step/phase navigation + work surface + blockers/actions |
| administration | taxonomy navigation + scoped configuration surface |
| review/triage | preview + metadata/actions; collapses safely on narrow screens |

Tables scroll inside their container, keep actions discoverable and provide a card/list alternative where horizontal comparison is not essential. Modals are for short atomic decisions; complex editing uses a page or drawer. File previews never force body-level horizontal overflow.

### Accessibility/responsiveness gates

- WCAG 2.2 AA is the acceptance baseline;
- keyboard navigation and visible focus;
- labelled controls and errors linked to fields;
- contrast and non-colour state indicators;
- minimum 44 px touch targets where appropriate;
- 320 px width without body overflow;
- navigation collapses without consuming the full first viewport;
- zoom/reflow and reduced motion supported.

## 12. Post-action contract

Every mutable view receives a validated `ReturnContext`:

```text
origin_route_name, origin_parameters, query/filter state,
parent_entity_reference, workflow_step, anchor, issued_at
```

It is signed or server-stored, route-name based, authorization-checked and never accepts an arbitrary external URL.

| Action | Persistence | Success destination | Failure destination |
|---|---|---|---|
| Save | commit draft/current state | same record and context | same form, values/errors retained |
| Save and close | commit | validated logical origin/list/parent | same form |
| Complete/Finish | transition + audit | next valid step or logical origin | current step with blockers |
| Cancel | none | validated origin | current page if origin invalid |
| Back | none | browser-safe logical origin | module list fallback |
| Create related | commit related record | source entity/related panel | creation form with context |

Success feedback is visible and non-duplicative. Concurrent update conflicts show the changed version and never silently overwrite. Module home is a fallback, not the default destination.

## 13. Extensibility tests

Without defining future requirements, the architecture must demonstrate that a hypothetical WhatsApp, Webex, portal or AI adapter can:

1. register a manifest without Core changes;
2. obtain explicitly granted contracts only;
3. produce/consume versioned events;
4. be disabled without breaking existing modules;
5. use installation-specific secrets/endpoints;
6. leave historical references readable;
7. contribute UI/Admin only while active.

Passing these tests proves extensibility; it does not authorize those modules.

## 14. Decisions required before implementation

The architectural choices above are approved. Phase 2 starts with characterization
and the Core composition foundation only; it does not move a real domain module.
Remaining implementation decisions must stay inside that approved slice: exact
package names, the additive catalogue DDL after review, baseline metric format and
the detailed compatibility mapping. Production rehearsal, anonymized data,
staging, costs and any legacy retirement still require separate approval.
