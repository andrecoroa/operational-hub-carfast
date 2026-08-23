# Phase 6 — Service Desk boundary

Status: reversible implementation slice on `integration/modular-architecture`; no production deploy.

## Preserved facts

- Tasks/Tickets, Processes and Email remain distinct capabilities with their current tables, URLs,
  statuses, assignment rules, SLAs and effective permissions.
- No task, process, message, attachment, delivery record, mailbox grant, history or audit event is
  moved, renamed or deleted.
- Email outbound/inbound settings remain disabled or sandbox-controlled outside production. This slice
  does not change endpoints, secrets, mailbox configuration or delivery behavior.
- `VISUAL_FOUNDATION_ENABLED` and modular composition remain off/legacy by default.

## Boundary introduced

`app.service_desk` provides versioned references for `task`, `process` and `email`, permission-safe
summaries, compatibility aliases, a common facade, Email→Task origin commands, a real manifest and
canonical permission mapping. The manifest has three separately permissioned navigation contributions,
so capability composition can omit Tasks, Processes or Email without importing their UI contribution.

The two priority Email task writers now persist/initialize tickets and create immutable email origins
through the facade. Existing task assignment/SLA services remain authoritative and unchanged. This is
an internal contract extraction, not a lifecycle rewrite.

## Ownership qualification

`management_processes` is compatibility storage for the current process center. Claims and vehicle
incidents represented through that storage remain conceptually Automotive-owned under the approved
architecture. Service Desk may expose orchestration references/summaries but does not acquire ownership
of the claim or vehicle lifecycle. A later Automotive adapter must classify those rows explicitly before
any physical change.

## Degradation and authorization

Historical summaries are restored only after an explicit read decision and contain no message body,
recipient list, mailbox grant or attachment path. Mailbox visibility and reply/approval restrictions
continue to be evaluated by the existing Email authorization functions; the canonical mapping does not
replace or broaden those restrictions.

## Reconciliation and reversibility

Synthetic tests cover stable references, identical ORM mappers/IDs, task assignment and SLA event
preservation, Email→Task origin linkage, process/email/task summaries, capability composition, default
deny and the presence of all history/delivery/audit tables. Existing Service Desk operations and
Postmark tests remain green.

Rollback is code-only: legacy routes remain and can return to direct compatibility calls. No migration,
dual write or data conversion exists in this phase.

## Remaining slices

1. Route remaining non-Email task creators through the facade, one characterized source at a time.
2. Define Process→Task commands and reconcile current management-process associations.
3. Expose Documents references for task/email attachments without transferring document ownership.
4. Characterize post-action destinations on ticket, process and email detail operations.
5. Add runtime capability-state enforcement only after the effective-access differential suite covers
   every mailbox and work-scope combination.

None of these items authorizes permission changes, mailbox configuration, real data or legacy removal.
