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

router = APIRouter(prefix="/tasks")
TaskReader = Annotated[object, Depends(require_permission("tasks.read"))]
TaskWriter = Annotated[object, Depends(require_permission("tasks.write"))]


@router.get("", response_model=list[TaskRead])
def list_tasks(
    db: DbSession,
    status_filter: str | None = None,
    task_type: str | None = None,
    team_id: int | None = None,
    assigned_to_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: TaskReader = None,
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
    _: TaskWriter = None,
):
    if not payload.team_id and not payload.assigned_to_id:
        raise HTTPException(status_code=400, detail="Task requires an assigned user or team.")
    validate_task_links(db, payload.team_id, payload.assigned_to_id)
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
def get_task(task_id: int, db: DbSession, _: TaskReader = None):
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
    _: TaskWriter = None,
):
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found.")

    changes = payload.model_dump(exclude_unset=True)
    validate_task_links(db, changes.get("team_id"), changes.get("assigned_to_id"))
    next_team_id = changes.get("team_id", task.team_id)
    next_assigned_to_id = changes.get("assigned_to_id", task.assigned_to_id)
    if not next_team_id and not next_assigned_to_id:
        raise HTTPException(status_code=400, detail="Task requires an assigned user or team.")

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

    if changes.get("status") in {"done", "cancelled"} and task.closed_at is None:
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
def list_task_comments(task_id: int, db: DbSession, _: TaskReader = None):
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
    _: TaskWriter = None,
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


def validate_task_links(db: DbSession, team_id: int | None, assigned_to_id: int | None) -> None:
    if team_id and not db.get(Team, team_id):
        raise HTTPException(status_code=400, detail="Team does not exist.")
    if assigned_to_id and not db.get(User, assigned_to_id):
        raise HTTPException(status_code=400, detail="Assigned user does not exist.")


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
