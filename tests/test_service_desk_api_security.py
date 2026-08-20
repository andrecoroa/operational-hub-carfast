from datetime import UTC, datetime

from sqlalchemy import select

from app.models import (
    Permission,
    Role,
    RolePermission,
    RoleWorkScope,
    ServiceDeskCategoryExecutor,
    ServiceDeskCategoryPolicy,
    ServiceDeskTicketType,
    Task,
    TaskAssignmentEvent,
    TaskSlaEvent,
    Team,
    TeamMember,
    User,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
)
from app.services.users import create_user


def _category(db_session, code: str = "api_service_desk"):
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == queue.id,
            WorkDepartment.code == "operations",
        )
    )
    category = WorkCategory(
        department_id=department.id,
        code=code,
        name="API Service Desk",
        active=True,
    )
    db_session.add(category)
    db_session.flush()
    return queue, department, category


def _operator_with_scope(
    db_session,
    *,
    category,
    email: str,
    can_assign: bool = False,
    can_assume: bool = False,
    can_respond: bool = False,
    can_complete: bool = False,
):
    role = Role(
        code=f"role_{category.code}_{email.split('@')[0]}",
        name=f"Role {email}",
        active=True,
    )
    db_session.add(role)
    db_session.flush()
    for code in ("tasks.read", "tasks.write"):
        permission = db_session.scalar(select(Permission).where(Permission.code == code))
        db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    user = create_user(
        db_session,
        name="Operador API",
        email=email,
        password="Secret123!",
        role_codes=[role.code],
        organizational_unit_codes=["carfast"],
    )
    department = db_session.get(WorkDepartment, category.department_id)
    db_session.add(
        RoleWorkScope(
            role_id=role.id,
            queue_id=department.queue_id,
            department_id=department.id,
            category_id=category.id,
            can_read=True,
            can_create=True,
            can_update=True,
            can_assign=can_assign,
            can_assume=can_assume,
            can_respond=can_respond,
            can_complete=can_complete,
            visibility_mode="direct_only",
        )
    )
    db_session.commit()
    return user


def _login(client, email: str):
    response = client.post(
        "/login",
        data={"email": email, "password": "Secret123!"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    notice = client.post(
        "/change-notice",
        data={"next_url": "/v2-clean"},
        follow_redirects=False,
    )
    assert notice.status_code == 303


def test_rest_list_get_and_comments_enforce_direct_visibility(client, db_session):
    queue, department, category = _category(db_session, "api_direct")
    user = _operator_with_scope(
        db_session,
        category=category,
        email="api.direct@carfast.local",
    )
    related = Task(
        title="REST relacionada",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        created_by_id=user.id,
        status="new",
        priority="normal",
    )
    unrelated = Task(
        title="REST fora da relação",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        status="new",
        priority="normal",
    )
    legacy_related = Task(
        title="REST legacy relacionada",
        task_type="operational_task",
        created_by_id=user.id,
        status="new",
        priority="normal",
    )
    legacy_unrelated = Task(
        title="REST legacy fora da relação",
        task_type="operational_task",
        status="new",
        priority="normal",
    )
    db_session.add_all([related, unrelated, legacy_related, legacy_unrelated])
    db_session.commit()
    _login(client, user.email)

    response = client.get("/tasks")
    assert response.status_code == 200
    returned_ids = {item["id"] for item in response.json()}
    assert related.id in returned_ids
    assert legacy_related.id in returned_ids
    assert unrelated.id not in returned_ids
    assert legacy_unrelated.id not in returned_ids
    assert client.get(f"/tasks/{related.id}").status_code == 200
    assert client.get(f"/tasks/{unrelated.id}").status_code == 403
    assert client.get(f"/tasks/{unrelated.id}/comments").status_code == 403


def test_rest_create_validates_ticket_hierarchy_eligibility_and_initializes_sla(
    authenticated_client,
    db_session,
):
    queue, department, category = _category(db_session, "api_create")
    policy = ServiceDeskCategoryPolicy(
        category_id=category.id,
        assignment_mode="manual",
        first_response_minutes=30,
        resolution_minutes=180,
        warning_minutes=15,
        pause_on_waiting=True,
        active=True,
    )
    eligible = create_user(
        db_session,
        name="Executor Elegível API",
        email="api.eligible@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    ineligible = create_user(
        db_session,
        name="Executor Não Elegível API",
        email="api.ineligible@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    db_session.add_all(
        [
            policy,
            ServiceDeskCategoryExecutor(
                category_id=category.id,
                user_id=eligible.id,
                active=True,
            ),
        ]
    )
    inactive_type = ServiceDeskTicketType(
        code="api_inactive",
        name="API inativo",
        active=False,
    )
    db_session.add(inactive_type)
    db_session.commit()

    payload = {
        "title": "Ticket REST completo",
        "task_type": "operational_task",
        "status": "new",
        "priority": "normal",
        "work_queue_id": queue.id,
        "work_department_id": department.id,
        "work_category_id": category.id,
        "assigned_to_id": eligible.id,
    }
    response = authenticated_client.post("/tasks", json=payload)
    assert response.status_code == 201, response.text
    created = db_session.get(Task, response.json()["id"])
    assert created.ticket_type_id is not None
    assert created.assignment_state == "assigned_user"
    assert created.assigned_to_id == eligible.id
    assert created.first_response_due_at is not None
    assert created.resolution_due_at is not None
    assert created.sla_first_response_minutes == 30
    assert created.sla_resolution_minutes == 180
    assert db_session.scalar(
        select(TaskAssignmentEvent).where(TaskAssignmentEvent.task_id == created.id)
    ) is not None

    denied = authenticated_client.post(
        "/tasks",
        json={**payload, "title": "Executor inválido", "assigned_to_id": ineligible.id},
    )
    assert denied.status_code == 400
    assert "eligible" in denied.json()["detail"].lower()

    inactive = authenticated_client.post(
        "/tasks",
        json={**payload, "title": "Tipo inativo", "ticket_type_id": inactive_type.id},
    )
    assert inactive.status_code == 400
    assert "inactive" in inactive.json()["detail"].lower()


def test_rest_actions_have_separate_scope_permissions_and_audit(client, db_session):
    queue, department, category = _category(db_session, "api_actions")
    actor = _operator_with_scope(
        db_session,
        category=category,
        email="api.actions@carfast.local",
    )
    other = create_user(
        db_session,
        name="Outro executor",
        email="api.other@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    db_session.add_all(
        [
            ServiceDeskCategoryExecutor(
                category_id=category.id,
                user_id=actor.id,
                active=True,
            ),
            ServiceDeskCategoryExecutor(
                category_id=category.id,
                user_id=other.id,
                active=True,
            ),
        ]
    )
    task = Task(
        title="Ações REST separadas",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        assigned_to_id=actor.id,
        assignment_state="assigned_user",
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()
    _login(client, actor.email)

    updated = client.patch(f"/tasks/{task.id}", json={"title": "Título permitido"})
    assert updated.status_code == 200
    assert client.post(
        f"/tasks/{task.id}/assignment", json={"user_id": other.id}
    ).status_code == 403
    assert client.post(
        f"/tasks/{task.id}/comments", json={"comment": "Resposta indevida"}
    ).status_code == 403
    assert client.post(f"/tasks/{task.id}/close", json={}).status_code == 403


def test_rest_claim_comment_and_close_record_operational_events(client, db_session):
    queue, department, category = _category(db_session, "api_claim")
    actor = _operator_with_scope(
        db_session,
        category=category,
        email="api.claim@carfast.local",
        can_assign=True,
        can_assume=True,
        can_respond=True,
        can_complete=True,
    )
    team = db_session.scalar(select(Team).where(Team.code == "operations"))
    db_session.add_all(
        [
            TeamMember(team_id=team.id, user_id=actor.id),
            ServiceDeskCategoryExecutor(
                category_id=category.id,
                team_id=team.id,
                active=True,
            ),
        ]
    )
    task = Task(
        title="Fila REST por assumir",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        team_id=team.id,
        assignment_mode="team_claim",
        assignment_state="team_unclaimed",
        sla_warning_minutes=10,
        first_response_due_at=datetime(2026, 8, 20, 10, 0, tzinfo=UTC),
        resolution_due_at=datetime(2026, 8, 20, 12, 0, tzinfo=UTC),
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()
    _login(client, actor.email)

    claimed = client.post(f"/tasks/{task.id}/claim")
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["assignment_state"] == "assigned_user"
    answered = client.post(
        f"/tasks/{task.id}/comments", json={"comment": "Primeira resposta REST"}
    )
    assert answered.status_code == 201
    closed = client.post(
        f"/tasks/{task.id}/close",
        json={"status": "closed", "reason": "Tratamento terminado"},
    )
    assert closed.status_code == 200, closed.text

    db_session.refresh(task)
    assert task.claimed_by_id == actor.id
    assert task.first_response_at is not None
    assert task.resolved_at is not None
    assert task.closed_at is not None
    assignment_actions = set(
        db_session.scalars(
            select(TaskAssignmentEvent.action).where(TaskAssignmentEvent.task_id == task.id)
        )
    )
    sla_actions = set(
        db_session.scalars(
            select(TaskSlaEvent.action).where(TaskSlaEvent.task_id == task.id)
        )
    )
    assert {"claimed", "completed"} <= assignment_actions
    assert {"first_response", "resolved"} <= sla_actions


def test_rest_legacy_create_and_update_keep_unclassified_compatibility(
    authenticated_client,
    db_session,
):
    team = db_session.scalar(select(Team).where(Team.code == "operations"))
    response = authenticated_client.post(
        "/tasks",
        json={
            "title": "API antiga preservada",
            "task_type": "operational_task",
            "category": "Classificação antiga",
            "team_id": team.id,
            "status": "new",
            "priority": "normal",
        },
    )
    assert response.status_code == 201, response.text
    task = db_session.get(Task, response.json()["id"])
    assert task.work_queue_id is None
    assert task.work_category_id is None
    assert task.category == "Classificação antiga"
    assert task.ticket_type_id is not None
    assert task.team_id == team.id

    updated = authenticated_client.patch(
        f"/tasks/{task.id}",
        json={"description": "Atualização por cliente antigo"},
    )
    assert updated.status_code == 200, updated.text
    db_session.refresh(task)
    assert task.work_queue_id is None
    assert task.category == "Classificação antiga"
    assert task.description == "Atualização por cliente antigo"
