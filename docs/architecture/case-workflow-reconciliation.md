# Case workflow reconciliation

## Scope of this candidate

This candidate reconciles the proposed case workflow with the existing structural
foundation. It does not expose UI or API routes, send email, publish portal data,
or import real sale and vehicle data. `CASES_V1_ENABLED` remains disabled.

## Canonical mapping

- `TaskCase` remains the single operational case aggregate. `OperationalCase` is
  an alias, not a second table.
- `ProcessModel`, `ProcessModelVersion`, and `ProcessInstance` remain canonical.
- A process version contains the immutable phase definition. Starting an instance
  creates ordered `ProcessPhaseInstance` snapshots.
- `ProcessPhaseExecution` records how a phase is executed. A delegated execution
  references a real `Task`, which continues to belong to the same case and points
  back to the process and phase key.
- Vehicles, documents, email messages, and workshop processes are attached with
  typed link tables. Tasks use their existing canonical `Task.case_id` membership
  plus the phase execution reference, so no competing task-to-case link is added.
  Linked records are referenced, never copied.
- Accepted proposal versions, workflow changes, and integration intents are
  recorded separately through proposal acceptance, audit, and outbox records.

## Dynamic decisions and branching

The immutable model definition may describe alternatives and transition rules,
while each phase stores the definition snapshot that applied when the process was
started. The choice between settlement model A and B must become an explicit,
audited execution decision before downstream phases are opened. This candidate
does not add a generic decision-value table because the decision payload and its
validation contract have not yet been approved. The minimum later extension is a
`process_decisions` record containing process, phase, decision key, selected
option, actor, timestamp, revision, and optional evidence references. Branch
activation must be derived from that accepted decision and never by rewriting the
published model version.

## Portal visibility

Typed links deliberately contain no implicit customer visibility. The minimum
later extension is an explicit publication policy/record at process or linked-item
level, with audience, publication state, actor, timestamps, and revocation audit.
Nothing becomes portal-visible merely because it is linked to a case.

## Permissions

The migration registers the missing granular permission codes. It intentionally
does not grant them to default roles. Role grants must be approved separately so
that installation/bootstrap does not silently broaden operational authority.

## Migration and rollback

Migration `fff9de4f5a6b` is additive on top of structural head `fff8cd3e4f5a`.
Its downgrade refuses to remove the extension while workflow evidence exists.
Published process-version immutability is protected in PostgreSQL and in the ORM.

## Decisions still required

1. Source of truth for `Entregue`: fleet state, delivery evidence, a dedicated
   delivery event, or an approved precedence between them.
2. Exact phase at which settlement model A/B becomes fixed, and who may change or
   override it after selection.
3. Exact fields and documents that may be published to the customer, including
   whether settlement evidence needs redaction or explicit approval.
4. Default role grants for create, execute, delegate, validate, reopen, and
   exceptional closure permissions.
