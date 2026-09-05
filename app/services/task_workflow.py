from collections.abc import Iterable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

TASK_WAITING_REASONS = frozenset(
    {
        "customer",
        "partner_broker",
        "other_entity",
        "clarification",
        "validation",
        "decision",
        "other",
    }
)


class TaskWaitingContextError(ValueError):
    pass


def parse_lisbon_local_datetime(value: datetime) -> datetime:
    """Convert a datetime to UTC, rejecting ambiguous or missing Lisbon wall times."""
    if value.tzinfo is not None:
        return value.astimezone(UTC)
    local_tz = ZoneInfo("Europe/Lisbon")
    candidates = {
        candidate.astimezone(UTC)
        for fold in (0, 1)
        if (
            (candidate := value.replace(tzinfo=local_tz, fold=fold))
            .astimezone(UTC)
            .astimezone(local_tz)
            .replace(tzinfo=None)
            == value
        )
    }
    if len(candidates) != 1:
        raise ValueError("invalid_lisbon_local_time")
    return candidates.pop()


def parse_task_waiting_until(value: datetime | str | None, *, now: datetime) -> datetime:
    """Return an unambiguous future instant, interpreting naive values in Lisbon."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip())
        except (TypeError, ValueError):
            parsed = None
    else:
        parsed = value
    if parsed is None:
        raise TaskWaitingContextError("waiting_until_required")
    try:
        parsed = parse_lisbon_local_datetime(parsed)
    except ValueError:
        if parsed.tzinfo is None:
            raise TaskWaitingContextError("waiting_until_invalid_local_time")
        raise
    if parsed <= now.astimezone(UTC):
        raise TaskWaitingContextError("waiting_until_required")
    return parsed


def validate_task_waiting_context(
    status: str | None,
    waiting_reason: str | None,
    waiting_reason_detail: str | None,
    waiting_until: datetime | str | None,
    *,
    now: datetime,
) -> tuple[str | None, str | None, datetime | None]:
    """Validate the canonical bounded-wait contract, clearing it outside waiting."""
    if status != "waiting":
        return None, None, None
    reason = (waiting_reason or "").strip()
    detail = (waiting_reason_detail or "").strip()
    if reason not in TASK_WAITING_REASONS:
        raise TaskWaitingContextError("waiting_reason_required")
    if not detail:
        raise TaskWaitingContextError("waiting_reason_detail_required")
    return reason, detail, parse_task_waiting_until(waiting_until, now=now)

TASK_STATUS_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "planned": ("new", "cancelled"),
    "new": ("in_execution", "waiting", "resolved", "cancelled"),
    "in_execution": ("waiting", "resolved", "cancelled"),
    "waiting": ("in_execution", "resolved", "cancelled"),
    # Support is resolved through the transactional support lifecycle.  The
    # generic transition endpoint remains closed while a request is active.
    "support_requested": (),
    # Decisions are resolved only by the dedicated permission-scoped lifecycle.
    "waiting_decision": (),
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


def task_support_return_statuses_for_task(
    task, previous_status: str | None, *, now: datetime
) -> tuple[str, ...]:
    """Resolve support exits using the same bounded-wait contract as mutation."""
    statuses = list(task_support_return_statuses(previous_status))
    if "waiting" in statuses:
        try:
            validate_task_waiting_context(
                "waiting", task.waiting_reason, task.waiting_reason_detail,
                task.waiting_until, now=now,
            )
        except TaskWaitingContextError:
            statuses.remove("waiting")
    return tuple(statuses)


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
