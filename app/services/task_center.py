from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, false, or_, select

from app.models.admin import Role, User, UserRole
from app.models.organization import Team, TeamMember
from app.models.tasks import (
    Task,
    TaskHelpRequest,
    TaskNotification,
    TaskParticipant,
)
from app.models.work_hierarchy import ServiceDeskCategoryExecutor
from app.services.authorization import get_user_permission_codes
from app.services.work_classification import (
    user_work_scope_allows,
    user_work_scope_filter,
)

TASK_DUE_SOON_DAYS = 3
TASK_ELEVATED_ROLE_CODES = {
    "admin",
    "user_admin",
    "functional_admin",
    "manager",
    "auditor",
}
ACTIVE_SUPPORT_STATUSES = ("pending", "accepted")


@dataclass(frozen=True)
class TaskScopeView:
    code: str
    workspace: str
    mine_kind: str
    assignment: str


def resolve_task_scope_view(
    db, *, user_id: int | None, requested: str
) -> tuple[TaskScopeView | None, str | None]:
    """Resolve the public Task Center view without silently changing scope."""

    scopes = {
        "mine": TaskScopeView("mine", "mine", "assigned", ""),
        "claim": TaskScopeView("claim", "all", "assigned", "unassigned"),
        "team": TaskScopeView("team", "mine", "team", ""),
        "all": TaskScopeView("all", "all", "all", ""),
    }
    scope = scopes.get(requested)
    if scope is None:
        return None, "invalid"
    if requested == "team" and (not user_id or not user_team_ids(db, user_id)):
        return None, "forbidden"
    return scope, None


def task_role_codes(db, user_id: int) -> set[str]:
    return set(
        db.scalars(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id, Role.active.is_(True))
        )
    )


def user_is_restricted_task_operator(db, user_id: int) -> bool:
    roles = task_role_codes(db, user_id)
    return "operator" in roles and not roles.intersection(TASK_ELEVATED_ROLE_CODES)


def user_team_ids(db, user_id: int) -> set[int]:
    return set(
        db.scalars(
            select(TeamMember.team_id)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.user_id == user_id, Team.active.is_(True))
        )
    )


def task_direct_relation_filter(*, user_id: int, task_model=Task):
    participant_ids = select(TaskParticipant.task_id).where(
        TaskParticipant.user_id == user_id,
        TaskParticipant.status == "active",
    )
    support_ids = select(TaskHelpRequest.task_id).where(
        TaskHelpRequest.requested_user_id == user_id,
        TaskHelpRequest.status.in_(ACTIVE_SUPPORT_STATUSES),
    )
    return or_(
        task_model.assigned_to_id == user_id,
        task_model.created_by_id == user_id,
        task_model.delegated_to_user_id == user_id,
        task_model.waiting_for_user_id == user_id,
        task_model.id.in_(participant_ids),
        task_model.id.in_(support_ids),
    )


def task_team_relation_filter(db, *, user_id: int, task_model=Task):
    team_ids = user_team_ids(db, user_id)
    if not team_ids:
        return None
    support_team_ids = select(TaskHelpRequest.task_id).where(
        TaskHelpRequest.requested_team_id.in_(tuple(team_ids)),
        TaskHelpRequest.status.in_(ACTIVE_SUPPORT_STATUSES),
    )
    return or_(
        task_model.team_id.in_(tuple(team_ids)),
        task_model.delegated_to_team_id.in_(tuple(team_ids)),
        task_model.waiting_for_team_id.in_(tuple(team_ids)),
        task_model.id.in_(support_team_ids),
    )


def task_claimable_relation_filter(db, *, user_id: int, task_model=Task):
    """Return tasks the actor may assume through an active team and work scope.

    Team membership alone never makes a task part of ``Minhas``.  It only
    participates here when the task is unassigned and either targets one of
    the actor's teams or belongs to a category for which that team is an
    active eligible executor.  A configured ``assume`` scope is mandatory.
    """

    team_ids = user_team_ids(db, user_id)
    if not team_ids:
        return false()
    assume_scope = user_work_scope_filter(
        db, user_id=user_id, task_model=task_model, action="assume"
    )
    if assume_scope is None:
        return false()
    eligible_category_ids = select(ServiceDeskCategoryExecutor.category_id).where(
        ServiceDeskCategoryExecutor.team_id.in_(tuple(team_ids)),
        ServiceDeskCategoryExecutor.active.is_(True),
    )
    team_or_category = or_(
        task_model.team_id.in_(tuple(team_ids)),
        and_(
            task_model.team_id.is_(None),
            task_model.work_category_id.in_(eligible_category_ids),
        ),
    )
    return and_(task_model.assigned_to_id.is_(None), team_or_category, assume_scope)


def task_visibility_filter(db, *, user_id: int, task_model=Task):
    """Return the canonical row-level visibility filter for tasks.

    Managers keep their configured hierarchy scope. Operators must additionally have
    a direct relationship or belong to an involved team. A direct relationship is
    deliberately retained even if historical hierarchy data is incomplete.
    """

    hierarchy = user_work_scope_filter(
        db, user_id=user_id, task_model=task_model, action="read"
    )
    if not user_is_restricted_task_operator(db, user_id):
        return hierarchy
    direct = task_direct_relation_filter(user_id=user_id, task_model=task_model)
    team = task_team_relation_filter(db, user_id=user_id, task_model=task_model)
    claimable = task_claimable_relation_filter(
        db, user_id=user_id, task_model=task_model
    )
    if team is None:
        return or_(direct, claimable)
    if hierarchy is None:
        return or_(direct, team, claimable)
    return or_(direct, and_(team, hierarchy), claimable)


def user_can_view_task(db, *, user_id: int, task: Task) -> bool:
    visibility = task_visibility_filter(db, user_id=user_id, task_model=Task)
    statement = select(Task.id).where(Task.id == task.id)
    if visibility is not None:
        statement = statement.where(visibility)
    return db.scalar(statement) is not None


def task_due_condition(code: str, *, task_model=Task, today: date | None = None):
    current_day = today or date.today()
    if code == "due_soon":
        return and_(
            task_model.due_on >= current_day,
            task_model.due_on <= current_day + timedelta(days=TASK_DUE_SOON_DAYS),
        )
    if code == "overdue":
        return and_(task_model.due_on.is_not(None), task_model.due_on < current_day)
    return None


def user_team_assignment_allows(db, *, user_id: int, team_id: int | None) -> bool:
    if not team_id:
        return True
    configured_members = set(
        db.scalars(select(TeamMember.user_id).where(TeamMember.team_id == team_id))
    )
    if not configured_members:
        # Preserve legacy teams that have not yet been populated.
        return True
    if user_id in configured_members:
        return True
    if task_role_codes(db, user_id).intersection(TASK_ELEVATED_ROLE_CODES):
        return True
    user = db.get(User, user_id)
    return bool(user and "admin.manage" in get_user_permission_codes(db, user))


def hierarchy_assignment_allows(
    db,
    *,
    actor_user_id: int,
    target_user_id: int,
    queue_id: int,
    department_id: int | None,
    category_id: int | None,
    subcategory_id: int | None,
    team_id: int | None,
) -> bool:
    target = db.get(User, target_user_id)
    if not target or not target.active:
        return False
    if not user_work_scope_allows(
        db,
        user_id=actor_user_id,
        queue_id=queue_id,
        department_id=department_id,
        category_id=category_id,
        subcategory_id=subcategory_id,
        action="assign",
    ):
        return False
    if not user_work_scope_allows(
        db,
        user_id=target_user_id,
        queue_id=queue_id,
        department_id=department_id,
        category_id=category_id,
        subcategory_id=subcategory_id,
        action="read",
    ):
        return False
    return user_team_assignment_allows(db, user_id=target_user_id, team_id=team_id)


def _team_member_user_ids(db, team_ids: Iterable[int]) -> set[int]:
    clean_ids = {int(team_id) for team_id in team_ids if team_id}
    if not clean_ids:
        return set()
    return set(
        db.scalars(
            select(TeamMember.user_id).where(TeamMember.team_id.in_(tuple(clean_ids)))
        )
    )


def task_notification_recipient_ids(
    db,
    *,
    task: Task,
    extra_user_ids: Iterable[int] = (),
) -> set[int]:
    recipient_ids = {
        int(user_id)
        for user_id in (
            task.assigned_to_id,
            task.created_by_id,
            task.delegated_to_user_id,
            task.waiting_for_user_id,
            *extra_user_ids,
        )
        if user_id
    }
    recipient_ids.update(
        db.scalars(
            select(TaskParticipant.user_id).where(
                TaskParticipant.task_id == task.id,
                TaskParticipant.status == "active",
            )
        )
    )
    help_requests = list(
        db.scalars(
            select(TaskHelpRequest).where(
                TaskHelpRequest.task_id == task.id,
                TaskHelpRequest.status.in_(ACTIVE_SUPPORT_STATUSES),
            )
        )
    )
    recipient_ids.update(
        item.requested_user_id for item in help_requests if item.requested_user_id
    )
    recipient_ids.update(
        _team_member_user_ids(
            db,
            [
                task.team_id,
                task.delegated_to_team_id,
                task.waiting_for_team_id,
                *(item.requested_team_id for item in help_requests),
            ],
        )
    )
    if not recipient_ids:
        return set()
    return set(
        db.scalars(
            select(User.id).where(
                User.id.in_(tuple(recipient_ids)),
                User.active.is_(True),
            )
        )
    )


def create_task_notifications(
    db,
    *,
    task: Task,
    event_type: str,
    title: str,
    actor_user_id: int | None,
    detail: str | None = None,
    extra_user_ids: Iterable[int] = (),
) -> list[TaskNotification]:
    notifications: list[TaskNotification] = []
    for recipient_id in sorted(
        task_notification_recipient_ids(
            db, task=task, extra_user_ids=extra_user_ids
        )
    ):
        if actor_user_id and recipient_id == actor_user_id:
            continue
        notification = TaskNotification(
            task_id=task.id,
            user_id=recipient_id,
            actor_user_id=actor_user_id,
            event_type=event_type[:60],
            title=title[:200],
            detail=(detail or "").strip() or None,
        )
        db.add(notification)
        notifications.append(notification)
    return notifications
