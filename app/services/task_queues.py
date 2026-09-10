from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.admin import User
from app.services.authorization import (
    get_user_direct_permission_codes,
    get_user_permission_codes,
)

TASK_QUEUE_ALIASES = {
    "operational": "tasks_support",
    "workshop": "tasks_support",
    "management": "tasks_support",
    "audit": "administration",
    "administration": "administration",
}
TASK_QUEUE_TASK_TYPES = {
    "tasks_support": {
        "operational_task", "task", "request_info", "request",
        "operational_incident", "incident", "technical_incident",
        "entity_incident", "workshop_task", "management_task",
    },
    "administration": {"audit_task", "workshop_audit", "administration_task"},
}


@dataclass(frozen=True)
class TaskQueueCapability:
    code: str
    label: str
    workspaces: frozenset[str]
    can_read: bool
    can_write: bool


def resolve_task_queue_capabilities(
    db: Session, user: User | None
) -> tuple[TaskQueueCapability, ...]:
    """Resolve all queue surfaces from one server-side capability contract.

    Administration requires a persisted direct grant. Audit compatibility
    aliases may authorize audit work but never expose this queue.
    """
    if not user or not user.active:
        return ()
    effective = get_user_permission_codes(db, user)
    direct = get_user_direct_permission_codes(db, user)
    support_read = bool(effective & {
        "tasks.read", "tasks.write", "tasks.operational.read", "tasks.operational.write",
        "tasks.workshop.read", "tasks.workshop.write", "tasks.management.read",
        "tasks.management.create", "tasks.management.update",
        "tasks.management.close", "admin.manage",
    })
    support_write = bool(effective & {
        "tasks.write", "tasks.operational.write", "tasks.workshop.write",
        "tasks.management.create", "tasks.management.update",
        "tasks.management.close", "admin.manage",
    })
    administration_read = bool(
        direct & {"tasks.administration.read", "tasks.administration.write"}
    )
    administration_write = "tasks.administration.write" in direct
    result = []
    if support_read:
        result.append(TaskQueueCapability(
            "tasks_support", "Tarefas e Suporte",
            frozenset({"operational", "workshop", "management"}), True, support_write,
        ))
    if administration_read:
        result.append(TaskQueueCapability(
            "administration", "Administração",
            frozenset({"audit", "administration"}), True, administration_write,
        ))
    return tuple(result)


def canonical_task_queue(value: str | None) -> str:
    clean = (value or "tasks_support").strip().lower()
    return TASK_QUEUE_ALIASES.get(clean, clean)


def task_queue_for_task_type(task_type: str | None) -> str | None:
    clean = (task_type or "task").strip().lower()
    for queue_code, task_types in TASK_QUEUE_TASK_TYPES.items():
        if clean in task_types:
            return queue_code
    return None


def authorized_task_queue(
    db: Session, user: User | None, requested: str | None
) -> tuple[TaskQueueCapability | None, str]:
    canonical = canonical_task_queue(requested)
    if canonical not in TASK_QUEUE_TASK_TYPES:
        return None, "invalid"
    capabilities = {item.code: item for item in resolve_task_queue_capabilities(db, user)}
    capability = capabilities.get(canonical)
    return (capability, "") if capability else (None, "forbidden")
