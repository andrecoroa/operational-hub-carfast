from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.auth import CurrentUser, require_permission
from app.api.deps import DbSession
from app.models.admin import User
from app.models.tasks import Task, TaskComment, TaskHistory
from app.models.organization import Team
from app.schemas.tasks import TaskCommentCreate, TaskCommentRead, TaskCreate, TaskRead, TaskUpdate
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes

router = APIRouter(prefix="/tasks")
TaskReader = Annotated[object, Depends(require_permission("tasks.read"))]
TaskWriter = Annotated[object, Depends(require_permission("tasks.write"))]
TASK_ARCHIVE_STATUSES = {"closed", "cancelled", "no_action_needed"}
TASK_RESPONSIBLE_ONLY_STATUSES = {"in_execution", "closed", "cancelled", "no_action_needed"}
TASK_WAITING_REASONS = {
    "customer",
    "partner_broker",
    "other_entity",
    "clarification",
    "validation",
    "decision",
    "other",
}


@router.get("", response_model=list[TaskRead])
def list_tasks(
    db: DbSession,
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
    stmt = select(Task).order_by(Task.id.desc()).limit(limit).offset(offset)
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
    return db.scalars(stmt).all()


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreate,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    validate_task_links(
        db,
        payload.team_id,
        payload.assigned_to_id,
        payload.delegated_to_team_id,
        payload.delegated_to_user_id,
        payload.waiting_for_team_id,
        payload.waiting_for_user_id,
    )
    validate_task_state(payload.status, payload.waiting_reason, payload.waiting_reason_detail, payload.delegated_to_user_id, payload.delegated_to_team_id)
    task = Task(**payload.model_dump(), created_by_id=current_user.id)
    db.add(task)
    db.flush()
    record_task_history(db, task.id, current_user.id, "created", None, task.status)
    record_audit(
        db,
        action="task.created",
        entity_type="task",
        entity_id=task.id,
        after_json=payload.model_dump(),
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, db: DbSession, _: TaskReader):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: DbSession,
    current_user: CurrentUser,
    _: TaskWriter,
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    changes = payload.model_dump(exclude_unset=True)
    validate_task_links(
        db,
        changes.get("team_id"),
        changes.get("assigned_to_id"),
        changes.get("delegated_to_team_id"),
        changes.get("delegated_to_user_id"),
        changes.get("waiting_for_team_id"),
        changes.get("waiting_for_user_id"),
    )
    next_status = changes.get("status", task.status)
    next_waiting_reason = changes.get("waiting_reason", task.waiting_reason)
    next_waiting_reason_detail = changes.get("waiting_reason_detail", task.waiting_reason_detail)
    next_delegated_user_id = changes.get("delegated_to_user_id", task.delegated_to_user_id)
    next_delegated_team_id = changes.get("delegated_to_team_id", task.delegated_to_team_id)
    if next_status in TASK_RESPONSIBLE_ONLY_STATUSES and not can_supervise_task(db, current_user, task):
        raise HTTPException(status_code=403, detail="Only the responsible user or an authorized profile can set this status.")
    if (
        "delegated_to_user_id" in changes
        or "delegated_to_team_id" in changes
        or next_status == "delegated"
    ) and not can_supervise_task(db, current_user, task):
        raise HTTPException(status_code=403, detail="Only the responsible user or an authorized profile can delegate execution.")
    validate_task_state(
        next_status,
        next_waiting_reason,
        next_waiting_reason_detail,
        next_delegated_user_id,
        next_delegated_team_id,
    )

    before = {
        "status": task.status,
        "priority": task.priority,
        "team_id": task.team_id,
        "assigned_to_id": task.assigned_to_id,
    }
    for field, value in changes.items():
        old_value = getattr(task, field)
        setattr(task, field, value)
        record_task_history(db, task.id, current_user.id, field, old_value, value)

    if changes.get("status") in TASK_ARCHIVE_STATUSES and task.closed_at is None:
        task.closed_at = datetime.now(timezone.utc)

    record_audit(
        db,
        action="task.updated",
        entity_type="task",
        entity_id=task.id,
        before_json=before,
        after_json=changes,
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(task)
    return task


@router.get("/{task_id}/comments", response_model=list[TaskCommentRead])
def list_task_comments(task_id: int, db: DbSession, _: TaskReader):
    if not db.get(Task, task_id):
        raise HTTPException(status_code=404, detail="Task not found.")
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
    if not db.get(Task, task_id):
        raise HTTPException(status_code=404, detail="Task not found.")

    comment = TaskComment(task_id=task_id, user_id=current_user.id, comment=payload.comment)
    db.add(comment)
    record_audit(
        db,
        action="task.comment.created",
        entity_type="task",
        entity_id=task_id,
        user_id=current_user.id,
    )
    db.commit()
    db.refresh(comment)
    return comment


def validate_task_links(
    db: DbSession,
    team_id: int | None,
    assigned_to_id: int | None,
    delegated_to_team_id: int | None = None,
    delegated_to_user_id: int | None = None,
    waiting_for_team_id: int | None = None,
    waiting_for_user_id: int | None = None,
) -> None:
    if team_id and not db.get(Team, team_id):
        raise HTTPException(status_code=400, detail="Team does not exist.")
    if assigned_to_id and not db.get(User, assigned_to_id):
        raise HTTPException(status_code=400, detail="Assigned user does not exist.")
    if delegated_to_team_id and not db.get(Team, delegated_to_team_id):
        raise HTTPException(status_code=400, detail="Delegated team does not exist.")
    if delegated_to_user_id and not db.get(User, delegated_to_user_id):
        raise HTTPException(status_code=400, detail="Delegated user does not exist.")
    if waiting_for_team_id and not db.get(Team, waiting_for_team_id):
        raise HTTPException(status_code=400, detail="Waiting target team does not exist.")
    if waiting_for_user_id and not db.get(User, waiting_for_user_id):
        raise HTTPException(status_code=400, detail="Waiting target user does not exist.")


def validate_task_state(
    status_value: str | None,
    waiting_reason: str | None,
    waiting_reason_detail: str | None,
    delegated_to_user_id: int | None,
    delegated_to_team_id: int | None,
) -> None:
    if status_value == "delegated" and not delegated_to_user_id and not delegated_to_team_id:
        raise HTTPException(status_code=400, detail="Delegated execution requires a delegated user or team.")
    if status_value == "waiting":
        if waiting_reason not in TASK_WAITING_REASONS:
            raise HTTPException(status_code=400, detail="Waiting status requires a reason.")
        if waiting_reason == "other" and not (waiting_reason_detail or "").strip():
            raise HTTPException(status_code=400, detail="Other waiting reason requires detail.")


def can_supervise_task(db: DbSession, user: User, task: Task) -> bool:
    if task.assigned_to_id and task.assigned_to_id == user.id:
        return True
    permissions = get_user_permission_codes(db, user)
    return bool({"admin.manage", "users.manage", "settings.manage"} & permissions)


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
