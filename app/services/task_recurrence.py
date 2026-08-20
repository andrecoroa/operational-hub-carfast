from __future__ import annotations

from datetime import UTC, datetime, timedelta
from threading import Lock
from time import monotonic
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.tasks import (
    Task,
    TaskHistory,
    TaskRecurrenceOccurrence,
    TaskRecurrenceTemplate,
)
from app.services.audit import record_audit
from app.services.service_desk import initialize_task_service_desk

RECURRENCE_TIMEZONE = "Europe/Lisbon"
RECURRENCE_FREQUENCIES = {"daily", "weekly", "monthly"}
RECURRENCE_TASK_TYPES = {
    "operational": "operational_task",
    "workshop": "workshop_task",
    "audit": "audit_task",
    "management": "management_task",
    "administration": "administration_task",
}
OPPORTUNISTIC_INTERVAL_SECONDS = 300
_opportunistic_lock = Lock()
_generation_lock = Lock()
_opportunistic_last_attempt = 0.0


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def local_datetime_to_utc(value: datetime, timezone: str = RECURRENCE_TIMEZONE) -> datetime:
    local_zone = ZoneInfo(timezone)
    if value.tzinfo is None:
        value = value.replace(tzinfo=local_zone)
    return value.astimezone(UTC)


def utc_datetime_to_local(value: datetime, timezone: str = RECURRENCE_TIMEZONE) -> datetime:
    return as_utc(value).astimezone(ZoneInfo(timezone))


def advance_schedule(
    scheduled_for: datetime,
    frequency: str,
    interval: int,
    timezone: str = RECURRENCE_TIMEZONE,
) -> datetime:
    if frequency not in RECURRENCE_FREQUENCIES:
        raise ValueError("Unsupported recurrence frequency")
    clean_interval = max(int(interval or 1), 1)
    local_value = utc_datetime_to_local(scheduled_for, timezone)
    if frequency == "daily":
        next_local = local_value + timedelta(days=clean_interval)
    elif frequency == "weekly":
        next_local = local_value + timedelta(weeks=clean_interval)
    else:
        target_month = local_value.month - 1 + clean_interval
        year = local_value.year + target_month // 12
        month = target_month % 12 + 1
        month_days = (
            29
            if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
            else 28
            if month == 2
            else 30
            if month in {4, 6, 9, 11}
            else 31
        )
        next_local = local_value.replace(
            year=year, month=month, day=min(local_value.day, month_days)
        )
    return next_local.astimezone(UTC)


def _reserve_occurrence(
    db: Session,
    template: TaskRecurrenceTemplate,
    scheduled_for: datetime,
) -> tuple[TaskRecurrenceOccurrence, bool]:
    existing = db.scalar(
        select(TaskRecurrenceOccurrence).where(
            TaskRecurrenceOccurrence.template_id == template.id,
            TaskRecurrenceOccurrence.scheduled_for == scheduled_for,
        )
    )
    if existing:
        return existing, False
    try:
        with db.begin_nested():
            occurrence = TaskRecurrenceOccurrence(
                template_id=template.id,
                scheduled_for=scheduled_for,
                status="reserved",
            )
            db.add(occurrence)
            db.flush()
        return occurrence, True
    except IntegrityError:
        existing = db.scalar(
            select(TaskRecurrenceOccurrence).where(
                TaskRecurrenceOccurrence.template_id == template.id,
                TaskRecurrenceOccurrence.scheduled_for == scheduled_for,
            )
        )
        if not existing:
            raise
        return existing, False


def _create_task_for_occurrence(
    db: Session,
    template: TaskRecurrenceTemplate,
    occurrence: TaskRecurrenceOccurrence,
) -> Task:
    local_schedule = utc_datetime_to_local(occurrence.scheduled_for, template.timezone)
    task = Task(
        title=template.task_title,
        description=template.task_description,
        task_type=template.task_type,
        source="recurrence",
        category=template.task_category,
        subcategory=template.task_subcategory,
        work_queue_id=template.work_queue_id,
        work_department_id=template.work_department_id,
        work_category_id=template.work_category_id,
        work_subcategory_id=template.work_subcategory_id,
        classification_status=(
            "classified" if template.work_queue_id and template.work_department_id else "legacy"
        ),
        legacy_classification=(
            " / ".join(
                value
                for value in (template.task_category, template.task_subcategory)
                if value
            )
            or None
        ),
        status="new",
        priority=template.task_priority,
        team_id=None,
        assigned_to_id=template.assigned_to_id,
        created_by_id=template.created_by_id,
        due_on=(local_schedule + timedelta(days=template.due_offset_days or 0)).date(),
        external_source_id=(
            f"recurrence:{template.id}:{as_utc(occurrence.scheduled_for).isoformat()}"
        ),
    )
    db.add(task)
    db.flush()
    try:
        initialize_task_service_desk(
            db,
            task,
            now=occurrence.scheduled_for,
            actor_user_id=template.created_by_id,
            requested_user_id=template.assigned_to_id,
        )
    except ValueError:
        # A recurrence must keep running after an executor is inactivated or
        # removed from the category. Re-evaluate the current category policy
        # and leave the occurrence waiting when no eligible default exists.
        initialize_task_service_desk(
            db,
            task,
            now=occurrence.scheduled_for,
            actor_user_id=template.created_by_id,
        )
    occurrence.task_id = task.id
    occurrence.status = "created"
    db.add(
        TaskHistory(
            task_id=task.id,
            user_id=template.created_by_id,
            field_name="created",
            old_value=None,
            new_value=f"Ocorrência automática do modelo recorrente #{template.id}",
        )
    )
    record_audit(
        db,
        action="task.recurrence.occurrence_created",
        entity_type="task_recurrence_template",
        entity_id=template.id,
        detail=f"Criada tarefa CF-TASK-{task.id:05d} a partir de {template.name}",
        user_id=template.created_by_id,
        after_json={
            "task_id": task.id,
            "scheduled_for": as_utc(occurrence.scheduled_for).isoformat(),
            "workspace": template.workspace,
        },
    )
    return task


def _generate_due_recurring_tasks(
    db: Session,
    *,
    now: datetime | None = None,
    max_occurrences: int = 25,
) -> list[Task]:
    effective_now = as_utc(now or datetime.now(UTC))
    query = (
        select(TaskRecurrenceTemplate)
        .where(
            TaskRecurrenceTemplate.enabled.is_(True),
            TaskRecurrenceTemplate.next_run_at <= effective_now,
        )
        .order_by(TaskRecurrenceTemplate.next_run_at, TaskRecurrenceTemplate.id)
        .limit(max_occurrences)
    )
    if db.bind is not None and db.bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    templates = list(db.scalars(query))
    created_tasks: list[Task] = []
    remaining = max(max_occurrences, 1)
    for template in templates:
        while template.enabled and as_utc(template.next_run_at) <= effective_now and remaining > 0:
            scheduled_for = as_utc(template.next_run_at)
            occurrence, reserved = _reserve_occurrence(db, template, scheduled_for)
            if reserved:
                created_tasks.append(_create_task_for_occurrence(db, template, occurrence))
            template.last_run_at = scheduled_for
            template.next_run_at = advance_schedule(
                scheduled_for,
                template.frequency,
                template.interval,
                template.timezone,
            )
            remaining -= 1
        if remaining <= 0:
            break
    return created_tasks


def generate_due_recurring_tasks(
    db: Session,
    *,
    now: datetime | None = None,
    max_occurrences: int = 25,
    commit: bool = False,
) -> list[Task]:
    # Serializes threads in one process; PostgreSQL row locks plus the unique
    # occurrence key provide the cross-process guarantee.
    with _generation_lock:
        created = _generate_due_recurring_tasks(
            db,
            now=now,
            max_occurrences=max_occurrences,
        )
        if commit:
            db.commit()
        return created


def opportunistic_generate_recurring_tasks(db: Session | None = None) -> int:
    global _opportunistic_last_attempt
    current_tick = monotonic()
    if current_tick - _opportunistic_last_attempt < OPPORTUNISTIC_INTERVAL_SECONDS:
        return 0
    if not _opportunistic_lock.acquire(blocking=False):
        return 0
    try:
        current_tick = monotonic()
        if current_tick - _opportunistic_last_attempt < OPPORTUNISTIC_INTERVAL_SECONDS:
            return 0
        _opportunistic_last_attempt = current_tick
        if db is not None:
            return len(generate_due_recurring_tasks(db, commit=True))
        with SessionLocal() as owned_db:
            created = generate_due_recurring_tasks(owned_db, commit=True)
            return len(created)
    finally:
        _opportunistic_lock.release()
