from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.admin import Role, User, UserRole
from app.models.organization import Team, TeamMember
from app.models.tasks import (
    Task,
    TaskAssignmentEvent,
    TaskHelpRequest,
    TaskParticipant,
    TaskSlaEvent,
)
from app.models.work_hierarchy import (
    RoleWorkScope,
    ServiceDeskCategoryExecutor,
    ServiceDeskCategoryPolicy,
    ServiceDeskCategorySupervisor,
    ServiceDeskTicketType,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
)
from app.services.bootstrap import seed_email_channels, seed_service_desk
from app.services.service_desk import (
    assign_task_executor,
    category_user_is_eligible,
    claim_task,
    duration_to_minutes,
    eligible_category_users,
    initialize_task_service_desk,
    local_datetime,
    mark_task_resolved,
    pause_task_sla,
    resume_task_sla,
    sla_snapshot,
)
from app.services.work_classification import user_work_scope_allows, user_work_scope_filter


def _category(db_session) -> WorkCategory:
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == queue.id,
            WorkDepartment.code == "operations",
        )
    )
    category = WorkCategory(
        department_id=department.id,
        code="service_desk_test",
        name="Service Desk Test",
        active=True,
    )
    db_session.add(category)
    db_session.flush()
    return category


def test_service_desk_bootstrap_is_idempotent_and_keeps_legacy_tasks(db_session):
    legacy = Task(
        title="Tarefa antiga",
        task_type="operational_task",
        category="Classificação histórica",
        subcategory="Não converter",
        status="new",
        priority="normal",
    )
    db_session.add(legacy)
    db_session.commit()

    seed_service_desk(db_session)
    seed_service_desk(db_session)
    seed_email_channels(db_session)
    seed_email_channels(db_session)
    db_session.commit()

    codes = list(db_session.scalars(select(ServiceDeskTicketType.code)))
    assert sorted(codes) == [
        "approval",
        "communication",
        "incident",
        "internal_help",
        "request",
        "task",
    ]
    db_session.refresh(legacy)
    assert legacy.ticket_type_id is None
    assert legacy.category == "Classificação histórica"
    assert legacy.subcategory == "Não converter"
    assert legacy.classification_other_text is None


def test_category_policy_initializes_team_claim_sla_and_complete_audit(db_session):
    category = _category(db_session)
    team = db_session.scalar(select(Team).where(Team.code == "operations"))
    supervisor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    executor = User(
        name="Executor elegível",
        email="executor.service.desk@carfast.local",
        password_hash="not-used",
        active=True,
    )
    outsider = User(
        name="Sem elegibilidade",
        email="outsider.service.desk@carfast.local",
        password_hash="not-used",
        active=True,
    )
    db_session.add_all([executor, outsider])
    db_session.flush()
    db_session.add_all(
        [
            TeamMember(team_id=team.id, user_id=executor.id),
            ServiceDeskCategoryExecutor(category_id=category.id, team_id=team.id),
            ServiceDeskCategorySupervisor(category_id=category.id, user_id=supervisor.id),
            ServiceDeskCategoryPolicy(
                category_id=category.id,
                assignment_mode="team_claim",
                default_executor_team_id=team.id,
                first_response_minutes=30,
                resolution_minutes=240,
                warning_minutes=15,
                pause_on_waiting=True,
                timezone="Europe/Lisbon",
            ),
        ]
    )
    db_session.commit()

    start = datetime(2026, 8, 20, 8, 0, tzinfo=UTC)
    task = Task(
        title="Pedido operacional",
        task_type="operational_task",
        work_category_id=category.id,
        status="new",
        priority="normal",
        created_by_id=supervisor.id,
    )
    db_session.add(task)
    db_session.flush()
    initialize_task_service_desk(
        db_session, task, now=start, actor_user_id=supervisor.id
    )

    assert task.assignment_state == "team_unclaimed"
    assert task.team_id == team.id
    assert task.assigned_to_id is None
    assert task.supervisor_user_id == supervisor.id
    assert task.first_response_due_at == start + timedelta(minutes=30)
    assert task.resolution_due_at == start + timedelta(minutes=240)
    assert sla_snapshot(task, now=start + timedelta(minutes=16)).first_response == "warning"
    assert sla_snapshot(task, now=start + timedelta(minutes=31)).first_response == "overdue"

    with pytest.raises(ValueError):
        claim_task(db_session, task, user_id=outsider.id, now=start)
    claim_task(db_session, task, user_id=executor.id, now=start + timedelta(minutes=5))
    assert task.assigned_to_id == executor.id
    assert task.assignment_state == "assigned_user"
    assert task.assigned_by_id == executor.id
    assert task.assigned_at == start + timedelta(minutes=5)

    original_resolution = task.resolution_due_at
    pause_task_sla(
        db_session,
        task,
        actor_user_id=executor.id,
        reason="Aguardar informação",
        now=start + timedelta(minutes=10),
    )
    resume_task_sla(
        db_session,
        task,
        actor_user_id=executor.id,
        reason="Informação recebida",
        now=start + timedelta(minutes=40),
    )
    assert task.resolution_due_at == original_resolution + timedelta(minutes=30)
    assert task.sla_total_paused_seconds == 1800
    pause_task_sla(
        db_session,
        task,
        actor_user_id=executor.id,
        reason="Aguardar confirmação final",
        now=start + timedelta(minutes=50),
    )
    mark_task_resolved(
        db_session,
        task,
        actor_user_id=executor.id,
        now=start + timedelta(minutes=70),
    )
    mark_task_resolved(
        db_session,
        task,
        actor_user_id=executor.id,
        now=start + timedelta(minutes=80),
    )
    assert task.resolution_due_at == original_resolution + timedelta(minutes=50)
    assert task.sla_total_paused_seconds == 3000
    assert sla_snapshot(task, now=start + timedelta(minutes=80)).overall == "completed"
    db_session.flush()
    assert {item.action for item in db_session.scalars(select(TaskAssignmentEvent))} >= {
        "team_queued",
        "claimed",
        "completed",
    }
    sla_actions = [item.action for item in db_session.scalars(select(TaskSlaEvent))]
    assert set(sla_actions) >= {
        "paused",
        "resumed",
        "first_response",
        "resolved",
    }
    assert sla_actions.count("resolved") == 1


def test_assignment_rejects_inactive_or_unauthorized_executors(db_session):
    category = _category(db_session)
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    inactive_team = Team(code="inactive_service_desk", name="Equipa inativa", active=False)
    inactive_user = User(
        name="Executor inativo",
        email="inactive.executor@carfast.local",
        password_hash="not-used",
        active=False,
    )
    active_member = User(
        name="Membro de equipa inativa",
        email="inactive.team.member@carfast.local",
        password_hash="not-used",
        active=True,
    )
    outsider = User(
        name="Não autorizado",
        email="not.eligible@carfast.local",
        password_hash="not-used",
        active=True,
    )
    db_session.add_all([inactive_team, inactive_user, active_member, outsider])
    db_session.flush()
    db_session.add_all(
        [
            TeamMember(team_id=inactive_team.id, user_id=active_member.id),
            ServiceDeskCategoryExecutor(category_id=category.id, team_id=inactive_team.id),
            ServiceDeskCategoryExecutor(category_id=category.id, user_id=inactive_user.id),
        ]
    )
    db_session.commit()

    assert eligible_category_users(db_session, category.id) == []
    assert category_user_is_eligible(db_session, category.id, inactive_user.id) is False
    assert category_user_is_eligible(db_session, category.id, active_member.id) is False

    task = Task(
        title="Atribuição protegida",
        task_type="operational_task",
        work_category_id=category.id,
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.flush()
    with pytest.raises(ValueError, match="not eligible"):
        initialize_task_service_desk(
            db_session,
            task,
            requested_user_id=outsider.id,
            actor_user_id=actor.id,
        )
    with pytest.raises(ValueError, match="at most one"):
        initialize_task_service_desk(
            db_session,
            task,
            requested_user_id=outsider.id,
            requested_team_id=inactive_team.id,
            actor_user_id=actor.id,
        )
    with pytest.raises(ValueError, match="requires an eligible team"):
        assign_task_executor(
            db_session,
            task,
            actor_user_id=actor.id,
            user_id=outsider.id,
            require_claim=True,
        )


def test_sla_uses_lisbon_timezone_and_only_pauses_when_configured(db_session):
    before_dst = local_datetime(datetime(2026, 3, 29, 0, 30, tzinfo=UTC))
    after_dst = local_datetime(datetime(2026, 3, 29, 1, 30, tzinfo=UTC))
    assert before_dst is not None and before_dst.utcoffset() == timedelta(0)
    assert after_dst is not None and after_dst.utcoffset() == timedelta(hours=1)
    assert duration_to_minutes(2, "days") == 2880
    assert duration_to_minutes(-5, "minutes") == 0
    with pytest.raises(ValueError, match="Duration unit"):
        duration_to_minutes(1, "hours")

    task = Task(
        title="SLA sem pausa",
        task_type="operational_task",
        status="new",
        priority="normal",
        sla_pause_on_waiting=False,
        sla_warning_minutes=10,
        first_response_due_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        resolution_due_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
    )
    db_session.add(task)
    db_session.flush()
    pause_task_sla(
        db_session,
        task,
        actor_user_id=None,
        reason="Não deve pausar",
        now=datetime(2026, 8, 20, 8, 0, tzinfo=UTC),
    )
    assert task.sla_paused_at is None
    assert sla_snapshot(task, now=datetime(2026, 8, 20, 8, 30, tzinfo=UTC)).overall == "within"


def test_direct_visibility_is_server_side_and_team_membership_counts(db_session):
    category = _category(db_session)
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.get(WorkDepartment, category.department_id)
    team = db_session.scalar(select(Team).where(Team.code == "operations"))
    role = db_session.scalar(select(Role).where(Role.code == "operator"))
    user = User(
        name="Operador com âmbito direto",
        email="direct.scope@carfast.local",
        password_hash="not-used",
        active=True,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add_all(
        [
            UserRole(user_id=user.id, role_id=role.id),
            TeamMember(team_id=team.id, user_id=user.id),
            RoleWorkScope(
                role_id=role.id,
                queue_id=queue.id,
                department_id=department.id,
                category_id=category.id,
                can_read=True,
                can_create=True,
                can_update=True,
                visibility_mode="direct_only",
            ),
        ]
    )
    related = Task(
        title="Relacionado pela equipa",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        team_id=team.id,
        status="new",
        priority="normal",
    )
    unrelated = Task(
        title="Sem relação direta",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        status="new",
        priority="normal",
    )
    legacy_related = Task(
        title="Legacy relacionado",
        task_type="operational_task",
        created_by_id=user.id,
        status="new",
        priority="normal",
    )
    legacy_unrelated = Task(
        title="Legacy sem relação",
        task_type="operational_task",
        status="new",
        priority="normal",
    )
    db_session.add_all([related, unrelated, legacy_related, legacy_unrelated])
    db_session.commit()

    scope_filter = user_work_scope_filter(
        db_session, user_id=user.id, task_model=Task, action="read"
    )
    visible_ids = set(db_session.scalars(select(Task.id).where(scope_filter)))
    assert related.id in visible_ids
    assert unrelated.id not in visible_ids
    assert legacy_related.id in visible_ids
    assert legacy_unrelated.id not in visible_ids
    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=queue.id,
        department_id=department.id,
        category_id=category.id,
        subcategory_id=None,
        action="update",
        task=related,
    ) is True
    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=queue.id,
        department_id=department.id,
        category_id=category.id,
        subcategory_id=None,
        action="update",
        task=unrelated,
    ) is False
    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=queue.id,
        department_id=department.id,
        category_id=category.id,
        subcategory_id=None,
        action="update",
    ) is False
    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=queue.id,
        department_id=department.id,
        category_id=category.id,
        subcategory_id=None,
        action="create",
    ) is True
    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=None,
        department_id=None,
        category_id=None,
        subcategory_id=None,
        action="update",
        task=legacy_related,
    ) is True
    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=None,
        department_id=None,
        category_id=None,
        subcategory_id=None,
        action="update",
        task=legacy_unrelated,
    ) is False


def test_consult_scope_is_read_only_and_denied_scope_cannot_read_legacy(db_session):
    category = _category(db_session)
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.get(WorkDepartment, category.department_id)
    consult_role = Role(code="service_desk_consult", name="Consulta Service Desk")
    denied_role = Role(code="service_desk_denied", name="Sem consulta Service Desk")
    consult_user = User(
        name="Consulta",
        email="consult.scope@carfast.local",
        password_hash="not-used",
        active=True,
    )
    denied_user = User(
        name="Sem consulta",
        email="denied.scope@carfast.local",
        password_hash="not-used",
        active=True,
    )
    db_session.add_all([consult_role, denied_role, consult_user, denied_user])
    db_session.flush()
    db_session.add_all(
        [
            UserRole(user_id=consult_user.id, role_id=consult_role.id),
            UserRole(user_id=denied_user.id, role_id=denied_role.id),
            RoleWorkScope(
                role_id=consult_role.id,
                queue_id=queue.id,
                department_id=department.id,
                category_id=category.id,
                can_read=True,
                can_update=True,
                can_manage=True,
                visibility_mode="consult",
            ),
            RoleWorkScope(
                role_id=denied_role.id,
                queue_id=queue.id,
                department_id=department.id,
                category_id=category.id,
                can_read=False,
                can_update=True,
                can_close=True,
                visibility_mode="direct_only",
            ),
        ]
    )
    scoped = Task(
        title="Consulta no âmbito",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        status="new",
        priority="normal",
    )
    legacy_related = Task(
        title="Legacy sem permissão",
        task_type="operational_task",
        created_by_id=denied_user.id,
        status="new",
        priority="normal",
    )
    db_session.add_all([scoped, legacy_related])
    db_session.flush()
    db_session.add_all(
        [
            TaskParticipant(
                task_id=scoped.id,
                user_id=consult_user.id,
                role="follower",
            ),
            TaskHelpRequest(
                task_id=scoped.id,
                requested_user_id=consult_user.id,
                status="pending",
            ),
        ]
    )
    db_session.commit()

    assert user_work_scope_allows(
        db_session,
        user_id=consult_user.id,
        queue_id=queue.id,
        department_id=department.id,
        category_id=category.id,
        subcategory_id=None,
        action="read",
        task=scoped,
    ) is True
    assert user_work_scope_allows(
        db_session,
        user_id=consult_user.id,
        queue_id=queue.id,
        department_id=department.id,
        category_id=category.id,
        subcategory_id=None,
        action="update",
        task=scoped,
    ) is False
    denied_filter = user_work_scope_filter(
        db_session,
        user_id=denied_user.id,
        task_model=Task,
        action="read",
    )
    assert list(db_session.scalars(select(Task.id).where(denied_filter))) == []
    assert user_work_scope_allows(
        db_session,
        user_id=denied_user.id,
        queue_id=None,
        department_id=None,
        category_id=None,
        subcategory_id=None,
        action="read",
        task=legacy_related,
    ) is False
    assert user_work_scope_allows(
        db_session,
        user_id=denied_user.id,
        queue_id=None,
        department_id=None,
        category_id=None,
        subcategory_id=None,
        action="close",
        task=legacy_related,
    ) is True
