from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.admin import User
from app.models.cases import (
    OperationalCase,
    PhaseDefinition,
    PhaseExecution,
    PhaseInstance,
    ProcessDefinitionVersion,
    ProcessInstance,
    ProcessProposalAcceptance,
    WorkflowAuditEvent,
    WorkflowOutboxEvent,
)
from app.services.authorization import get_user_permission_codes
from app.services.case_authorization import can_access_case


class WorkflowError(ValueError):
    pass


class InvalidTransitionError(WorkflowError):
    pass


class StaleRevisionError(WorkflowError):
    pass


PROCESS_TRANSITIONS = {
    "draft": {"active", "cancelled"},
    "active": {"blocked", "completed", "cancelled"},
    "blocked": {"active", "cancelled"},
    "completed": {"active"},
    "cancelled": set(),
}
PHASE_TRANSITIONS = {
    "pending": {"active", "delegated", "skipped"},
    "active": {"delegated", "awaiting_validation", "completed", "blocked"},
    "delegated": {"active", "awaiting_validation", "completed", "blocked"},
    "awaiting_validation": {"active", "completed"},
    "blocked": {"active", "skipped"},
    "completed": {"active"},
    "skipped": {"active"},
}


def require_global_permission(db: Session, actor_id: int | None, permission: str) -> User:
    actor = db.get(User, actor_id) if actor_id else None
    permissions = get_user_permission_codes(db, actor) if actor and actor.active else set()
    if not actor or not ({permission, "admin.manage"} & permissions):
        raise WorkflowError(f"Missing permission: {permission}")
    return actor


def require_case_action(
    db: Session, actor_id: int | None, case: OperationalCase, action: str
) -> User:
    actor = db.get(User, actor_id) if actor_id else None
    if not actor or not can_access_case(db, actor, case, action):
        raise WorkflowError(f"Case access denied: {action}")
    return actor


def now_utc() -> datetime:
    return datetime.now(UTC)


def audit(
    db: Session,
    aggregate_type: str,
    aggregate_id: int,
    action: str,
    actor_id: int | None,
    revision: int,
    *,
    reason: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
    idempotency_key: str | None = None,
) -> None:
    db.add(
        WorkflowAuditEvent(
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            action=action,
            actor_id=actor_id,
            revision=revision,
            reason=reason,
            before_json=before,
            after_json=after,
            idempotency_key=idempotency_key,
            created_at=now_utc(),
        )
    )


def create_case(
    db: Session,
    *,
    title: str,
    organizational_unit_id: int | None,
    actor_id: int | None,
) -> OperationalCase:
    actor = require_global_permission(db, actor_id, "cases.write")
    if "admin.manage" not in get_user_permission_codes(db, actor):
        scoped_case = OperationalCase(organizational_unit_id=organizational_unit_id, title="scope")
        if not can_access_case(db, actor, scoped_case, "write"):
            raise WorkflowError("Case organizational scope denied")
    case = OperationalCase(
        title=title.strip(),
        status="open",
        organizational_unit_id=organizational_unit_id,
        created_by_id=actor_id,
    )
    db.add(case)
    db.flush()
    case.human_code = f"CAS-{now_utc().year}-{case.id:06d}"
    audit(
        db,
        "case",
        case.id,
        "case.created",
        actor_id,
        case.revision,
        after={"status": case.status, "organizational_unit_id": organizational_unit_id},
    )
    return case


def publish_definition_version(
    db: Session,
    version: ProcessDefinitionVersion,
    actor_id: int | None,
) -> None:
    require_global_permission(db, actor_id, "processes.publish")
    if version.status != "draft":
        raise InvalidTransitionError("Only draft definitions can be published")
    version.status = "published"
    version.published_at = now_utc()
    audit(db, "definition_version", version.id, "definition.published", actor_id, version.version)


def ensure_definition_mutable(version: ProcessDefinitionVersion) -> None:
    if version.status != "draft":
        raise WorkflowError("Published or retired definitions are immutable")


def sale_operation_key(proposal_id: str, version: int, vehicle_id: int, kind: str) -> str:
    return f"sale:{proposal_id}:{version}:{vehicle_id}:{kind}"


def create_sale_process(
    db: Session,
    *,
    case: OperationalCase,
    definition_version: ProcessDefinitionVersion,
    proposal_logical_id: str,
    proposal_version: int,
    vehicle_id: int,
    title: str,
    actor_id: int | None,
    process_kind: str = "sale_settlement",
) -> ProcessInstance:
    locked_case = db.scalar(
        select(OperationalCase).where(OperationalCase.id == case.id).with_for_update()
    )
    if not locked_case:
        raise WorkflowError("Case not found")
    require_case_action(db, actor_id, locked_case, "execute")
    if locked_case.status != "open" or locked_case.deleted_at:
        raise WorkflowError("Case is not open")
    if definition_version.status != "published":
        raise WorkflowError("A published definition version is required")
    key = sale_operation_key(proposal_logical_id, proposal_version, vehicle_id, process_kind)
    active = db.scalar(
        select(ProcessInstance).where(
            ProcessInstance.proposal_logical_id == proposal_logical_id,
            ProcessInstance.vehicle_id == vehicle_id,
            ProcessInstance.process_kind == process_kind,
            ProcessInstance.deleted_at.is_(None),
            ProcessInstance.status.in_({"draft", "active", "blocked"}),
        )
    )
    if active:
        if active.accepted_proposal_version == proposal_version:
            return active
        raise WorkflowError("An active process exists; accept the new proposal version explicitly")
    existing = db.scalar(select(ProcessInstance).where(ProcessInstance.operation_key == key))
    if existing:
        return existing
    process = ProcessInstance(
        case_id=locked_case.id,
        definition_version_id=definition_version.id,
        title=title,
        status="active",
        vehicle_id=vehicle_id,
        proposal_logical_id=proposal_logical_id,
        accepted_proposal_version=proposal_version,
        process_kind=process_kind,
        operation_key=key,
        owner_id=actor_id,
    )
    try:
        with db.begin_nested():
            db.add(process)
            db.flush()
            db.add(
                ProcessProposalAcceptance(
                    process_id=process.id,
                    proposal_version=proposal_version,
                    accepted_by_id=actor_id,
                    accepted_at=now_utc(),
                )
            )
            for definition in db.scalars(
                select(PhaseDefinition)
                .where(PhaseDefinition.definition_version_id == definition_version.id)
                .order_by(PhaseDefinition.sort_order)
            ).all():
                db.add(
                    PhaseInstance(
                        process_id=process.id,
                        definition_phase_id=definition.id,
                        definition_version_id=definition_version.id,
                        status="pending",
                    )
                )
            audit(
                db,
                "process",
                process.id,
                "process.created",
                actor_id,
                process.revision,
                after={"operation_key": key},
                idempotency_key=f"create:{key}",
            )
            db.flush()
    except IntegrityError:
        concurrent = db.scalar(select(ProcessInstance).where(ProcessInstance.operation_key == key))
        if concurrent:
            return concurrent
        raise
    return process


def accept_new_proposal_version(
    db: Session,
    *,
    process: ProcessInstance,
    proposal_version: int,
    expected_revision: int,
    actor_id: int | None,
    source_reference: str | None = None,
) -> None:
    case = db.get(OperationalCase, process.case_id)
    require_case_action(db, actor_id, case, "execute")
    if process.status == "completed":
        raise WorkflowError("Completed processes cannot be rewritten")
    if proposal_version <= (process.accepted_proposal_version or 0):
        raise WorkflowError("Proposal version must advance")
    old = process.accepted_proposal_version
    result = db.execute(
        update(ProcessInstance)
        .where(
            ProcessInstance.id == process.id,
            ProcessInstance.revision == expected_revision,
            ProcessInstance.status != "completed",
        )
        .values(
            accepted_proposal_version=proposal_version,
            revision=expected_revision + 1,
            updated_at=now_utc(),
        )
    )
    if result.rowcount != 1:
        raise StaleRevisionError("Process revision is stale")
    db.expire(process)
    db.add(
        ProcessProposalAcceptance(
            process_id=process.id,
            proposal_version=proposal_version,
            source_reference=source_reference,
            accepted_by_id=actor_id,
            accepted_at=now_utc(),
        )
    )
    audit(
        db,
        "process",
        process.id,
        "proposal.version.accepted",
        actor_id,
        expected_revision + 1,
        before={"proposal_version": old},
        after={"proposal_version": proposal_version},
    )


def _transition(
    db: Session,
    model,
    object_id: int,
    expected_revision: int,
    target: str,
    transitions: dict,
    actor_id: int | None,
    reason: str | None,
):
    process = None
    if model is ProcessInstance:
        item = db.scalar(
            select(ProcessInstance).where(ProcessInstance.id == object_id).with_for_update()
        )
        process = item
    else:
        provisional = db.get(PhaseInstance, object_id)
        if not provisional:
            raise WorkflowError("Workflow item not found")
        process = db.scalar(
            select(ProcessInstance)
            .where(ProcessInstance.id == provisional.process_id)
            .with_for_update()
        )
        item = db.scalar(
            select(PhaseInstance).where(PhaseInstance.id == object_id).with_for_update()
        )
    if not item or item.deleted_at:
        raise WorkflowError("Workflow item not found")
    if model is PhaseInstance and (not process or process.status in {"completed", "cancelled"}):
        raise WorkflowError("Completed or cancelled process cannot change phases")
    if target not in transitions.get(item.status, set()):
        raise InvalidTransitionError(f"Invalid transition {item.status} -> {target}")
    if item.status in {"completed", "skipped"} and target == "active" and not reason:
        raise WorkflowError("Reopening requires a reason")
    if item.status in {"completed", "skipped"} and target == "active":
        require_global_permission(
            db, actor_id, "phases.reopen" if model is PhaseInstance else "processes.reopen"
        )
    if model is ProcessInstance and target == "completed":
        phases = db.scalars(
            select(PhaseInstance)
            .where(
                PhaseInstance.process_id == item.id,
                PhaseInstance.deleted_at.is_(None),
            )
            .with_for_update()
        ).all()
        if any(phase.status not in {"completed", "skipped"} for phase in phases):
            raise WorkflowError("Process has incomplete phases")
    if model is PhaseInstance and target == "completed":
        definition = db.get(PhaseDefinition, item.definition_phase_id)
        if definition.sensitive_validation and item.status != "awaiting_validation":
            raise WorkflowError("Sensitive phase requires validation")
        if definition.sensitive_validation:
            case = db.get(OperationalCase, process.case_id)
            require_case_action(db, actor_id, case, "validate")
            if not item.submitted_by_id or item.submitted_by_id == actor_id:
                raise WorkflowError("Sensitive phase requires a different validator")
    old = item.status
    values = {"status": target, "revision": expected_revision + 1, "updated_at": now_utc()}
    if target == "completed":
        values["completed_at"] = now_utc()
        if model is PhaseInstance:
            values["completed_by_id"] = actor_id
            definition = db.get(PhaseDefinition, item.definition_phase_id)
            if definition.sensitive_validation:
                values["validated_by_id"] = actor_id
    if target == "awaiting_validation" and model is PhaseInstance:
        values["submitted_by_id"] = actor_id
    if target == "active":
        values["completed_at"] = None
        if model is PhaseInstance:
            values["completed_by_id"] = None
            values["validated_by_id"] = None
            if item.started_at is None:
                values["started_at"] = now_utc()
    result = db.execute(
        update(model)
        .where(model.id == object_id, model.revision == expected_revision)
        .values(**values)
    )
    if result.rowcount != 1:
        raise StaleRevisionError("Revision is stale")
    db.expire(item)
    audit(
        db,
        "phase" if model is PhaseInstance else "process",
        object_id,
        f"workflow.{target}",
        actor_id,
        expected_revision + 1,
        reason=reason,
        before={"status": old},
        after={"status": target},
    )
    return item


def transition_process(
    db: Session,
    *,
    process_id: int,
    expected_revision: int,
    target: str,
    actor_id: int | None,
    reason: str | None = None,
) -> ProcessInstance:
    process = db.get(ProcessInstance, process_id)
    require_case_action(db, actor_id, db.get(OperationalCase, process.case_id), "execute")
    return _transition(
        db,
        ProcessInstance,
        process_id,
        expected_revision,
        target,
        PROCESS_TRANSITIONS,
        actor_id,
        reason,
    )


def transition_phase(
    db: Session,
    *,
    phase_id: int,
    expected_revision: int,
    target: str,
    actor_id: int | None,
    reason: str | None = None,
) -> PhaseInstance:
    phase = db.get(PhaseInstance, phase_id)
    process = db.get(ProcessInstance, phase.process_id)
    require_case_action(db, actor_id, db.get(OperationalCase, process.case_id), "execute")
    return _transition(
        db,
        PhaseInstance,
        phase_id,
        expected_revision,
        target,
        PHASE_TRANSITIONS,
        actor_id,
        reason,
    )


def delegate_phase_to_task(
    db: Session,
    *,
    phase: PhaseInstance,
    expected_revision: int,
    actor_id: int | None,
    idempotency_key: str,
) -> PhaseExecution:
    process = db.get(ProcessInstance, phase.process_id)
    require_case_action(db, actor_id, db.get(OperationalCase, process.case_id), "delegate")
    existing = db.scalar(
        select(PhaseExecution).where(PhaseExecution.idempotency_key == idempotency_key)
    )
    if existing:
        if existing.phase_id != phase.id or existing.kind != "task":
            raise WorkflowError("Idempotency key belongs to a different intent")
        return existing
    if db.scalar(
        select(PhaseExecution).where(
            PhaseExecution.phase_id == phase.id, PhaseExecution.active.is_(True)
        )
    ):
        raise WorkflowError("Phase already has an active execution")
    try:
        transition_phase(
            db,
            phase_id=phase.id,
            expected_revision=expected_revision,
            target="delegated",
            actor_id=actor_id,
        )
    except StaleRevisionError:
        concurrent = db.scalar(
            select(PhaseExecution).where(PhaseExecution.idempotency_key == idempotency_key)
        )
        if concurrent and concurrent.phase_id == phase.id and concurrent.kind == "task":
            return concurrent
        raise
    execution = PhaseExecution(
        phase_id=phase.id,
        kind="task",
        status="pending",
        active=True,
        idempotency_key=idempotency_key,
    )
    db.add(execution)
    db.flush()
    db.add(
        WorkflowOutboxEvent(
            event_key=f"create-task:{idempotency_key}",
            event_type="CreateTaskRequested",
            aggregate_type="phase_execution",
            aggregate_id=str(execution.id),
            payload_json={"phase_id": phase.id, "execution_id": execution.id},
            status="pending",
            attempts=0,
            available_at=now_utc(),
            created_at=now_utc(),
        )
    )
    return execution


def close_case(
    db: Session,
    *,
    case: OperationalCase,
    actor_id: int | None,
    override: bool = False,
    reason: str | None = None,
) -> None:
    locked_case = db.scalar(
        select(OperationalCase).where(OperationalCase.id == case.id).with_for_update()
    )
    if not locked_case:
        raise WorkflowError("Case not found")
    require_case_action(db, actor_id, locked_case, "write")
    if locked_case.status == "closed":
        raise InvalidTransitionError("Case is already closed")
    active = db.scalar(
        select(ProcessInstance.id)
        .where(
            ProcessInstance.case_id == locked_case.id,
            ProcessInstance.status.in_({"draft", "active", "blocked"}),
        )
        .limit(1)
    )
    if active and not override:
        raise WorkflowError("Case has active processes")
    if override:
        require_case_action(db, actor_id, locked_case, "close_override")
        if not reason:
            raise WorkflowError("Override requires a reason")
    old = locked_case.status
    locked_case.status = "closed"
    locked_case.closed_at = now_utc()
    locked_case.revision += 1
    audit(
        db,
        "case",
        locked_case.id,
        "case.closed.override" if override else "case.closed",
        actor_id,
        locked_case.revision,
        reason=reason,
        before={"status": old},
        after={"status": "closed"},
    )


def soft_delete_case(
    db: Session,
    case: OperationalCase,
    actor_id: int | None,
    reason: str,
) -> None:
    require_case_action(db, actor_id, case, "write")
    if case.deleted_at:
        raise InvalidTransitionError("Case is already deleted")
    if not reason:
        raise WorkflowError("Soft delete requires a reason")
    case.deleted_at = now_utc()
    case.revision += 1
    audit(db, "case", case.id, "case.soft_deleted", actor_id, case.revision, reason=reason)
