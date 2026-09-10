from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.tasks import Task, TaskHelpRequest, TaskHistory, TaskSlaEvent
from app.services.service_desk import (
    mark_task_resolved,
    pause_task_sla,
    resume_task_sla,
)
from app.services.task_center import create_task_notifications
from app.services.task_workflow import (
    TaskWaitingContextError,
    validate_task_support_return_status,
    validate_task_waiting_context,
)

ACTIVE_SUPPORT_STATUSES = ("pending", "accepted")
SUPPORT_INELIGIBLE_TASK_STATUSES = (
    "closed",
    "cancelled",
    "no_action_needed",
    "support_requested",
)


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
    if task.status in SUPPORT_INELIGIBLE_TASK_STATUSES or task.closed_at is not None:
        raise TaskSupportError("support_task_ineligible")
    clean_reason = reason.strip()
    if not clean_reason:
        raise TaskSupportError("support_reason_required")
    if bool(requested_user_id) == bool(requested_team_id):
        raise TaskSupportError("support_single_target_required")
    # One active support request per task keeps the task-level
    # ``support_requested`` state unambiguous. A different recipient is not a
    # reason to create a second concurrent lifecycle.
    duplicate = db.scalar(
        select(TaskHelpRequest.id).where(
            TaskHelpRequest.task_id == task.id,
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
    permitted_next_statuses: tuple[str, ...] | None = None,
    detail: str | None = None,
) -> None:
    now = datetime.now(UTC)
    if item.status not in ACTIVE_SUPPORT_STATUSES:
        raise TaskSupportError("support_not_active")
    if task.status != "support_requested":
        raise TaskSupportError("support_task_state_mismatch")
    if action == "accept":
        if item.status != "pending":
            raise TaskSupportError("support_already_accepted")
        item.status = "accepted"
        item.accepted_at = now
        event_type = "support_accepted"
        title = f"Suporte aceite: {task.title}"
    elif action in {"complete", "cancel"}:
        try:
            next_status = validate_task_support_return_status(
                item.previous_task_status,
                next_status,
                permitted_statuses=permitted_next_statuses,
            )
        except ValueError as exc:
            raise TaskSupportError(str(exc)) from exc
        old_status = task.status
        try:
            waiting_reason, waiting_detail, waiting_until = validate_task_waiting_context(
                next_status, task.waiting_reason, task.waiting_reason_detail,
                task.waiting_until, now=now,
            )
        except TaskWaitingContextError as exc:
            raise TaskSupportError(str(exc)) from exc
        task.status = next_status
        if next_status != "waiting":
            for field_name, old_value in (
                ("waiting_reason", task.waiting_reason),
                ("waiting_reason_detail", task.waiting_reason_detail),
                ("waiting_until", task.waiting_until),
            ):
                if old_value is not None:
                    db.add(
                        TaskHistory(
                            task_id=task.id,
                            user_id=actor_user_id,
                            field_name=field_name,
                            old_value=str(old_value),
                            new_value=None,
                        )
                    )
        task.waiting_reason = waiting_reason
        task.waiting_reason_detail = waiting_detail
        task.waiting_until = waiting_until
        prior_operational_status = item.previous_task_status
        if next_status == "waiting" and prior_operational_status != "waiting":
            pause_task_sla(
                db,
                task,
                actor_user_id=actor_user_id,
                reason="Support completed into waiting",
                now=now,
            )
        elif next_status != "waiting" and prior_operational_status == "waiting":
            resume_task_sla(
                db,
                task,
                actor_user_id=actor_user_id,
                reason="Support completed and task resumed",
                now=now,
            )
        if next_status in {"closed", "cancelled", "no_action_needed"}:
            task.closed_at = task.closed_at or now
            mark_task_resolved(
                db, task, actor_user_id=actor_user_id, now=now
            )
        else:
            task.closed_at = None
            if next_status == "resolved":
                mark_task_resolved(
                    db, task, actor_user_id=actor_user_id, now=now
                )
            elif prior_operational_status == "resolved" and task.resolved_at:
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
                        actor_user_id=actor_user_id,
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
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=actor_user_id,
                field_name="status",
                old_value=old_status,
                new_value=next_status,
            )
        )
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
