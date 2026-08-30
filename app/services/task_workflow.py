from collections.abc import Iterable

TASK_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "planned": ("new", "cancelled"),
    "new": ("in_execution", "waiting", "resolved", "cancelled"),
    "in_execution": ("waiting", "resolved", "cancelled"),
    "waiting": ("in_execution", "resolved", "cancelled"),
    # Support is resolved through the transactional support lifecycle.  The
    # generic transition endpoint remains closed while a request is active.
    "support_requested": (),
    "delegated": ("in_execution", "waiting", "resolved", "cancelled"),
    "execution_done": ("ready_validation", "in_execution"),
    "ready_validation": ("resolved", "in_execution"),
    "resolved": ("closed", "in_execution"),
    "closed": (),
    "cancelled": (),
    "no_action_needed": (),
}


def task_allowed_status_transitions(task_or_status) -> tuple[str, ...]:
    status = task_or_status if isinstance(task_or_status, str) else task_or_status.status
    return TASK_STATUS_TRANSITIONS.get(status, ())


def task_support_return_statuses(previous_status: str | None) -> tuple[str, ...]:
    """Return the captured state first, followed by its legal explicit exits."""
    if not previous_status or previous_status == "support_requested":
        return ()
    return tuple(
        dict.fromkeys((previous_status, *task_allowed_status_transitions(previous_status)))
    )


def validate_task_support_return_status(
    previous_status: str | None,
    next_status: str | None,
    *,
    permitted_statuses: Iterable[str] | None = None,
) -> str:
    allowed = set(task_support_return_statuses(previous_status))
    if permitted_statuses is not None:
        allowed.intersection_update(permitted_statuses)
    if not next_status:
        raise ValueError("support_next_status_required")
    if next_status not in allowed:
        raise ValueError("support_next_status_invalid")
    return next_status
