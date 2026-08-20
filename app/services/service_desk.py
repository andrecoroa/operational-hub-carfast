from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.admin import Role, User, UserRole
from app.models.email import (
    EmailAuditEvent,
    EmailChannel,
    EmailExecutorEligibility,
    EmailInboxRule,
    EmailThread,
)
from app.models.organization import Team, TeamMember
from app.models.tasks import Task, TaskAssignmentEvent, TaskHistory, TaskSlaEvent
from app.models.work_hierarchy import (
    ServiceDeskCategoryExecutor,
    ServiceDeskCategoryPolicy,
    ServiceDeskCategorySupervisor,
    ServiceDeskTicketType,
)

SERVICE_DESK_TIMEZONE = "Europe/Lisbon"
ASSIGNMENT_MODES = {"auto_user", "auto_team", "team_claim", "manual"}
ASSIGNMENT_STATES = {
    "assigned_user",
    "assigned_team",
    "team_unclaimed",
    "waiting_assignment",
}
SLA_STATES = {"within", "warning", "overdue", "completed", "paused", "not_configured"}
ROLE_ASSIGNMENT_RANK = {
    "admin": 50,
    "functional_admin": 40,
    "manager": 30,
    "auditor": 25,
    "operator": 20,
    "viewer": 10,
}


@dataclass(frozen=True)
class SlaSnapshot:
    first_response: str
    resolution: str
    overall: str


@dataclass(frozen=True)
class EmailPolicy:
    assignment_mode: str
    executor_user_id: int | None
    executor_team_id: int | None
    supervisor_user_id: int | None
    first_response_minutes: int | None
    resolution_minutes: int | None
    warning_minutes: int
    pause_on_waiting: bool


def aware_utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(UTC)
    if current.tzinfo is None:
        return current.replace(tzinfo=UTC)
    return current.astimezone(UTC)


def local_datetime(value: datetime | None) -> datetime | None:
    return aware_utc(value).astimezone(ZoneInfo(SERVICE_DESK_TIMEZONE)) if value else None


def assignment_target_user_allowed(
    db: Session, *, actor_user_id: int | None, target_user_id: int | None
) -> bool:
    """Prevent selectors and writes from assigning a user with a superior profile."""
    if not target_user_id:
        return True
    target = db.get(User, target_user_id)
    if not target or not target.active:
        return False
    if not actor_user_id or actor_user_id == target_user_id:
        return True
    actor = db.get(User, actor_user_id)
    if not actor or not actor.active:
        return False
    actor_codes = db.scalars(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == actor_user_id, Role.active.is_(True))
    ).all()
    target_codes = db.scalars(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == target_user_id, Role.active.is_(True))
    ).all()
    actor_rank = max((ROLE_ASSIGNMENT_RANK.get(code, 0) for code in actor_codes), default=0)
    target_rank = max((ROLE_ASSIGNMENT_RANK.get(code, 0) for code in target_codes), default=0)
    return target_rank <= actor_rank


def duration_to_minutes(value: int | None, unit: str = "minutes") -> int | None:
    if value is None:
        return None
    if unit not in {"minutes", "days"}:
        raise ValueError("Duration unit must be 'minutes' or 'days'.")
    clean_value = max(int(value), 0)
    return clean_value * 1440 if unit == "days" else clean_value


def default_ticket_type(db: Session) -> ServiceDeskTicketType | None:
    return db.scalar(
        select(ServiceDeskTicketType)
        .where(ServiceDeskTicketType.code == "task", ServiceDeskTicketType.active.is_(True))
        .order_by(ServiceDeskTicketType.id)
    )


def category_policy(db: Session, category_id: int | None) -> ServiceDeskCategoryPolicy | None:
    if not category_id:
        return None
    return db.scalar(
        select(ServiceDeskCategoryPolicy).where(
            ServiceDeskCategoryPolicy.category_id == category_id,
            ServiceDeskCategoryPolicy.active.is_(True),
        )
    )


def category_supervisor_id(db: Session, category_id: int | None) -> int | None:
    if not category_id:
        return None
    return db.scalar(
        select(ServiceDeskCategorySupervisor.user_id)
        .join(User, User.id == ServiceDeskCategorySupervisor.user_id)
        .where(
            ServiceDeskCategorySupervisor.category_id == category_id,
            ServiceDeskCategorySupervisor.active.is_(True),
            User.active.is_(True),
        )
        .order_by(ServiceDeskCategorySupervisor.id)
    )


def eligible_category_teams(db: Session, category_id: int | None) -> list[Team]:
    if not category_id:
        return []
    return list(
        db.scalars(
            select(Team)
            .join(ServiceDeskCategoryExecutor, ServiceDeskCategoryExecutor.team_id == Team.id)
            .where(
                ServiceDeskCategoryExecutor.category_id == category_id,
                ServiceDeskCategoryExecutor.active.is_(True),
                Team.active.is_(True),
            )
            .distinct()
            .order_by(Team.name)
        )
    )


def eligible_category_users(db: Session, category_id: int | None) -> list[User]:
    if not category_id:
        return []
    direct_ids = select(ServiceDeskCategoryExecutor.user_id).where(
        ServiceDeskCategoryExecutor.category_id == category_id,
        ServiceDeskCategoryExecutor.active.is_(True),
        ServiceDeskCategoryExecutor.user_id.is_not(None),
    )
    team_ids = select(ServiceDeskCategoryExecutor.team_id).where(
        ServiceDeskCategoryExecutor.category_id == category_id,
        ServiceDeskCategoryExecutor.active.is_(True),
        ServiceDeskCategoryExecutor.team_id.is_not(None),
    )
    team_member_ids = (
        select(TeamMember.user_id)
        .join(Team, Team.id == TeamMember.team_id)
        .where(TeamMember.team_id.in_(team_ids), Team.active.is_(True))
    )
    return list(
        db.scalars(
            select(User)
            .where(
                User.active.is_(True),
                or_(User.id.in_(direct_ids), User.id.in_(team_member_ids)),
            )
            .distinct()
            .order_by(User.name)
        )
    )


def category_user_is_eligible(db: Session, category_id: int | None, user_id: int | None) -> bool:
    return bool(
        user_id
        and any(item.id == user_id for item in eligible_category_users(db, category_id))
    )


def category_team_is_eligible(db: Session, category_id: int | None, team_id: int | None) -> bool:
    return bool(
        team_id
        and any(item.id == team_id for item in eligible_category_teams(db, category_id))
    )


def _assignment_values(
    db: Session,
    *,
    category_id: int | None,
    mode: str,
    user_id: int | None,
    team_id: int | None,
) -> tuple[int | None, int | None, str]:
    clean_mode = mode if mode in ASSIGNMENT_MODES else "manual"
    if clean_mode == "auto_user" and category_user_is_eligible(db, category_id, user_id):
        return user_id, None, "assigned_user"
    if clean_mode == "auto_team" and category_team_is_eligible(db, category_id, team_id):
        return None, team_id, "assigned_team"
    if clean_mode == "team_claim" and category_team_is_eligible(db, category_id, team_id):
        return None, team_id, "team_unclaimed"
    return None, None, "waiting_assignment"


def initialize_task_service_desk(
    db: Session,
    task: Task,
    *,
    now: datetime | None = None,
    actor_user_id: int | None = None,
    requested_user_id: int | None = None,
    requested_team_id: int | None = None,
) -> Task:
    effective_now = aware_utc(now)
    policy = category_policy(db, task.work_category_id)
    fallback_ticket_type = default_ticket_type(db) if not task.ticket_type_id else None
    task.ticket_type_id = task.ticket_type_id or (
        fallback_ticket_type.id if fallback_ticket_type else None
    )
    task.supervisor_user_id = category_supervisor_id(db, task.work_category_id)
    task.assignment_mode = policy.assignment_mode if policy else "manual"
    if requested_user_id and requested_team_id:
        raise ValueError("Choose at most one executor user or team.")
    if requested_user_id:
        requested_user = db.get(User, requested_user_id)
        if (
            not requested_user
            or not requested_user.active
            or not assignment_target_user_allowed(
                db,
                actor_user_id=actor_user_id,
                target_user_id=requested_user_id,
            )
            or (
                task.work_category_id
                and not category_user_is_eligible(
                    db, task.work_category_id, requested_user_id
                )
            )
        ):
            raise ValueError("User is not eligible for this category.")
    if requested_team_id:
        requested_team = db.get(Team, requested_team_id)
        if (
            not requested_team
            or not requested_team.active
            or (
                task.work_category_id
                and not category_team_is_eligible(
                    db, task.work_category_id, requested_team_id
                )
            )
        ):
            raise ValueError("Team is not eligible for this category.")
    policy_user_id = requested_user_id or (policy.default_executor_user_id if policy else None)
    policy_team_id = requested_team_id or (policy.default_executor_team_id if policy else None)
    if requested_user_id:
        assignment = (requested_user_id, None, "assigned_user")
    elif requested_team_id:
        assignment = (
            None,
            requested_team_id,
            "team_unclaimed" if task.assignment_mode == "team_claim" else "assigned_team",
        )
    else:
        assignment = _assignment_values(
            db,
            category_id=task.work_category_id,
            mode=task.assignment_mode,
            user_id=policy_user_id,
            team_id=policy_team_id,
        )
    task.assigned_to_id, task.team_id, task.assignment_state = assignment
    if task.assignment_state != "waiting_assignment":
        task.assigned_at = effective_now
        task.assigned_by_id = actor_user_id
    task.sla_first_response_minutes = (
        max(policy.first_response_minutes, 0)
        if policy and policy.first_response_minutes is not None
        else None
    )
    task.sla_resolution_minutes = (
        max(policy.resolution_minutes, 0)
        if policy and policy.resolution_minutes is not None
        else None
    )
    task.sla_warning_minutes = max(policy.warning_minutes if policy else 60, 0)
    task.sla_pause_on_waiting = policy.pause_on_waiting if policy else True
    task.sla_timezone = SERVICE_DESK_TIMEZONE
    task.first_response_due_at = (
        effective_now + timedelta(minutes=task.sla_first_response_minutes)
        if task.sla_first_response_minutes is not None
        else None
    )
    task.resolution_due_at = (
        effective_now + timedelta(minutes=task.sla_resolution_minutes)
        if task.sla_resolution_minutes is not None
        else None
    )
    if task.id:
        db.add(
            TaskAssignmentEvent(
                task_id=task.id,
                actor_user_id=actor_user_id,
                action=(
                    "assignment_pending"
                    if task.assignment_state == "waiting_assignment"
                    else "team_queued"
                    if task.assignment_state == "team_unclaimed"
                    else "assigned"
                ),
                to_user_id=task.assigned_to_id,
                to_team_id=task.team_id,
                details_json={
                    "mode": task.assignment_mode,
                    "source": "category_policy",
                },
                created_at=effective_now,
            )
        )
    return task


def assign_task_executor(
    db: Session,
    task: Task,
    *,
    actor_user_id: int,
    user_id: int | None = None,
    team_id: int | None = None,
    require_claim: bool = False,
    reason: str | None = None,
    now: datetime | None = None,
) -> None:
    effective_now = aware_utc(now)
    if user_id and team_id:
        raise ValueError("Choose at most one executor user or team.")
    if require_claim and not team_id:
        raise ValueError("A claimable assignment requires an eligible team.")
    selected_user = db.get(User, user_id) if user_id else None
    user_eligible = bool(
        selected_user
        and selected_user.active
        and (
            not task.work_category_id
            or category_user_is_eligible(db, task.work_category_id, user_id)
        )
    )
    if user_id and (
        not user_eligible
        or not assignment_target_user_allowed(
            db, actor_user_id=actor_user_id, target_user_id=user_id
        )
    ):
        raise ValueError("User is not eligible for this category or assigning profile.")
    selected_team = db.get(Team, team_id) if team_id else None
    team_eligible = bool(
        selected_team
        and selected_team.active
        and (
            not task.work_category_id
            or category_team_is_eligible(db, task.work_category_id, team_id)
        )
    )
    if team_id and not team_eligible:
        raise ValueError("Team is not eligible for this category.")
    old_user_id, old_team_id = task.assigned_to_id, task.team_id
    task.assigned_to_id = user_id
    task.team_id = team_id
    task.assignment_state = (
        "assigned_user"
        if user_id
        else "team_unclaimed"
        if team_id and require_claim
        else "assigned_team"
        if team_id
        else "waiting_assignment"
    )
    task.assignment_mode = (
        "team_claim"
        if team_id and require_claim
        else "auto_user"
        if user_id
        else "auto_team"
        if team_id
        else "manual"
    )
    task.assigned_by_id = actor_user_id
    task.assigned_at = effective_now if user_id or team_id else None
    task.claimed_by_id = None
    task.claimed_at = None
    db.add(
        TaskAssignmentEvent(
            task_id=task.id,
            actor_user_id=actor_user_id,
            action=(
                "unassigned"
                if not user_id and not team_id
                else "reassigned"
                if old_user_id or old_team_id
                else "assigned"
            ),
            from_user_id=old_user_id,
            to_user_id=user_id,
            from_team_id=old_team_id,
            to_team_id=team_id,
            details_json={"reason": reason, "require_claim": require_claim},
            created_at=effective_now,
        )
    )
    db.add(
        TaskHistory(
            task_id=task.id,
            user_id=actor_user_id,
            field_name="assignment",
            old_value=f"user:{old_user_id or '-'};team:{old_team_id or '-'}",
            new_value=f"user:{user_id or '-'};team:{team_id or '-'};state:{task.assignment_state}",
        )
    )


def claim_task(db: Session, task: Task, *, user_id: int, now: datetime | None = None) -> None:
    if task.assignment_state != "team_unclaimed" or not task.team_id:
        raise ValueError("Task is not available to claim.")
    assigned_team = db.get(Team, task.team_id)
    if (
        not assigned_team
        or not assigned_team.active
        or (
            task.work_category_id
            and not category_team_is_eligible(db, task.work_category_id, task.team_id)
        )
    ):
        raise ValueError("Assigned team is no longer eligible for this category.")
    membership = db.scalar(
        select(TeamMember.id)
        .join(Team, Team.id == TeamMember.team_id)
        .join(User, User.id == TeamMember.user_id)
        .where(
            TeamMember.team_id == task.team_id,
            TeamMember.user_id == user_id,
            Team.active.is_(True),
            User.active.is_(True),
        )
    )
    if not membership or (
        task.work_category_id
        and not category_user_is_eligible(db, task.work_category_id, user_id)
    ):
        raise ValueError("User is not an eligible member of the assigned team.")
    effective_now = aware_utc(now)
    task.assigned_to_id = user_id
    task.assignment_state = "assigned_user"
    task.assigned_by_id = user_id
    task.assigned_at = effective_now
    task.claimed_by_id = user_id
    task.claimed_at = effective_now
    db.add(
        TaskAssignmentEvent(
            task_id=task.id,
            actor_user_id=user_id,
            action="claimed",
            to_user_id=user_id,
            from_team_id=task.team_id,
            to_team_id=task.team_id,
            created_at=effective_now,
        )
    )
    db.add(
        TaskHistory(
            task_id=task.id,
            user_id=user_id,
            field_name="assignment",
            old_value=f"team:{task.team_id};unclaimed",
            new_value=f"team:{task.team_id};user:{user_id};claimed",
        )
    )


def _deadline_state(
    *,
    deadline: datetime | None,
    completed_at: datetime | None,
    warning_minutes: int,
    paused_at: datetime | None,
    now: datetime,
) -> str:
    if completed_at:
        return "completed"
    if not deadline:
        return "not_configured"
    if paused_at:
        return "paused"
    clean_deadline = aware_utc(deadline)
    if now > clean_deadline:
        return "overdue"
    if clean_deadline - now <= timedelta(minutes=max(warning_minutes, 0)):
        return "warning"
    return "within"


def sla_snapshot(item: Task | EmailThread, *, now: datetime | None = None) -> SlaSnapshot:
    effective_now = aware_utc(now)
    first = _deadline_state(
        deadline=item.first_response_due_at,
        completed_at=item.first_response_at,
        warning_minutes=item.sla_warning_minutes or 0,
        paused_at=item.sla_paused_at,
        now=effective_now,
    )
    resolution = _deadline_state(
        deadline=item.resolution_due_at,
        completed_at=item.resolved_at,
        warning_minutes=item.sla_warning_minutes or 0,
        paused_at=item.sla_paused_at,
        now=effective_now,
    )
    rank = {
        "overdue": 5,
        "warning": 4,
        "paused": 3,
        "within": 2,
        "completed": 1,
        "not_configured": 0,
    }
    overall = max((first, resolution), key=lambda value: rank[value])
    return SlaSnapshot(first_response=first, resolution=resolution, overall=overall)


def _shift_deadlines(item: Task | EmailThread, seconds: int) -> None:
    if item.first_response_due_at and not item.first_response_at:
        item.first_response_due_at = aware_utc(item.first_response_due_at) + timedelta(
            seconds=seconds
        )
    if item.resolution_due_at and not item.resolved_at:
        item.resolution_due_at = aware_utc(item.resolution_due_at) + timedelta(seconds=seconds)


def pause_task_sla(
    db: Session,
    task: Task,
    *,
    actor_user_id: int | None,
    reason: str,
    now: datetime | None = None,
) -> None:
    if not task.sla_pause_on_waiting or task.sla_paused_at:
        return
    effective_now = aware_utc(now)
    task.sla_paused_at = effective_now
    db.add(
        TaskSlaEvent(
            task_id=task.id,
            actor_user_id=actor_user_id,
            action="paused",
            reason=reason,
            occurred_at=effective_now,
        )
    )


def resume_task_sla(
    db: Session,
    task: Task,
    *,
    actor_user_id: int | None,
    reason: str,
    now: datetime | None = None,
) -> None:
    if not task.sla_paused_at:
        return
    effective_now = aware_utc(now)
    elapsed = max(int((effective_now - aware_utc(task.sla_paused_at)).total_seconds()), 0)
    _shift_deadlines(task, elapsed)
    task.sla_total_paused_seconds += elapsed
    task.sla_paused_at = None
    db.add(
        TaskSlaEvent(
            task_id=task.id,
            actor_user_id=actor_user_id,
            action="resumed",
            reason=reason,
            occurred_at=effective_now,
            details_json={"paused_seconds": elapsed},
        )
    )


def mark_task_first_response(
    db: Session, task: Task, *, actor_user_id: int | None, now: datetime | None = None
) -> None:
    if task.first_response_at:
        return
    effective_now = aware_utc(now)
    task.first_response_at = effective_now
    db.add(
        TaskSlaEvent(
            task_id=task.id,
            actor_user_id=actor_user_id,
            action="first_response",
            occurred_at=effective_now,
        )
    )


def mark_task_resolved(
    db: Session, task: Task, *, actor_user_id: int | None, now: datetime | None = None
) -> None:
    effective_now = aware_utc(now)
    if task.sla_paused_at:
        resume_task_sla(
            db,
            task,
            actor_user_id=actor_user_id,
            reason="Ticket concluído",
            now=effective_now,
        )
    mark_task_first_response(db, task, actor_user_id=actor_user_id, now=effective_now)
    if not task.resolved_at:
        task.resolved_at = effective_now
        db.add(
            TaskSlaEvent(
                task_id=task.id,
                actor_user_id=actor_user_id,
                action="resolved",
                occurred_at=effective_now,
            )
        )
        db.add(
            TaskAssignmentEvent(
                task_id=task.id,
                actor_user_id=actor_user_id,
                action="completed",
                from_user_id=task.assigned_to_id,
                to_user_id=task.assigned_to_id,
                from_team_id=task.team_id,
                to_team_id=task.team_id,
                details_json={"resolved_at": effective_now.isoformat()},
                created_at=effective_now,
            )
        )


def resolve_email_policy(channel: EmailChannel, rule: EmailInboxRule | None = None) -> EmailPolicy:
    def chosen(name: str):
        value = getattr(rule, name, None) if rule else None
        return value if value is not None else getattr(channel, name)

    resolution_minutes = chosen("resolution_minutes")
    if resolution_minutes is None and chosen("default_due_days") is not None:
        resolution_minutes = chosen("default_due_days") * 1440
    return EmailPolicy(
        assignment_mode=chosen("assignment_mode") or "manual",
        executor_user_id=chosen("default_assignee_id"),
        executor_team_id=chosen("default_team_id"),
        supervisor_user_id=chosen("supervisor_user_id"),
        first_response_minutes=chosen("first_response_minutes"),
        resolution_minutes=resolution_minutes,
        warning_minutes=max(chosen("warning_minutes") or 60, 0),
        pause_on_waiting=chosen("pause_on_waiting") is not False,
    )


def email_eligible_teams(
    db: Session, channel_id: int, category_id: int | None = None
) -> list[Team]:
    category_filter = (
        EmailExecutorEligibility.category_id.is_(None)
        if category_id is None
        else or_(
            EmailExecutorEligibility.category_id == category_id,
            EmailExecutorEligibility.category_id.is_(None),
        )
    )
    return list(
        db.scalars(
            select(Team)
            .join(EmailExecutorEligibility, EmailExecutorEligibility.team_id == Team.id)
            .where(
                EmailExecutorEligibility.channel_id == channel_id,
                EmailExecutorEligibility.active.is_(True),
                category_filter,
                Team.active.is_(True),
            )
            .distinct()
            .order_by(Team.name)
        )
    )


def email_eligible_users(
    db: Session, channel_id: int, category_id: int | None = None
) -> list[User]:
    category_filter = (
        EmailExecutorEligibility.category_id.is_(None)
        if category_id is None
        else or_(
            EmailExecutorEligibility.category_id == category_id,
            EmailExecutorEligibility.category_id.is_(None),
        )
    )
    direct_ids = select(EmailExecutorEligibility.user_id).where(
        EmailExecutorEligibility.channel_id == channel_id,
        EmailExecutorEligibility.active.is_(True),
        category_filter,
        EmailExecutorEligibility.user_id.is_not(None),
    )
    team_ids = select(EmailExecutorEligibility.team_id).where(
        EmailExecutorEligibility.channel_id == channel_id,
        EmailExecutorEligibility.active.is_(True),
        category_filter,
        EmailExecutorEligibility.team_id.is_not(None),
    )
    member_ids = select(TeamMember.user_id).where(TeamMember.team_id.in_(team_ids))
    return list(
        db.scalars(
            select(User)
            .where(User.active.is_(True), or_(User.id.in_(direct_ids), User.id.in_(member_ids)))
            .distinct()
            .order_by(User.name)
        )
    )


def initialize_email_operations(
    db: Session,
    thread: EmailThread,
    *,
    channel: EmailChannel,
    rule: EmailInboxRule | None = None,
    now: datetime | None = None,
) -> EmailThread:
    effective_now = aware_utc(now)
    policy = resolve_email_policy(channel, rule)
    thread.supervisor_user_id = policy.supervisor_user_id
    thread.assignment_mode = (
        policy.assignment_mode if policy.assignment_mode in ASSIGNMENT_MODES else "manual"
    )
    eligible_user_ids = {
        item.id for item in email_eligible_users(db, channel.id, thread.work_category_id)
    }
    eligible_team_ids = {
        item.id for item in email_eligible_teams(db, channel.id, thread.work_category_id)
    }
    user_id = policy.executor_user_id if policy.executor_user_id in eligible_user_ids else None
    team_id = policy.executor_team_id if policy.executor_team_id in eligible_team_ids else None
    if thread.assignment_mode == "auto_user" and user_id:
        thread.assigned_to_id, thread.assignment_state = user_id, "assigned_user"
    elif thread.assignment_mode == "auto_team" and team_id:
        thread.executor_team_id, thread.assignment_state = team_id, "assigned_team"
    elif thread.assignment_mode == "team_claim" and team_id:
        thread.executor_team_id, thread.assignment_state = team_id, "team_unclaimed"
    else:
        thread.assigned_to_id = None
        thread.executor_team_id = None
        thread.assignment_state = "waiting_assignment"
    if thread.assignment_state != "waiting_assignment":
        thread.assigned_at = effective_now
    thread.sla_first_response_minutes = policy.first_response_minutes
    thread.sla_resolution_minutes = policy.resolution_minutes
    thread.sla_warning_minutes = policy.warning_minutes
    thread.sla_pause_on_waiting = policy.pause_on_waiting
    thread.sla_timezone = SERVICE_DESK_TIMEZONE
    thread.first_response_due_at = (
        effective_now + timedelta(minutes=policy.first_response_minutes)
        if policy.first_response_minutes is not None
        else None
    )
    thread.resolution_due_at = (
        effective_now + timedelta(minutes=policy.resolution_minutes)
        if policy.resolution_minutes is not None
        else None
    )
    thread.due_at = thread.resolution_due_at
    return thread


def claim_email_thread(
    db: Session, thread: EmailThread, *, user_id: int, now: datetime | None = None
) -> None:
    if thread.assignment_state != "team_unclaimed" or not thread.executor_team_id:
        raise ValueError("Conversation is not available to claim.")
    membership = db.scalar(
        select(TeamMember.id).where(
            TeamMember.team_id == thread.executor_team_id,
            TeamMember.user_id == user_id,
        )
    )
    eligible = {
        item.id
        for item in email_eligible_users(db, thread.channel_id, thread.work_category_id)
    }
    if not membership or user_id not in eligible:
        raise ValueError("User is not eligible for this email category.")
    thread.assigned_to_id = user_id
    thread.assignment_state = "assigned_user"
    thread.claimed_by_id = user_id
    thread.claimed_at = aware_utc(now)
    db.add(
        EmailAuditEvent(
            thread_id=thread.id,
            user_id=user_id,
            action="claimed",
            details_json={"team_id": thread.executor_team_id},
        )
    )


def mark_email_first_response(
    db: Session, thread: EmailThread, *, user_id: int, now: datetime | None = None
) -> None:
    if thread.first_response_at:
        return
    thread.first_response_at = aware_utc(now)
    db.add(
        EmailAuditEvent(
            thread_id=thread.id,
            user_id=user_id,
            action="first_response",
        )
    )


def mark_email_resolved(
    db: Session, thread: EmailThread, *, user_id: int, now: datetime | None = None
) -> None:
    effective_now = aware_utc(now)
    if thread.resolved_at:
        return
    if thread.sla_paused_at:
        transition_email_waiting(
            db,
            thread,
            waiting=False,
            user_id=user_id,
            reason="Conversa resolvida",
            now=effective_now,
        )
    mark_email_first_response(db, thread, user_id=user_id, now=effective_now)
    thread.resolved_at = effective_now
    db.add(
        EmailAuditEvent(
            thread_id=thread.id,
            user_id=user_id,
            action="sla_resolved",
        )
    )


def transition_email_waiting(
    db: Session,
    thread: EmailThread,
    *,
    waiting: bool,
    user_id: int | None,
    reason: str,
    now: datetime | None = None,
) -> None:
    effective_now = aware_utc(now)
    if waiting and thread.sla_pause_on_waiting and not thread.sla_paused_at:
        thread.sla_paused_at = effective_now
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                user_id=user_id,
                action="sla_paused",
                details_json={"reason": reason},
            )
        )
    elif not waiting and thread.sla_paused_at:
        elapsed = max(int((effective_now - aware_utc(thread.sla_paused_at)).total_seconds()), 0)
        _shift_deadlines(thread, elapsed)
        thread.sla_total_paused_seconds += elapsed
        thread.sla_paused_at = None
        thread.due_at = thread.resolution_due_at
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                user_id=user_id,
                action="sla_resumed",
                details_json={"reason": reason, "paused_seconds": elapsed},
            )
        )


def assignment_label(
    *,
    state: str,
    user_name: str | None,
    team_name: str | None,
) -> str:
    if state == "team_unclaimed" and team_name:
        return f"Por assumir na equipa {team_name}"
    if state == "assigned_team" and team_name:
        return f"Equipa {team_name}"
    if user_name:
        return user_name
    return "A aguardar atribuição"
