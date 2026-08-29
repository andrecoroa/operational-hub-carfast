from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.auth import CurrentUser, require_permission
from app.api.deps import DbSession
from app.models.admin import User
from app.models.organization import Team, TeamMember
from app.models.tasks import (
    Task,
    TaskAssignmentEvent,
    TaskComment,
    TaskHistory,
    TaskSlaEvent,
)
from app.models.work_hierarchy import ServiceDeskTicketType
from app.schemas.common import ApiModel
from app.schemas.tasks import (
    TaskCommentCreate,
    TaskCommentRead,
    TaskCreate,
    TaskRead,
    TaskUpdate,
)
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.services.classification_proposals import (
    attach_selection_to_entity,
    detach_entity_proposals,
    validate_proposal_selection,
)
from app.services.service_desk import (
    assign_task_executor,
    assignment_target_user_allowed,
    category_team_is_eligible,
    category_user_is_eligible,
    claim_task,
    default_ticket_type,
    initialize_task_service_desk,
    mark_task_first_response,
    mark_task_resolved,
    pause_task_sla,
    resume_task_sla,
)
from app.services.work_classification import (
    user_work_scope_allows,
    user_work_scope_filter,
    validate_work_hierarchy,
)

router = APIRouter(prefix="/tasks")
TaskReader = Annotated[object, Depends(require_permission("tasks.read"))]
TaskWriter = Annotated[object, Depends(require_permission("tasks.write"))]
TASK_ARCHIVE_STATUSES = {"resolved", "closed", "cancelled", "no_action_needed"}
TASK_RESPONSIBLE_ONLY_STATUSES = {
    "in_execution",
    "resolved",
    "closed",
    "cancelled",
    "no_action_needed",
}
TASK_WAITING_REASONS = {
    "customer",
    "partner_broker",
    "other_entity",
    "clarification",
    "validation",
    "decision",
    "other",
}


class ServiceDeskTaskCreate(TaskCreate):
    """Additive Service Desk contract; legacy TaskCreate payloads remain valid."""

    ticket_type_id: int | None = None
    work_queue_id: int | None = None
    work_department_id: int | None = None
    work_category_id: int | None = None
    work_subcategory_id: int | None = None
    provisional_category_id: int | None = None
    provisional_subcategory_id: int | None = None
    classification_other_text: str | None = None
    team_requires_claim: bool = False


class ServiceDeskTaskUpdate(TaskUpdate):
    ticket_type_id: int | None = None
    work_queue_id: int | None = None
    work_department_id: int | None = None
    work_category_id: int | None = None
    work_subcategory_id: int | None = None
    provisional_category_id: int | None = None
    provisional_subcategory_id: int | None = None
    classification_other_text: str | None = None
    team_requires_claim: bool = False


class ServiceDeskTaskRead(TaskRead):
    ticket_type_id: int | None = None
    subcategory: str | None = None
    work_queue_id: int | None = None
    work_department_id: int | None = None
    work_category_id: int | None = None
    work_subcategory_id: int | None = None
    provisional_category_id: int | None = None
    provisional_subcategory_id: int | None = None
    classification_status: str = "unclassified"
    classification_other_text: str | None = None
    supervisor_user_id: int | None = None
    assignment_mode: str = "manual"
    assignment_state: str = "waiting_assignment"
    assigned_by_id: int | None = None
    assigned_at: datetime | None = None
    claimed_by_id: int | None = None
    claimed_at: datetime | None = None
    first_response_at: datetime | None = None
    first_response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None
    resolved_at: datetime | None = None
    sla_first_response_minutes: int | None = None
    sla_resolution_minutes: int | None = None
    sla_warning_minutes: int = 60
    sla_pause_on_waiting: bool = True
    sla_timezone: str = "Europe/Lisbon"
    sla_paused_at: datetime | None = None
    sla_total_paused_seconds: int = 0


class TaskAssignmentUpdate(ApiModel):
    user_id: int | None = None
    team_id: int | None = None
    require_claim: bool = False
    reason: str | None = None


class TaskCloseRequest(ApiModel):
    status: str = "closed"
    reason: str | None = None


@router.get("", response_model=list[ServiceDeskTaskRead])
def list_tasks(
    db: DbSession,
    current_user: CurrentUser,
    _: TaskReader,
    status_filter: str | None = None,
    task_type: str | None = None,
    team_id: int | None = None,
    assigned_to_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    stmt = select(Task).order_by(Task.id.desc())
    scope_filter = user_work_scope_filter(
        db, user_id=current_user.id, task_model=Task, action="read"
    )
    if scope_filter is not None:
        stmt = stmt.where(scope_filter)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    if task_type:
        stmt = stmt.where(Task.task_type == task_type)
    if team_id:
        stmt = stmt.where(Task.team_id == team_id)
    if assigned_to_id:
        stmt = stmt.where(Task.assigned_to_id == assigned_to_id)
    if entity_type:
        stmt = stmt.where(Task.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(Task.entity_id == entity_id)
    return db.scalars(stmt.limit(limit).offset(offset)).all()


@router.post("", response_model=ServiceDeskTaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: ServiceDeskTaskCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    values = payload.model_dump(
        exclude={
            "team_requires_claim",
            "provisional_category_id",
            "provisional_subcategory_id",
        }
    )
    hierarchy_requested = _hierarchy_requested(payload.model_fields_set)
    hierarchy = None
    proposal_selection = None
    if hierarchy_requested:
        permissions = get_user_permission_codes(db, current_user)
        uses_provisional = bool(
            payload.provisional_category_id or payload.provisional_subcategory_id
        )
        required_permission = (
            "classification.provisional.use"
            if uses_provisional
            else "classification.active.use"
        )
        if required_permission not in permissions:
            raise HTTPException(status_code=403, detail="Classification permission denied.")
        hierarchy = validate_work_hierarchy(
            db,
            queue_id=payload.work_queue_id,
            department_id=payload.work_department_id,
            category_id=payload.work_category_id,
            subcategory_id=payload.work_subcategory_id,
            other_text=payload.classification_other_text or "",
            require_category=not bool(payload.provisional_category_id),
        )
        if not hierarchy:
            raise HTTPException(status_code=400, detail="Invalid or inactive work hierarchy.")
        try:
            proposal_selection = validate_proposal_selection(
                db,
                department_id=hierarchy.department.id,
                official_category_id=hierarchy.category.id if hierarchy.category else None,
                category_proposal_id=payload.provisional_category_id,
                subcategory_proposal_id=payload.provisional_subcategory_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    scope_values = _hierarchy_scope_values(hierarchy)
    if not user_work_scope_allows(
        db, user_id=current_user.id, **scope_values, action="create"
    ):
        raise HTTPException(status_code=403, detail="Work scope does not allow task creation.")

    ticket_type = _active_ticket_type(db, payload.ticket_type_id)
    validate_task_links(
        db,
        payload.team_id,
        payload.assigned_to_id,
        payload.delegated_to_team_id,
        payload.delegated_to_user_id,
        payload.waiting_for_team_id,
        payload.waiting_for_user_id,
        require_active=True,
    )
    validate_task_state(
        payload.status,
        payload.waiting_reason,
        payload.waiting_reason_detail,
        payload.delegated_to_user_id,
        payload.delegated_to_team_id,
    )

    if hierarchy:
        if payload.assigned_to_id and payload.team_id:
            raise HTTPException(status_code=400, detail="Choose at most one executor user or team.")
        if (payload.assigned_to_id or payload.team_id) and not user_work_scope_allows(
            db, user_id=current_user.id, **scope_values, action="assign"
        ):
            raise HTTPException(status_code=403, detail="Work scope does not allow assignment.")
        values.update(
            {
                "work_queue_id": hierarchy.queue.id,
                "work_department_id": hierarchy.department.id,
                "work_category_id": hierarchy.category.id if hierarchy.category else None,
                "work_subcategory_id": (
                    hierarchy.subcategory.id if hierarchy.subcategory else None
                ),
                "classification_status": hierarchy.status,
                "classification_other_text": hierarchy.other_text,
                "classification_updated_by_id": current_user.id,
                "classification_updated_at": datetime.now(timezone.utc),
            }
        )
    else:
        for field_name in (
            "work_queue_id",
            "work_department_id",
            "work_category_id",
            "work_subcategory_id",
            "provisional_category_id",
            "provisional_subcategory_id",
            "classification_other_text",
        ):
            values.pop(field_name, None)

    requested_user_id = values.pop("assigned_to_id", None)
    requested_team_id = values.pop("team_id", None)
    values["ticket_type_id"] = ticket_type.id if ticket_type else None
    task = Task(
        **values,
        created_by_id=current_user.id,
        assigned_to_id=None,
        team_id=None,
    )
    db.add(task)
    db.flush()
    if proposal_selection and (
        proposal_selection.category or proposal_selection.subcategory
    ):
        attach_selection_to_entity(
            db,
            entity=task,
            selection=proposal_selection,
            actor_user_id=current_user.id,
            module="service_desk_api",
        )
    if hierarchy:
        try:
            initialize_task_service_desk(
                db,
                task,
                actor_user_id=current_user.id,
                requested_user_id=requested_user_id,
                requested_team_id=requested_team_id,
            )
            if requested_team_id and payload.team_requires_claim:
                assign_task_executor(
                    db,
                    task,
                    actor_user_id=current_user.id,
                    team_id=requested_team_id,
                    require_claim=True,
                    reason="API task creation",
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        _initialize_legacy_task(
            db,
            task,
            actor_user_id=current_user.id,
            user_id=requested_user_id,
            team_id=requested_team_id,
        )

    record_task_history(db, task.id, current_user.id, "created", None, task.status)
    record_audit(
        db,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        after_json=payload.model_dump(mode="json"),
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=ServiceDeskTaskRead)
def get_task(task_id: int, db: DbSession, current_user: CurrentUser, _: TaskReader):
    return _get_visible_task(db, task_id, current_user, action="read")


@router.patch("/{task_id}", response_model=ServiceDeskTaskRead)
def update_task(
    task_id: int,
    payload: ServiceDeskTaskUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    task = _get_visible_task(db, task_id, current_user, action="update")
    changes = payload.model_dump(exclude_unset=True)
    team_requires_claim = bool(changes.pop("team_requires_claim", False))
    proposed_category_id = changes.pop("provisional_category_id", None)
    proposed_subcategory_id = changes.pop("provisional_subcategory_id", None)

    target_hierarchy = None
    proposal_selection = None
    if _hierarchy_requested(payload.model_fields_set):
        permissions = get_user_permission_codes(db, current_user)
        uses_provisional = bool(proposed_category_id or proposed_subcategory_id)
        required_permission = (
            "classification.provisional.use"
            if uses_provisional
            else "classification.active.use"
        )
        if required_permission not in permissions:
            raise HTTPException(status_code=403, detail="Classification permission denied.")
        target_hierarchy = validate_work_hierarchy(
            db,
            queue_id=changes.get("work_queue_id", task.work_queue_id),
            department_id=changes.get("work_department_id", task.work_department_id),
            category_id=changes.get("work_category_id", task.work_category_id),
            subcategory_id=changes.get("work_subcategory_id", task.work_subcategory_id),
            other_text=changes.get(
                "classification_other_text", task.classification_other_text or ""
            ),
            require_category=not bool(proposed_category_id),
        )
        if not target_hierarchy:
            raise HTTPException(status_code=400, detail="Invalid or inactive work hierarchy.")
        try:
            proposal_selection = validate_proposal_selection(
                db,
                department_id=target_hierarchy.department.id,
                official_category_id=(
                    target_hierarchy.category.id if target_hierarchy.category else None
                ),
                category_proposal_id=proposed_category_id,
                subcategory_proposal_id=proposed_subcategory_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not user_work_scope_allows(
            db,
            user_id=current_user.id,
            **_hierarchy_scope_values(target_hierarchy),
            action="update",
            task=task,
        ):
            raise HTTPException(status_code=403, detail="Target work scope does not allow update.")

    if "ticket_type_id" in changes:
        requested_ticket_type_id = changes["ticket_type_id"]
        if requested_ticket_type_id is None:
            changes["ticket_type_id"] = task.ticket_type_id
        elif requested_ticket_type_id != task.ticket_type_id:
            changes["ticket_type_id"] = _active_ticket_type(
                db, requested_ticket_type_id, required=True
            ).id

    assignment_requested = bool({"assigned_to_id", "team_id"} & payload.model_fields_set)
    requested_user_id = changes.pop("assigned_to_id", task.assigned_to_id)
    requested_team_id = changes.pop("team_id", task.team_id)
    if assignment_requested:
        if (
            "assigned_to_id" in payload.model_fields_set
            and "team_id" not in payload.model_fields_set
        ):
            requested_team_id = None
        if (
            "team_id" in payload.model_fields_set
            and "assigned_to_id" not in payload.model_fields_set
        ):
            requested_user_id = None
        if requested_user_id and requested_team_id:
            raise HTTPException(status_code=400, detail="Choose at most one executor user or team.")

    validate_task_links(
        db,
        requested_team_id if assignment_requested else None,
        requested_user_id if assignment_requested else None,
        changes.get("delegated_to_team_id"),
        changes.get("delegated_to_user_id"),
        changes.get("waiting_for_team_id"),
        changes.get("waiting_for_user_id"),
        require_active=True,
    )
    prior_status = task.status
    next_status = changes.get("status", prior_status)
    next_waiting_reason = changes.get("waiting_reason", task.waiting_reason)
    next_waiting_reason_detail = changes.get("waiting_reason_detail", task.waiting_reason_detail)
    next_delegated_user_id = changes.get("delegated_to_user_id", task.delegated_to_user_id)
    next_delegated_team_id = changes.get("delegated_to_team_id", task.delegated_to_team_id)
    if (
        "status" in changes
        and next_status in TASK_RESPONSIBLE_ONLY_STATUSES
        and not can_supervise_task(db, current_user, task)
    ):
        raise HTTPException(
            status_code=403,
            detail="Only the responsible user or an authorized profile can set this status.",
        )
    if (
        "delegated_to_user_id" in changes
        or "delegated_to_team_id" in changes
        or ("status" in changes and next_status == "delegated")
    ) and not can_supervise_task(db, current_user, task):
        raise HTTPException(
            status_code=403,
            detail="Only the responsible user or an authorized profile can delegate execution.",
        )
    validate_task_state(
        next_status,
        next_waiting_reason,
        next_waiting_reason_detail,
        next_delegated_user_id,
        next_delegated_team_id,
    )

    if "status" in changes and next_status in TASK_ARCHIVE_STATUSES:
        _require_task_scope(db, current_user, task, action="complete")
    if (
        "status" in changes
        and prior_status in TASK_ARCHIVE_STATUSES
        and next_status not in TASK_ARCHIVE_STATUSES
    ):
        _require_task_scope(db, current_user, task, action="complete")
        _require_task_scope(db, current_user, task, action="manage_sla")

    target_category_id = (
        target_hierarchy.category.id
        if target_hierarchy and target_hierarchy.category
        else task.work_category_id
    )
    if assignment_requested:
        _require_task_scope(db, current_user, task, action="assign")
        if target_hierarchy and not user_work_scope_allows(
            db,
            user_id=current_user.id,
            **_hierarchy_scope_values(target_hierarchy),
            action="assign",
            task=task,
        ):
            raise HTTPException(
                status_code=403,
                detail="Target work scope does not allow assignment.",
            )
        _validate_category_assignment(
            db, target_category_id, requested_user_id, requested_team_id
        )
    elif target_hierarchy:
        _validate_category_assignment(
            db,
            target_category_id,
            task.assigned_to_id,
            task.team_id,
            allow_empty=True,
        )

    before = {
        "status": task.status,
        "priority": task.priority,
        "team_id": task.team_id,
        "assigned_to_id": task.assigned_to_id,
        "work_category_id": task.work_category_id,
    }
    if target_hierarchy:
        changes.update(
            {
                "work_queue_id": target_hierarchy.queue.id,
                "work_department_id": target_hierarchy.department.id,
                "work_category_id": (
                    target_hierarchy.category.id if target_hierarchy.category else None
                ),
                "work_subcategory_id": (
                    target_hierarchy.subcategory.id if target_hierarchy.subcategory else None
                ),
                "classification_status": target_hierarchy.status,
                "classification_other_text": target_hierarchy.other_text,
                "classification_updated_by_id": current_user.id,
                "classification_updated_at": datetime.now(timezone.utc),
            }
        )
    else:
        for field_name in (
            "work_queue_id",
            "work_department_id",
            "work_category_id",
            "work_subcategory_id",
            "classification_other_text",
        ):
            changes.pop(field_name, None)

    for field, value in changes.items():
        old_value = getattr(task, field)
        setattr(task, field, value)
        record_task_history(db, task.id, current_user.id, field, old_value, value)
    if target_hierarchy:
        detach_entity_proposals(db, entity=task, actor_user_id=current_user.id)
        if proposal_selection and (
            proposal_selection.category or proposal_selection.subcategory
        ):
            attach_selection_to_entity(
                db,
                entity=task,
                selection=proposal_selection,
                actor_user_id=current_user.id,
                module="service_desk_api",
            )

    if assignment_requested:
        _assign_task_compatibly(
            db,
            task,
            actor_user_id=current_user.id,
            user_id=requested_user_id,
            team_id=requested_team_id,
            require_claim=team_requires_claim,
            reason="API task update",
        )

    now = datetime.now(timezone.utc)
    if next_status == "waiting" and prior_status != "waiting":
        pause_task_sla(
            db,
            task,
            actor_user_id=current_user.id,
            reason=next_waiting_reason or "Task waiting",
            now=now,
        )
    elif next_status != "waiting" and prior_status == "waiting":
        resume_task_sla(
            db,
            task,
            actor_user_id=current_user.id,
            reason="Task resumed",
            now=now,
        )
    if next_status in TASK_ARCHIVE_STATUSES:
        task.closed_at = task.closed_at or now
        mark_task_resolved(db, task, actor_user_id=current_user.id, now=now)
    elif "status" in changes:
        task.closed_at = None
        if task.resolved_at and prior_status in TASK_ARCHIVE_STATUSES:
            record_task_history(
                db, task.id, current_user.id, "resolved_at", task.resolved_at, None
            )
            task.resolved_at = None
            task.sla_paused_at = None
            task.resolution_due_at = (
                now + timedelta(minutes=task.sla_resolution_minutes)
                if task.sla_resolution_minutes is not None
                else None
            )
            db.add(
                TaskSlaEvent(
                    task_id=task.id,
                    actor_user_id=current_user.id,
                    action="reopened",
                    details_json={
                        "resolution_due_at": (
                            task.resolution_due_at.isoformat()
                            if task.resolution_due_at
                            else None
                        )
                    },
                )
            )

    record_audit(
        db,
        action="task.updated",
        entity_type="task",
        entity_id=task.id,
        before_json=before,
        after_json=payload.model_dump(mode="json", exclude_unset=True),
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/assignment", response_model=ServiceDeskTaskRead)
def update_task_assignment(
    task_id: int,
    payload: TaskAssignmentUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    task = _get_visible_task(db, task_id, current_user, action="assign")
    validate_task_links(db, payload.team_id, payload.user_id, require_active=True)
    _validate_category_assignment(
        db, task.work_category_id, payload.user_id, payload.team_id
    )
    _assign_task_compatibly(
        db,
        task,
        actor_user_id=current_user.id,
        user_id=payload.user_id,
        team_id=payload.team_id,
        require_claim=payload.require_claim,
        reason=payload.reason or "API assignment",
    )
    record_audit(
        db,
        action="task.assignment.updated",
        entity_type="task",
        entity_id=task.id,
        after_json=payload.model_dump(mode="json"),
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/claim", response_model=ServiceDeskTaskRead)
def claim_assigned_task(
    task_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    task = _get_visible_task(db, task_id, current_user, action="assume")
    try:
        claim_task(db, task, user_id=current_user.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    record_audit(
        db,
        action="task.claimed",
        entity_type="task",
        entity_id=task.id,
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.post("/{task_id}/close", response_model=ServiceDeskTaskRead)
def close_task(
    task_id: int,
    payload: TaskCloseRequest,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    if payload.status not in TASK_ARCHIVE_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid completion status.")
    task = _get_visible_task(db, task_id, current_user, action="complete")
    if not can_supervise_task(db, current_user, task):
        raise HTTPException(
            status_code=403,
            detail="Only the responsible user or an authorized profile can complete this task.",
        )
    previous_status = task.status
    task.status = payload.status
    now = datetime.now(timezone.utc)
    task.closed_at = task.closed_at or now
    mark_task_resolved(db, task, actor_user_id=current_user.id, now=now)
    record_task_history(
        db, task.id, current_user.id, "status", previous_status, payload.status
    )
    record_audit(
        db,
        action="task.closed",
        entity_type="task",
        entity_id=task.id,
        detail=payload.reason,
        before_json={"status": previous_status},
        after_json={"status": payload.status},
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}/comments", response_model=list[TaskCommentRead])
def list_task_comments(
    task_id: int,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskReader,
):
    _get_visible_task(db, task_id, current_user, action="read")
    return db.scalars(
        select(TaskComment).where(TaskComment.task_id == task_id).order_by(TaskComment.id)
    ).all()


@router.post(
    "/{task_id}/comments",
    response_model=TaskCommentRead,
    status_code=status.HTTP_201_CREATED,
)
def create_task_comment(
    task_id: int,
    payload: TaskCommentCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    task = _get_visible_task(db, task_id, current_user, action="respond")
    clean_comment = payload.comment.strip()
    if not clean_comment:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="comment_required")
    comment = TaskComment(task_id=task_id, user_id=current_user.id, comment=clean_comment)
    db.add(comment)
    mark_task_first_response(db, task, actor_user_id=current_user.id)
    record_audit(
        db,
        action="task.comment.created",
        entity_type="task",
        entity_id=task_id,
        user_id=current_user.id,
    )
    from app.services.task_center import create_task_notifications
    create_task_notifications(
        db, task=task, event_type="task_commented",
        title=f"Novo comentário: {task.title}", actor_user_id=current_user.id,
        detail=clean_comment,
    )
    db.commit()
    db.refresh(comment)
    return comment


def _hierarchy_requested(field_names: set[str]) -> bool:
    return bool(
        {
            "work_queue_id",
            "work_department_id",
            "work_category_id",
            "work_subcategory_id",
            "classification_other_text",
        }
        & field_names
    )


def _hierarchy_scope_values(hierarchy) -> dict[str, int | None]:
    if not hierarchy:
        return {
            "queue_id": None,
            "department_id": None,
            "category_id": None,
            "subcategory_id": None,
        }
    return {
        "queue_id": hierarchy.queue.id,
        "department_id": hierarchy.department.id,
        "category_id": hierarchy.category.id if hierarchy.category else None,
        "subcategory_id": hierarchy.subcategory.id if hierarchy.subcategory else None,
    }


def _active_ticket_type(
    db: DbSession, ticket_type_id: int | None, *, required: bool = False
) -> ServiceDeskTicketType | None:
    if ticket_type_id is None:
        ticket_type = default_ticket_type(db)
        if required and not ticket_type:
            raise HTTPException(status_code=400, detail="Active ticket type is required.")
        return ticket_type
    ticket_type = db.get(ServiceDeskTicketType, ticket_type_id)
    if not ticket_type or not ticket_type.active:
        raise HTTPException(status_code=400, detail="Ticket type is inactive or does not exist.")
    return ticket_type


def _get_visible_task(
    db: DbSession, task_id: int, user: User, *, action: str
) -> Task:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    _require_task_scope(db, user, task, action=action)
    return task


def _require_task_scope(db: DbSession, user: User, task: Task, *, action: str) -> None:
    if not user_work_scope_allows(
        db,
        user_id=user.id,
        queue_id=task.work_queue_id,
        department_id=task.work_department_id,
        category_id=task.work_category_id,
        subcategory_id=task.work_subcategory_id,
        action=action,
        task=task,
    ):
        raise HTTPException(status_code=403, detail="Work scope does not allow this action.")


def _validate_category_assignment(
    db: DbSession,
    category_id: int | None,
    user_id: int | None,
    team_id: int | None,
    *,
    allow_empty: bool = False,
) -> None:
    if user_id and team_id:
        raise HTTPException(status_code=400, detail="Choose at most one executor user or team.")
    if not user_id and not team_id:
        if allow_empty:
            return
        return
    if not category_id:
        return
    if user_id and not category_user_is_eligible(db, category_id, user_id):
        raise HTTPException(status_code=400, detail="User is not eligible for this category.")
    if team_id and not category_team_is_eligible(db, category_id, team_id):
        raise HTTPException(status_code=400, detail="Team is not eligible for this category.")


def _initialize_legacy_task(
    db: DbSession,
    task: Task,
    *,
    actor_user_id: int,
    user_id: int | None,
    team_id: int | None,
) -> None:
    if user_id and not assignment_target_user_allowed(
        db, actor_user_id=actor_user_id, target_user_id=user_id
    ):
        raise HTTPException(
            status_code=400,
            detail="User is not eligible for the assigning profile.",
        )
    task.assigned_to_id = user_id
    task.team_id = team_id
    task.assignment_state = (
        "assigned_user" if user_id else "assigned_team" if team_id else "waiting_assignment"
    )
    task.assignment_mode = "manual"
    if user_id or team_id:
        task.assigned_by_id = actor_user_id
        task.assigned_at = datetime.now(timezone.utc)
        db.add(
            TaskAssignmentEvent(
                task_id=task.id,
                actor_user_id=actor_user_id,
                action="assigned",
                to_user_id=user_id,
                to_team_id=team_id,
                details_json={"source": "legacy_api"},
            )
        )


def _assign_task_compatibly(
    db: DbSession,
    task: Task,
    *,
    actor_user_id: int,
    user_id: int | None,
    team_id: int | None,
    require_claim: bool,
    reason: str,
) -> None:
    if user_id and not assignment_target_user_allowed(
        db, actor_user_id=actor_user_id, target_user_id=user_id
    ):
        raise HTTPException(
            status_code=400,
            detail="User is not eligible for the assigning profile.",
        )
    if task.work_category_id:
        try:
            assign_task_executor(
                db,
                task,
                actor_user_id=actor_user_id,
                user_id=user_id,
                team_id=team_id,
                require_claim=require_claim,
                reason=reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return
    if require_claim and not team_id:
        raise HTTPException(status_code=400, detail="A claimable assignment requires a team.")
    old_user_id, old_team_id = task.assigned_to_id, task.team_id
    task.assigned_to_id = user_id
    task.team_id = team_id
    task.assignment_mode = "team_claim" if require_claim else "manual"
    task.assignment_state = (
        "assigned_user"
        if user_id
        else "team_unclaimed"
        if team_id and require_claim
        else "assigned_team"
        if team_id
        else "waiting_assignment"
    )
    task.assigned_by_id = actor_user_id
    task.assigned_at = datetime.now(timezone.utc) if user_id or team_id else None
    task.claimed_by_id = None
    task.claimed_at = None
    db.add(
        TaskAssignmentEvent(
            task_id=task.id,
            actor_user_id=actor_user_id,
            action="reassigned" if old_user_id or old_team_id else "assigned",
            from_user_id=old_user_id,
            to_user_id=user_id,
            from_team_id=old_team_id,
            to_team_id=team_id,
            details_json={"reason": reason, "legacy_unclassified": True},
        )
    )
    record_task_history(
        db,
        task.id,
        actor_user_id,
        "assignment",
        f"user:{old_user_id or '-'};team:{old_team_id or '-'}",
        f"user:{user_id or '-'};team:{team_id or '-'};state:{task.assignment_state}",
    )


def validate_task_links(
    db: DbSession,
    team_id: int | None,
    assigned_to_id: int | None,
    delegated_to_team_id: int | None = None,
    delegated_to_user_id: int | None = None,
    waiting_for_team_id: int | None = None,
    waiting_for_user_id: int | None = None,
    *,
    require_active: bool = False,
) -> None:
    _validate_team(db, team_id, "Team", require_active=require_active)
    _validate_user(db, assigned_to_id, "Assigned user", require_active=require_active)
    _validate_team(db, delegated_to_team_id, "Delegated team", require_active=require_active)
    _validate_user(db, delegated_to_user_id, "Delegated user", require_active=require_active)
    _validate_team(db, waiting_for_team_id, "Waiting target team", require_active=require_active)
    _validate_user(db, waiting_for_user_id, "Waiting target user", require_active=require_active)


def _validate_team(
    db: DbSession, team_id: int | None, label: str, *, require_active: bool
) -> None:
    if not team_id:
        return
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=400, detail=f"{label} does not exist.")
    if require_active and not team.active:
        raise HTTPException(status_code=400, detail=f"{label} is inactive.")


def _validate_user(
    db: DbSession, user_id: int | None, label: str, *, require_active: bool
) -> None:
    if not user_id:
        return
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=400, detail=f"{label} does not exist.")
    if require_active and not user.active:
        raise HTTPException(status_code=400, detail=f"{label} is inactive.")


def validate_task_state(
    status_value: str | None,
    waiting_reason: str | None,
    waiting_reason_detail: str | None,
    delegated_to_user_id: int | None,
    delegated_to_team_id: int | None,
) -> None:
    if status_value == "delegated" and not delegated_to_user_id and not delegated_to_team_id:
        raise HTTPException(
            status_code=400,
            detail="Delegated execution requires a delegated user or team.",
        )
    if status_value == "waiting":
        if waiting_reason not in TASK_WAITING_REASONS:
            raise HTTPException(status_code=400, detail="Waiting status requires a reason.")
        if waiting_reason == "other" and not (waiting_reason_detail or "").strip():
            raise HTTPException(status_code=400, detail="Other waiting reason requires detail.")


def can_supervise_task(db: DbSession, user: User, task: Task) -> bool:
    if task.assigned_to_id and task.assigned_to_id == user.id:
        return True
    if task.supervisor_user_id and task.supervisor_user_id == user.id:
        return True
    if task.team_id and db.scalar(
        select(TeamMember.id).where(
            TeamMember.team_id == task.team_id,
            TeamMember.user_id == user.id,
        )
    ):
        return True
    permissions = get_user_permission_codes(db, user)
    return bool(
        {
            "service_desk.assign",
            "service_desk.complete",
            "admin.manage",
            "users.manage",
            "settings.manage",
        }
        & permissions
    )


def record_task_history(
    db: DbSession,
    task_id: int,
    user_id: int | None,
    field_name: str,
    old_value,
    new_value,
) -> None:
    if old_value == new_value:
        return
    db.add(
        TaskHistory(
            task_id=task_id,
            user_id=user_id,
            field_name=field_name,
            old_value="" if old_value is None else str(old_value),
            new_value="" if new_value is None else str(new_value),
        )
    )
