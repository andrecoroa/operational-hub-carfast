"""Keep an email conversation in sync with explicit task status changes."""

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.models.email import EmailAuditEvent, EmailThread
from app.models.tasks import Task


COMPLETED_TASK_STATUSES = frozenset(
    {"execution_done", "closed", "cancelled", "no_action_needed"}
)


def _reopen_email_threads_on_task_completion(db: Session, _flush_context, _instances) -> None:
    for task in list(db.dirty):
        if not isinstance(task, Task) or task.status not in COMPLETED_TASK_STATUSES:
            continue
        if not inspect(task).attrs.status.history.has_changes():
            continue
        threads = db.scalars(
            select(EmailThread).where(
                EmailThread.task_id == task.id,
                EmailThread.status == "task_created",
            )
        ).all()
        for thread in threads:
            if thread.status != "task_created":
                continue
            thread.status = "triage"
            db.add(
                EmailAuditEvent(
                    thread_id=thread.id,
                    user_id=None,
                    action="reopened_after_task_completion",
                    details_json={"task_id": task.id, "task_status": task.status},
                )
            )


def reconcile_completed_email_tasks(db: Session) -> int:
    """One-time catch-up for task completions predating the event listener."""
    rows = db.execute(
        select(EmailThread, Task)
        .join(Task, Task.id == EmailThread.task_id)
        .where(
            EmailThread.status == "task_created",
            Task.status.in_(COMPLETED_TASK_STATUSES),
        )
    ).all()
    for thread, task in rows:
        thread.status = "triage"
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                user_id=None,
                action="reopened_after_task_completion",
                details_json={"task_id": task.id, "task_status": task.status},
            )
        )
    return len(rows)


def register_email_task_events() -> None:
    if not event.contains(Session, "before_flush", _reopen_email_threads_on_task_completion):
        event.listen(Session, "before_flush", _reopen_email_threads_on_task_completion)
