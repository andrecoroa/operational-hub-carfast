from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.admin import User
from app.models.case_workflow import (
    OperationalCase,
    ProcessPhaseExecution,
    ProcessPhaseInstance,
    ProcessProposalAcceptance,
    WorkflowAuditEvent,
    WorkflowOutboxEvent,
)
from app.models.task_templates import ProcessInstance, ProcessModelVersion
from app.models.tasks import Task
from app.services.authorization import get_user_permission_codes
from app.services.case_workflow_authorization import can_access_case


class WorkflowError(ValueError):
    pass


class InvalidTransitionError(WorkflowError):
    pass


class StaleRevisionError(WorkflowError):
    pass


PROCESS_TRANSITIONS = {
    "active": {"blocked", "completed", "cancelled"},
    "blocked": {"active", "cancelled"},
    "completed": {"active"},
    "cancelled": set(),
}
PHASE_TRANSITIONS = {
    "pending": {"active", "skipped"},
    "active": {"blocked", "awaiting_validation", "completed", "skipped"},
    "blocked": {"active", "skipped"},
    "awaiting_validation": {"active", "completed"},
    "completed": {"active"},
    "skipped": {"active"},
}


def now_utc() -> datetime:
    return datetime.now(UTC)


def require_global_permission(db: Session, actor_id: int | None, permission: str) -> User:
    actor = db.get(User, actor_id) if actor_id else None
    permissions = get_user_permission_codes(db, actor) if actor else set()
    if not actor or permission not in permissions:
        raise WorkflowError(f"Permission denied: {permission}")
    return actor


def require_case_action(
    db: Session, actor_id: int | None, case: OperationalCase, action: str
) -> User:
    actor = db.get(User, actor_id) if actor_id else None
    if not actor or not can_access_case(db, actor, case, action):
        raise WorkflowError(f"Case access denied: {action}")
    return actor


def audit(
    db: Session,
    aggregate_type: str,
    aggregate_id: int,
    action: str,
    actor_id: int | None,
    revision: int | None = None,
    *,
    reason: str | None = None,
    before: dict | None = None,
    after: dict | None = None,
) -> None:
    db.add(
        WorkflowAuditEvent(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            action=action,
            actor_id=actor_id,
            revision=revision,
            reason=reason,
            before_json=before,
            after_json=after,
            created_at=now_utc(),
        )
    )


def create_case(
    db: Session,
    *,
    title: str,
    organizational_unit_id: int,
    actor_id: int | None,
    description: str | None = None,
    human_code: str | None = None,
) -> OperationalCase:
    actor = require_global_permission(db, actor_id, "cases.create")
    probe = OperationalCase(
        title=title,
        workspace="processes",
        organizational_unit_id=organizational_unit_id,
        created_by_id=actor_id,
    )
    if not can_access_case(db, actor, probe, "write"):
        raise WorkflowError("Case organizational scope denied")
    case = OperationalCase(
        title=title,
        description=description,
        human_code=human_code,
        workspace="processes",
        organizational_unit_id=organizational_unit_id,
        status="open",
        revision=1,
        created_by_id=actor_id,
    )
    db.add(case)
    db.flush()
    audit(db, "case", case.id, "case.created", actor_id, case.revision)
    return case


def publish_process_model_version(
    db: Session, version: ProcessModelVersion, actor_id: int | None
) -> None:
    require_global_permission(db, actor_id, "process.models.publish")
    if version.status != "draft":
        raise InvalidTransitionError("Only draft process models can be published")
    phases = (
        version.definition_json.get("phases") if isinstance(version.definition_json, dict) else None
    )
    if not isinstance(phases, list) or not phases:
        raise WorkflowError("Process model requires at least one phase")
    keys = [phase.get("key") for phase in phases if isinstance(phase, dict)]
    if len(keys) != len(phases) or any(not key for key in keys) or len(set(keys)) != len(keys):
        raise WorkflowError("Process phases require unique keys")
    version.status = "published"
    version.published_at = now_utc()
    audit(
        db, "process_model_version", version.id, "definition.published", actor_id, version.version
    )


def sale_operation_key(proposal_id: str, version: int, vehicle_id: int, kind: str) -> str:
    return f"sale:{proposal_id}:{version}:{vehicle_id}:{kind}"


def create_sale_process(
    db: Session,
    *,
    case: OperationalCase,
    model_version: ProcessModelVersion,
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
    if model_version.status != "published":
        raise WorkflowError("A published process model version is required")
    active = db.scalar(
        select(ProcessInstance).where(
            ProcessInstance.proposal_logical_id == proposal_logical_id,
            ProcessInstance.vehicle_id == vehicle_id,
            ProcessInstance.process_kind == process_kind,
            ProcessInstance.deleted_at.is_(None),
            ProcessInstance.status.in_({"active", "blocked"}),
        )
    )
    if active:
        if active.accepted_proposal_version == proposal_version:
            return active
        raise WorkflowError("An active process exists; accept the new proposal explicitly")
    key = sale_operation_key(proposal_logical_id, proposal_version, vehicle_id, process_kind)
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(func.hashtext(key))))
        active = db.scalar(
            select(ProcessInstance).where(
                ProcessInstance.proposal_logical_id == proposal_logical_id,
                ProcessInstance.vehicle_id == vehicle_id,
                ProcessInstance.process_kind == process_kind,
                ProcessInstance.deleted_at.is_(None),
                ProcessInstance.status.in_({"active", "blocked"}),
            )
        )
        if active:
            if active.accepted_proposal_version == proposal_version:
                return active
            raise WorkflowError("An active process exists; accept the new proposal explicitly")
    existing = db.scalar(select(ProcessInstance).where(ProcessInstance.operation_key == key))
    if existing:
        return existing
    process = ProcessInstance(
        case_id=locked_case.id,
        model_version_id=model_version.id,
        model_snapshot_json=model_version.definition_json,
        model_snapshot_digest=model_version.definition_digest,
        title=title,
        status="active",
        source="sale",
        context_json={"proposal_logical_id": proposal_logical_id},
        organizational_unit_code=None,
        created_by_id=actor_id,
        vehicle_id=vehicle_id,
        process_kind=process_kind,
        proposal_logical_id=proposal_logical_id,
        accepted_proposal_version=proposal_version,
        operation_key=key,
        revision=1,
    )
    db.add(process)
    db.flush()
    phases = model_version.definition_json["phases"]
    for index, phase in enumerate(phases, start=1):
        db.add(
            ProcessPhaseInstance(
                process_instance_id=process.id,
                phase_key=phase["key"],
                title=phase.get("title") or phase["key"],
                sort_order=phase.get("sort_order", index),
                definition_snapshot_json=phase,
                status="pending",
                execution_mode="direct",
                sensitive_validation=bool(phase.get("sensitive_validation")),
                revision=1,
            )
        )
    db.add(
        ProcessProposalAcceptance(
            process_instance_id=process.id,
            proposal_version=proposal_version,
            accepted_by_id=actor_id,
            accepted_at=now_utc(),
        )
    )
    audit(db, "process", process.id, "process.created", actor_id, process.revision)
    return process


def _lock_process(db: Session, process_id: int) -> ProcessInstance:
    process = db.scalar(
        select(ProcessInstance).where(ProcessInstance.id == process_id).with_for_update()
    )
    if not process or process.deleted_at:
        raise WorkflowError("Process not found")
    return process


def transition_phase(
    db: Session,
    *,
    phase_id: int,
    expected_revision: int,
    target: str,
    actor_id: int | None,
    reason: str | None = None,
) -> ProcessPhaseInstance:
    provisional = db.get(ProcessPhaseInstance, phase_id)
    if not provisional:
        raise WorkflowError("Phase not found")
    process = _lock_process(db, provisional.process_instance_id)
    phase = db.scalar(
        select(ProcessPhaseInstance).where(ProcessPhaseInstance.id == phase_id).with_for_update()
    )
    case = db.get(OperationalCase, process.case_id)
    sensitive_terminal = phase.sensitive_validation and target in {"completed", "skipped"}
    require_case_action(db, actor_id, case, "validate" if sensitive_terminal else "execute")
    if process.status in {"completed", "cancelled"}:
        raise WorkflowError("Completed or cancelled process cannot change phases")
    if phase.revision != expected_revision:
        raise StaleRevisionError("Revision is stale")
    if target not in PHASE_TRANSITIONS.get(phase.status, set()):
        raise InvalidTransitionError(f"Invalid transition {phase.status} -> {target}")
    if phase.status in {"completed", "skipped"} and target == "active":
        require_global_permission(db, actor_id, "process.instances.reopen")
        if not reason:
            raise WorkflowError("Reopening requires a reason")
    if sensitive_terminal:
        if phase.status != "awaiting_validation":
            raise WorkflowError("Sensitive phase requires validation")
        if not phase.submitted_by_id or phase.submitted_by_id == actor_id:
            raise WorkflowError("Sensitive phase requires a different validator")
        phase.validated_by_id = actor_id
    old = phase.status
    phase.status = target
    phase.revision += 1
    if target == "awaiting_validation":
        phase.submitted_by_id = actor_id
    if target == "active" and phase.started_at is None:
        phase.started_at = now_utc()
    if target in {"completed", "skipped"}:
        phase.completed_by_id = actor_id
        phase.completed_at = now_utc()
    elif target == "active":
        phase.completed_by_id = None
        phase.completed_at = None
        phase.validated_by_id = None
    audit(
        db,
        "phase",
        phase.id,
        f"workflow.{target}",
        actor_id,
        phase.revision,
        reason=reason,
        before={"status": old},
        after={"status": target},
    )
    return phase


def transition_process(
    db: Session,
    *,
    process_id: int,
    expected_revision: int,
    target: str,
    actor_id: int | None,
    reason: str | None = None,
) -> ProcessInstance:
    process = _lock_process(db, process_id)
    case = db.get(OperationalCase, process.case_id)
    require_case_action(db, actor_id, case, "execute")
    if process.revision != expected_revision:
        raise StaleRevisionError("Revision is stale")
    if target not in PROCESS_TRANSITIONS.get(process.status, set()):
        raise InvalidTransitionError(f"Invalid transition {process.status} -> {target}")
    if process.status == "completed" and target == "active":
        require_global_permission(db, actor_id, "process.instances.reopen")
        if not reason:
            raise WorkflowError("Reopening requires a reason")
    if target == "completed":
        phases = db.scalars(
            select(ProcessPhaseInstance)
            .where(
                ProcessPhaseInstance.process_instance_id == process.id,
                ProcessPhaseInstance.deleted_at.is_(None),
            )
            .with_for_update()
        ).all()
        if any(phase.status not in {"completed", "skipped"} for phase in phases):
            raise WorkflowError("Process has incomplete phases")
    if target in {"completed", "cancelled"}:
        active_execution = db.scalar(
            select(ProcessPhaseExecution.id)
            .join(
                ProcessPhaseInstance,
                ProcessPhaseInstance.id == ProcessPhaseExecution.phase_instance_id,
            )
            .where(
                ProcessPhaseInstance.process_instance_id == process.id,
                ProcessPhaseExecution.active.is_(True),
            )
            .limit(1)
        )
        if active_execution:
            raise WorkflowError("Process has active delegated executions")
    old = process.status
    process.status = target
    process.revision += 1
    process.completed_at = now_utc() if target == "completed" else None
    audit(
        db,
        "process",
        process.id,
        f"workflow.{target}",
        actor_id,
        process.revision,
        reason=reason,
        before={"status": old},
        after={"status": target},
    )
    return process


def delegate_phase_to_task(
    db: Session,
    *,
    phase_id: int,
    expected_revision: int,
    actor_id: int | None,
    idempotency_key: str,
) -> ProcessPhaseExecution:
    if db.bind and db.bind.dialect.name == "postgresql":
        db.execute(select(func.pg_advisory_xact_lock(phase_id)))
    phase = db.get(ProcessPhaseInstance, phase_id)
    if not phase:
        raise WorkflowError("Phase not found")
    process = _lock_process(db, phase.process_instance_id)
    case = db.get(OperationalCase, process.case_id)
    require_case_action(db, actor_id, case, "delegate")
    existing = db.scalar(
        select(ProcessPhaseExecution).where(
            ProcessPhaseExecution.idempotency_key == idempotency_key
        )
    )
    if existing:
        if existing.phase_instance_id != phase.id or existing.kind != "task":
            raise WorkflowError("Idempotency key belongs to a different intent")
        return existing
    if case.status != "open" or case.deleted_at:
        raise WorkflowError("Case is not open")
    if process.status not in {"active", "blocked"} or process.deleted_at:
        raise WorkflowError("Process is not executable")
    locked_phase = db.scalar(
        select(ProcessPhaseInstance).where(ProcessPhaseInstance.id == phase.id).with_for_update()
    )
    if locked_phase.revision != expected_revision:
        raise StaleRevisionError("Revision is stale")
    if locked_phase.status not in {"pending", "active", "blocked"} or locked_phase.deleted_at:
        raise WorkflowError("Phase cannot be delegated")
    if db.scalar(
        select(ProcessPhaseExecution.id).where(
            ProcessPhaseExecution.phase_instance_id == locked_phase.id,
            ProcessPhaseExecution.active.is_(True),
        )
    ):
        raise WorkflowError("Phase already has an active execution")
    task = Task(
        case_id=case.id,
        title=locked_phase.title,
        description=locked_phase.definition_snapshot_json.get("instructions"),
        task_type="operational_task",
        source="process",
        status="new",
        priority="normal",
        created_by_id=actor_id,
        process_instance_id=process.id,
        process_step_code=locked_phase.phase_key,
    )
    db.add(task)
    db.flush()
    execution = ProcessPhaseExecution(
        phase_instance_id=locked_phase.id,
        kind="task",
        status="active",
        active=True,
        task_id=task.id,
        idempotency_key=idempotency_key,
        created_by_id=actor_id,
    )
    db.add(execution)
    locked_phase.execution_mode = "task"
    locked_phase.revision += 1
    db.add(
        WorkflowOutboxEvent(
            event_type="phase.delegated.task",
            aggregate_type="phase",
            aggregate_id=locked_phase.id,
            idempotency_key=f"outbox:{idempotency_key}",
            payload_json={"phase_id": locked_phase.id, "task_id": task.id},
            status="pending",
            attempts=0,
            available_at=now_utc(),
            created_at=now_utc(),
        )
    )
    audit(db, "phase", locked_phase.id, "phase.delegated.task", actor_id, locked_phase.revision)
    return execution


def accept_new_proposal_version(
    db: Session,
    *,
    process_id: int,
    proposal_version: int,
    expected_revision: int,
    actor_id: int | None,
    source_reference: str | None = None,
) -> None:
    process = _lock_process(db, process_id)
    case = db.get(OperationalCase, process.case_id)
    require_case_action(db, actor_id, case, "execute")
    if process.status in {"completed", "cancelled"}:
        raise WorkflowError("Completed or cancelled process cannot be rewritten")
    if process.revision != expected_revision:
        raise StaleRevisionError("Revision is stale")
    if db.scalar(
        select(ProcessProposalAcceptance.id).where(
            ProcessProposalAcceptance.process_instance_id == process.id,
            ProcessProposalAcceptance.proposal_version == proposal_version,
        )
    ):
        return
    process.accepted_proposal_version = proposal_version
    process.revision += 1
    db.add(
        ProcessProposalAcceptance(
            process_instance_id=process.id,
            proposal_version=proposal_version,
            accepted_by_id=actor_id,
            source_reference=source_reference,
            accepted_at=now_utc(),
        )
    )
    audit(db, "process", process.id, "proposal.accepted", actor_id, process.revision)


def close_case(
    db: Session,
    *,
    case_id: int,
    actor_id: int | None,
    override: bool = False,
    reason: str | None = None,
) -> None:
    case = db.scalar(select(OperationalCase).where(OperationalCase.id == case_id).with_for_update())
    if not case:
        raise WorkflowError("Case not found")
    require_case_action(db, actor_id, case, "write")
    if case.status == "closed":
        raise InvalidTransitionError("Case is already closed")
    # Test and worker sessions may disable autoflush. Persist preceding process
    # transitions before enforcing the database-backed closure invariant.
    db.flush()
    active = db.scalar(
        select(func.count(ProcessInstance.id)).where(
            ProcessInstance.case_id == case.id,
            ProcessInstance.status.in_({"active", "blocked"}),
            ProcessInstance.deleted_at.is_(None),
        )
    )
    if active and not override:
        raise WorkflowError("Case has active processes")
    if override:
        require_case_action(db, actor_id, case, "close_override")
        if not reason:
            raise WorkflowError("Override requires a reason")
    old = case.status
    case.status = "closed"
    case.closed_at = now_utc()
    case.revision += 1
    audit(
        db,
        "case",
        case.id,
        "case.closed.override" if override else "case.closed",
        actor_id,
        case.revision,
        reason=reason,
        before={"status": old},
        after={"status": "closed"},
    )
