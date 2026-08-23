# Proposed CarFast anonymized migration rehearsal

Status: **execution proposal only — not authorized to provision, copy or run**

This runbook defines one disposable, isolated rehearsal of the CarFast migration path. It creates no resource, contains no secret and authorizes no access to production data or document storage. Every command is a template whose prerequisites must be approved and supplied outside Git.

## 1. Purpose and deliverables

The rehearsal must prove that one mutually consistent database and document snapshot can be anonymized, migrated, reconciled, functionally tested and rolled back without contacting production integrations. Deliverables are:

1. signed capture manifest and common cut-off identifier;
2. anonymization report by table/column and residual-PII scan;
3. pre/post counts, relationship checks and state distributions;
4. document metadata/object accessibility, byte-size and hash reconciliation;
5. open-process continuity report for state, phase, responsible, dates and actions;
6. permissions differential and audit/history preservation report;
7. performance and functional test results;
8. rollback evidence and destruction certificate;
9. go/no-go dossier with every exception explicitly explained.

## 2. Environment topology

Use a short-lived, non-production environment in a separately access-controlled project/account:

- application: one ephemeral instance built from an immutable commit of `integration/modular-architecture`;
- database: dedicated PostgreSQL with no network route to production and a name ending `_test`;
- objects: dedicated private bucket/container with versioning disabled unless required for rollback testing;
- job runner: isolated worker with outbound traffic denied by default;
- DNS: internal/random hostname, never a CarFast production domain;
- email, webhooks, OAuth, Postmark, Webex, WhatsApp, portals and scheduled outbound jobs: disabled or bound only to local capture mocks;
- logs: private, access-controlled, with payload/body logging disabled;
- observability: technical metrics only; no document contents or original personal identifiers.

Preferred implementation is a disposable staging stack with PostgreSQL and object storage in the same region. Local developer machines, shared personal storage and the current Render production service are prohibited.

## 3. Roles and separation of duties

| Role | Responsibility | Must not do alone |
|---|---|---|
| Strategy owner | approves scope, tolerances, costs and go/no-go | access or transform the dataset |
| Data custodian | authorizes snapshot and validates lawful purpose/retention | approve own anonymization exceptions |
| Execution lead | runs signed runbook and records evidence | change functional mappings during rehearsal |
| Security/privacy reviewer | approves transformations and residual-PII scan | operate production export credentials |
| Application reviewer | validates flows, ownership and permissions | waive unexplained reconciliation differences |
| Infrastructure operator | provisions isolation, network and destruction | inspect business content unnecessarily |
| Independent verifier | checks report, hashes and rollback evidence | modify the rehearsal dataset |

Named people and deputies must be recorded in the execution ticket before provisioning.

## 4. Approval gates

No step may begin until the preceding gate is signed:

- **G0 — proposal approval:** environment, budget ceiling, roles, lawful purpose, retention and tolerances.
- **G1 — provision approval:** exact provider/resources, regions, network policy and destruction owner.
- **G2 — capture approval:** read-only production credentials, maintenance/capture window and storage locations.
- **G3 — anonymization approval:** field transformation map and exceptional fields.
- **G4 — rehearsal approval:** residual scan clean, source snapshots sealed and integrations proven off.
- **G5 — destruction approval:** evidence exported, resources/data deleted and certificate reviewed.

Any failed gate stops the run; it never becomes an implicit waiver.

## 5. Common database/storage cut-off

Database metadata and document objects must represent one logical cut-off:

1. pause or queue application writes that can alter document metadata or objects during capture, using an approved maintenance mechanism;
2. record UTC timestamp, PostgreSQL transaction/WAL position and application commit as `CUT_OFF_ID`;
3. create the consistent PostgreSQL snapshot from one repeatable-read/export snapshot;
4. enumerate every referenced object key from that same database snapshot;
5. copy exactly those keys to isolated quarantine storage, retaining original byte hashes in a separate signed manifest;
6. record missing, extra or changed objects before releasing the write pause;
7. seal database dump, object manifest and capture metadata with SHA-256 and one signed `CUT_OFF_ID` manifest;
8. abort if any referenced object changed during capture or if the database and object manifests cannot be tied to the same cut-off.

No live production object URL may remain usable from the rehearsal environment.

## 6. Anonymization method

Anonymization runs in a quarantine zone before the application rehearsal. Direct identifiers are deterministically tokenized where joins must survive and irreversibly generalized/redacted otherwise.

### 6.1 Transformation classes

| Data class | Method | Referential behavior |
|---|---|---|
| internal numeric IDs/FKs | preserve | exact links and counts remain testable |
| names, companies and display names | keyed deterministic pseudonym | equality/joins preserved; original unrecoverable without separately held key |
| emails | deterministic local alias under reserved invalid domain | thread/user joins preserved; delivery impossible |
| phone numbers | deterministic format-preserving test number | equality preserved; non-routable range only |
| addresses | replace with synthetic district/country-compatible values | geographic class retained only if required by tests |
| tax/legal/bank identifiers | deterministic valid-shape token or null when optional | uniqueness retained; never a real identifier |
| plates/VIN/external unit numbers | deterministic format-preserving token | vehicle/process/document links preserved |
| free text, email bodies, OCR and extraction payloads | replace with synthetic markers; allowlist technical enums only | no original prose retained |
| filenames | deterministic neutral name with extension retained | object/reference mapping preserved |
| document binaries/images | replace content with synthetic same-type fixtures unless content-level parsing is explicitly approved | object key/link retained; original bytes never enter rehearsal |
| timestamps/statuses/phases | preserve or consistently shift dates | sequence, duration and open-state tests retained |
| audit IP/user-agent/request payload | redact/tokenize | event order/action/actor pseudonym retained |
| secrets, tokens, signatures, webhook payload credentials | delete and replace with disabled/sandbox configuration | no production connectivity |

The keyed pseudonymization secret is generated for this rehearsal, held outside the dataset by the security reviewer and destroyed at G5. It is never committed, logged or reused.

### 6.2 Validation

- enforce declared transformations through a versioned field map;
- scan all string/JSON/text fields and extracted files for email, phone, tax, IBAN, plate/VIN and configured name patterns;
- sample every transformation class under two-person review;
- confirm uniqueness/FK constraints and required format checks;
- reject, do not manually waive, residual high-confidence identifiers;
- produce counts only in the durable report; do not export sensitive row samples.

## 7. Integrations and side-effect controls

Before application startup:

- set inbound/outbound email to false and point any test mailbox to a local capture server;
- clear production API tokens and signing secrets; use rehearsal-only generated values;
- block outbound network except package mirrors and explicitly approved mock endpoints;
- disable webhook dispatch and replace receivers with local recorders;
- disable scheduled jobs until each is allowlisted for read-only rehearsal use;
- disable portal/public links and invalidate copied publication tokens;
- ensure object storage credentials can access only the isolated bucket;
- verify with a canary request that production endpoints are unreachable;
- fail startup if a production hostname/domain appears in effective configuration.

## 8. Executable sequence

Commands are illustrative and must run from the approved immutable commit in the ephemeral runner. Secret and resource values are injected by the approved secret store, never shell history or repository files.

```text
preflight: verify G0–G3 signatures, commit SHA, environment guard and egress deny
capture: create sealed DB/object manifests with one CUT_OFF_ID
quarantine: restore DB and copy only manifest-listed objects
anonymize: apply approved field map; replace document content; run residual scan
seal: hash anonymized dump/object manifest and revoke capture credentials
rehearsal: create fresh target; Alembic upgrade; run idempotent migration/import twice
reconcile: counts, IDs, FKs, states, hashes, accessibility, permissions and audit
test: clean bootstrap separately; module combinations; core flows; performance; security
rollback: destroy rehearsal target; restore pre-rehearsal isolated checkpoint; reconcile again
report: sign exceptions/go-no-go; export evidence; execute G5 destruction
```

The existing guarded command `python -m scripts.run_phase10_rehearsal` is used only for the separate clean-install target. A later implementation PR must add the approved anonymization and CarFast reconciliation commands; this proposal deliberately does not contain production extraction logic.

## 9. Reconciliation metrics and tolerances

| Metric | Required tolerance |
|---|---:|
| rows per operational/reference/history/audit table | exactly expected delta; default 0 |
| primary keys and stable references | 100% preserved unless explicitly mapped |
| non-null foreign keys resolving | 100% |
| documents with metadata and listed object | 100% |
| object accessibility | 100% |
| anonymized object hash versus anonymized manifest | 100% |
| original-object hashes copied to rehearsal | 0 objects, unless separately approved |
| open processes preserving status/phase/responsible/dates/context | 100% |
| tasks/emails/process/document associations | 100% |
| users/profiles/permission effective-decision differential | 0 unexplained differences |
| audit/history event order and ownership | 100% structurally preserved |
| duplicate stable references | 0 |
| residual high-confidence direct identifiers | 0 |
| failed core/module-combination/security tests | 0 |
| unexplained errors or reconciliation exceptions | 0 |

Statistical/performance tolerances must be approved at G0. Proposed initial targets are p95 page/API latency no worse than baseline by 20%, no query with more than 2× baseline duration, and migration/rollback completion within the approved maintenance window. Performance failure blocks go-live planning but does not justify data-integrity tolerance.

## 10. Test matrix

- Alembic unique head, upgrade/downgrade/upgrade and idempotency;
- clean installation from migrations/seeds with zero operational rows;
- Core with each module off/on and approved combinations;
- Documents standalone, object access, previews and synthetic OCR/extraction;
- Service Desk task/process/email lifecycles with outbound integrations captured locally;
- Stock without Workshop and ledger/reversal reconciliation;
- Fleet without Workshop/Sales; Workshop without Stock;
- Workshop legacy/phased open-process continuity;
- permissions differential for every anonymized profile;
- signed ReturnContext and external-return rejection;
- keyboard/responsive/accessibility smoke tests on representative surfaces;
- search, notifications and jobs under module-disabled degradation;
- backup restoration and full rollback reconciliation;
- negative tests proving production DNS, credentials and endpoints are unreachable.

## 11. Retention and destruction

Proposed maximum lifetime is seven calendar days from capture, shortened where feasible. Exact period requires G0 approval.

- quarantine source: delete immediately after anonymization seal and verification;
- anonymized DB/objects: delete at G5 or automatic expiry, whichever occurs first;
- ephemeral logs/caches/runners/backups: included in deletion inventory;
- pseudonymization secret: destroy at G5 and record destruction;
- durable evidence: retain only aggregate metrics, signed manifests without object keys/personal data, CI results and approvals under the approved audit retention policy;
- infrastructure operator produces deletion evidence; independent verifier confirms resources, snapshots and credentials no longer exist.

## 12. Cost proposal

Before G1, Infrastructure provides a fixed ceiling covering PostgreSQL, object capacity/operations, compute/runner time, private networking, logs and backup snapshot. Record currency, taxes, region, duration and automatic-expiry settings. No purchase or paid resource is authorized by this document.

Prefer the smallest resources that hold the measured anonymized volume plus 30% headroom. The budget must include destruction verification and one rollback repetition. If the estimate exceeds the approved ceiling, stop before provisioning.

## 13. Rollback rehearsal

Rollback is performed only inside the isolated environment:

1. seal the pre-migration anonymized DB and object checkpoints under one rehearsal ID;
2. execute migration and tests;
3. revoke application access and stop workers;
4. destroy migrated target DB/object namespace;
5. restore both pre-migration checkpoints, never only one side;
6. verify counts, stable references, object hashes/accessibility and open-process context;
7. restart with integrations still disabled and run read-only smoke tests;
8. record duration, failures and evidence.

Any inability to restore both DB and objects exactly is an automatic no-go.

## 14. Go/no-go criteria

**Go for production-planning proposal only** when every mandatory tolerance is met, CI/test matrix is green, rollback is successful within its window, no residual identifier or production connectivity exists, all exceptions are explained and signed, and Strategy/Data/Security/Application reviewers approve.

**No-go** on any unexplained count/hash/link/permission difference, missing object, lost process context, failed rollback, residual PII, production endpoint reachability, divergent migration head, uncontrolled side effect, exceeded retention/cost, or missing approval. No-go triggers containment, evidence preservation without personal content, destruction at G5 and a new proposal; it never triggers an ad-hoc fix against production.

## 15. Decisions required from Strategy

1. approve or revise environment/provider/region and cost ceiling;
2. name each responsible person and independent verifier;
3. approve lawful purpose, seven-day maximum retention and durable evidence policy;
4. approve the precise anonymization field map and binary replacement policy;
5. approve capture window and common cut-off mechanism;
6. approve performance targets and confirm all integrity tolerances remain exact;
7. authorize separately the provisioning of resources;
8. authorize separately the read-only capture and copying of data/documents.

Until those decisions and gates are complete, execution stops at this document.
