from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tasks import Task, TaskCase, TaskHistory
from app.services.audit import record_audit

ARCHIVE_STATUSES = {"resolved", "closed", "cancelled", "no_action_needed"}


class TaskCaseError(ValueError):
    pass


def task_workspace(task: Task) -> str:
    return (
        "administration"
        if task.task_type in {"audit_task", "administration_task"}
        else "tasks_support"
    )


def calculated_case_state(tasks: list[Task], *, today: date | None = None) -> str:
    """Calculate state from child tasks; the case has no independent workflow."""
    current_day = today or date.today()
    if not tasks:
        return "empty"
    active = [
        task for task in tasks if task.status not in ARCHIVE_STATUSES and task.closed_at is None
    ]
    if not active:
        return "completed"
    if any(task.due_on and task.due_on < current_day for task in active):
        return "overdue"
    if any(task.status == "support_requested" for task in active):
        return "support_requested"
    if any(task.due_on and task.due_on <= current_day for task in active):
        return "at_risk"
    return "active"


def case_tasks(db: Session, case_id: int) -> list[Task]:
    return list(
        db.scalars(select(Task).where(Task.case_id == case_id).order_by(Task.created_at, Task.id))
    )


def _validate_title(title: str) -> str:
    clean = title.strip()
    if len(clean) < 2:
        raise TaskCaseError("case_title_required")
    return clean[:200]


def _attach(db: Session, *, case: TaskCase, task: Task, actor_user_id: int) -> None:
    if task.case_id is not None:
        raise TaskCaseError("task_already_in_case")
    if task_workspace(task) != case.workspace:
        raise TaskCaseError("cross_workspace_case")
    task.case_id = case.id
    db.add(
        TaskHistory(
            task_id=task.id,
            user_id=actor_user_id,
            field_name="case_id",
            old_value=None,
            new_value=str(case.id),
        )
    )


def create_case_with_first_task(
    db: Session,
    *,
    title: str,
    first_task: Task,
    actor_user_id: int,
) -> TaskCase:
    with db.begin_nested():
        db.add(first_task)
        db.flush()
        case = TaskCase(
            title=_validate_title(title),
            workspace=task_workspace(first_task),
            work_queue_id=first_task.work_queue_id,
            created_by_id=actor_user_id,
        )
        db.add(case)
        db.flush()
        _attach(db, case=case, task=first_task, actor_user_id=actor_user_id)
        record_audit(
            db,
            action="task_case.created_with_first_task",
            entity_type="task_case",
            entity_id=case.id,
            user_id=actor_user_id,
            after_json={"task_ids": [first_task.id], "workspace": case.workspace},
        )
    return case


def add_task_to_case(
    db: Session,
    *,
    case: TaskCase,
    task: Task,
    actor_user_id: int,
) -> Task:
    with db.begin_nested():
        locked_case = db.scalar(
            select(TaskCase).where(TaskCase.id == case.id).with_for_update()
        )
        if not locked_case:
            raise TaskCaseError("case_not_found")
        locked_tasks = list(
            db.scalars(
                select(Task)
                .where(Task.case_id == locked_case.id)
                .order_by(Task.id)
                .with_for_update()
            )
        )
        if calculated_case_state(locked_tasks) in {"empty", "completed"}:
            raise TaskCaseError("case_not_active")
        db.add(task)
        db.flush()
        _attach(db, case=locked_case, task=task, actor_user_id=actor_user_id)
        record_audit(
            db,
            action="task_case.task_added",
            entity_type="task_case",
            entity_id=locked_case.id,
            user_id=actor_user_id,
            after_json={"task_id": task.id},
        )
    return task


def create_related_case(
    db: Session,
    *,
    title: str,
    original_task: Task,
    related_task: Task,
    actor_user_id: int,
) -> TaskCase:
    with db.begin_nested():
        locked_original = db.scalar(
            select(Task)
            .where(Task.id == original_task.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not locked_original or locked_original.case_id is not None:
            raise TaskCaseError("task_already_in_case")
        if task_workspace(locked_original) != task_workspace(related_task):
            raise TaskCaseError("cross_workspace_case")
        db.add(related_task)
        db.flush()
        case = TaskCase(
            title=_validate_title(title),
            workspace=task_workspace(locked_original),
            work_queue_id=locked_original.work_queue_id,
            created_by_id=actor_user_id,
        )
        db.add(case)
        db.flush()
        _attach(db, case=case, task=locked_original, actor_user_id=actor_user_id)
        _attach(db, case=case, task=related_task, actor_user_id=actor_user_id)
        record_audit(
            db,
            action="task_case.created_from_related_task",
            entity_type="task_case",
            entity_id=case.id,
            user_id=actor_user_id,
            after_json={"task_ids": [locked_original.id, related_task.id]},
        )
    return case
