from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, or_, select

from app.models.tasks import Task, TaskHelpRequest, TaskHistory
from app.services.task_center import create_task_notifications

ACTIVE_SUPPORT_STATUSES = ("pending", "accepted")


class TaskSupportError(ValueError):
    pass


def active_support_predicate():
    return TaskHelpRequest.status.in_(ACTIVE_SUPPORT_STATUSES)


def request_task_support(
    db,
    *,
    task: Task,
    actor_user_id: int,
    reason: str,
    requested_user_id: int | None = None,
    requested_team_id: int | None = None,
    due_at: datetime | None = None,
) -> TaskHelpRequest:
    clean_reason = reason.strip()
    if not clean_reason:
        raise TaskSupportError("support_reason_required")
    if bool(requested_user_id) == bool(requested_team_id):
        raise TaskSupportError("support_single_target_required")
    target_match = (
        TaskHelpRequest.requested_user_id == requested_user_id
        if requested_user_id
        else TaskHelpRequest.requested_team_id == requested_team_id
    )
    duplicate = db.scalar(
        select(TaskHelpRequest.id).where(
            TaskHelpRequest.task_id == task.id,
            target_match,
            active_support_predicate(),
        )
    )
    if duplicate:
        raise TaskSupportError("support_duplicate")

    previous_status = task.status
    item = TaskHelpRequest(
        task_id=task.id,
        requested_user_id=requested_user_id,
        requested_team_id=requested_team_id,
        requested_by_id=actor_user_id,
        message=clean_reason,
        due_at=due_at,
        previous_task_status=previous_status,
        status="pending",
    )
    db.add(item)
    task.status = "support_requested"
    db.add(
        TaskHistory(
            task_id=task.id,
            user_id=actor_user_id,
            field_name="status",
            old_value=previous_status,
            new_value="support_requested",
        )
    )
    return item


def resolve_task_support(
    db,
    *,
    task: Task,
    item: TaskHelpRequest,
    actor_user_id: int,
    action: str,
    next_status: str | None = None,
    detail: str | None = None,
) -> None:
    now = datetime.now(UTC)
    if item.status not in ACTIVE_SUPPORT_STATUSES:
        raise TaskSupportError("support_not_active")
    if action == "accept":
        if item.status != "pending":
            raise TaskSupportError("support_already_accepted")
        item.status = "accepted"
        item.accepted_at = now
        event_type = "support_accepted"
        title = f"Suporte aceite: {task.title}"
    elif action in {"complete", "cancel"}:
        if not next_status:
            raise TaskSupportError("support_next_status_required")
        # Restoration is explicit and bounded to the state captured transactionally.
        if next_status != item.previous_task_status:
            raise TaskSupportError("support_next_status_invalid")
        old_status = task.status
        task.status = next_status
        db.add(TaskHistory(task_id=task.id, user_id=actor_user_id, field_name="status", old_value=old_status, new_value=next_status))
        if action == "complete":
            item.status = "completed"
            item.completed_at = now
            item.responded_at = now
            event_type = "support_completed"
            title = f"Suporte concluído: {task.title}"
        else:
            item.status = "cancelled"
            item.cancelled_at = now
            event_type = "support_cancelled"
            title = f"Pedido de suporte cancelado: {task.title}"
    else:
        raise TaskSupportError("support_action_invalid")

    create_task_notifications(
        db,
        task=task,
        event_type=event_type,
        title=title,
        actor_user_id=actor_user_id,
        detail=(detail or "").strip() or None,
        extra_user_ids=(item.requested_by_id,) if item.requested_by_id else (),
    )
