from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.models import (
    Task,
    TaskHelpRequest,
    TaskComment,
    TaskHistory,
    TaskNotification,
    TaskParticipant,
    Team,
    TeamMember,
    User,
    WorkDepartment,
    WorkQueue,
)
from app.services.users import create_user
import app.web.router as task_router


def _login(client, email: str, password: str = "Secret123!") -> None:
    client.post("/logout", follow_redirects=False)
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    notice = client.post(
        "/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False
    )
    assert notice.status_code == 303


def _tasks_hierarchy(db_session):
    queue = db_session.scalar(
        select(WorkQueue).where(WorkQueue.code == "tasks_support")
    )
    department = db_session.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == queue.id,
            WorkDepartment.code == "operations",
        )
    )
    return queue, department


def test_deadline_and_unassigned_counters_match_filters(authenticated_client, db_session):
    today = date.today()
    db_session.add_all(
        [
            Task(
                title="Termina dentro da janela",
                task_type="operational_task",
                status="new",
                due_on=today + timedelta(days=2),
            ),
            Task(
                title="Prazo ultrapassado",
                task_type="operational_task",
                status="new",
                due_on=today - timedelta(days=1),
            ),
            Task(
                title="Prazo distante",
                task_type="operational_task",
                status="new",
                due_on=today + timedelta(days=10),
            ),
            Task(
                title="Fechada e ultrapassada",
                task_type="operational_task",
                status="closed",
                closed_at=datetime.now(UTC),
                due_on=today - timedelta(days=5),
            ),
        ]
    )
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open")
    assert page.status_code == 200
    assert '<span>Abertas</span><strong>3</strong>' in page.text
    assert '<span>Por atribuir</span><strong>3</strong>' in page.text
    assert '<span>A terminar</span><strong>1</strong>' in page.text
    assert '<span>Ultrapassado</span><strong>1</strong>' in page.text

    due_soon = authenticated_client.get(
        "/v2-clean/tasks?workspace=all&status=open&due=due_soon"
    )
    assert "Termina dentro da janela" in due_soon.text
    assert "Prazo ultrapassado" not in due_soon.text
    assert "Prazo distante" not in due_soon.text

    overdue = authenticated_client.get(
        "/v2-clean/tasks?workspace=all&status=open&due=overdue"
    )
    assert "Prazo ultrapassado" in overdue.text
    assert "Fechada e ultrapassada" not in overdue.text

    unassigned = authenticated_client.get(
        "/v2-clean/tasks?workspace=all&status=open&assignment=unassigned"
    )
    assert "Termina dentro da janela" in unassigned.text
    assert 'name="assignment"' in unassigned.text


def test_operator_visibility_and_counters_do_not_leak_unrelated_tasks(
    client, db_session
):
    operator = create_user(
        db_session,
        name="Operador restrito",
        email="operator.visibility@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    db_session.flush()
    direct = Task(
        title="Tarefa diretamente relacionada",
        task_type="operational_task",
        status="new",
        assigned_to_id=operator.id,
    )
    hidden = Task(
        title="Tarefa sem relação",
        task_type="operational_task",
        status="new",
    )
    db_session.add_all([direct, hidden])
    db_session.commit()

    _login(client, operator.email)
    page = client.get("/v2-clean/tasks?workspace=all&status=open")

    assert page.status_code == 200
    assert direct.title in page.text
    assert hidden.title not in page.text
    assert '<span>Abertas</span><strong>1</strong>' in page.text
    assert '<span>Por atribuir</span><strong>0</strong>' in page.text


def test_listable_direct_task_uses_same_resolver_for_clean_and_legacy_detail(
    client, db_session
):
    operator = create_user(
        db_session,
        name="Operador detalhe",
        email="operator.detail@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    task = Task(
        title="Detalhe com paridade",
        task_type="operational_task",
        status="new",
        assigned_to_id=operator.id,
    )
    db_session.add(task)
    db_session.commit()
    _login(client, operator.email)

    listed = client.get("/v2-clean/tasks?workspace=all&status=open&category=all")
    opened = client.get(
        f"/v2-clean/tasks/{task.id}/open",
        params={"return_url": "/v2-clean/tasks?workspace=all&status=open&category=all#task-1"},
        follow_redirects=False,
    )
    assert task.title in listed.text
    assert opened.status_code == 303
    assert opened.headers["location"].startswith(f"/v2-clean/tasks/{task.id}/detail?return_context=")
    detail = client.get(opened.headers["location"])
    assert detail.status_code == 200
    assert not detail.history, [(item.status_code, item.headers.get("location")) for item in detail.history]
    assert task.title in detail.text
    assert "Voltar ao Centro de Tarefas" in detail.text
    assert "/v2-clean/tasks?workspace=all&amp;status=open&amp;category=all#task-1" in detail.text


def test_three_creation_models_persist_distinct_canonical_task_types(
    authenticated_client, db_session
):
    expected = {
        "request": ("request", "Pedido"),
        "information": ("request_info", "Informação"),
        "task": ("operational_task", "Tarefa"),
    }
    for record_type, (task_type, origin_label) in expected.items():
        response = authenticated_client.post(
            "/v2-clean/tasks",
            data={
                "record_type": record_type,
                "workspace": "operational",
                "title": f"Modelo {record_type}",
                "category": "operations",
                "subcategory": "operations_tbd",
                "return_url": "/v2-clean/tasks?workspace=mine&status=open",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        created = db_session.scalar(select(Task).where(Task.title == f"Modelo {record_type}"))
        assert created is not None
        assert created.task_type == task_type
        assert task_router.task_origin_label(created) == origin_label

    forged = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "record_type": "request",
            "workspace": "workshop",
            "title": "Pedido forjado fora do workspace",
            "category": "workshop",
        },
        follow_redirects=False,
    )
    assert forged.status_code == 303
    assert forged.headers["location"] == "/v2-clean/tasks?error=forbidden"
    assert db_session.scalar(
        select(Task).where(Task.title == "Pedido forjado fora do workspace")
    ) is None


def test_legacy_team_fallback_is_workspace_scoped_and_forged_team_fails_closed(
    authenticated_client, db_session
):
    admin = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    operations = db_session.scalar(select(Team).where(Team.code == "operations"))
    workshop = db_session.scalar(select(Team).where(Team.code == "workshop"))
    visible = task_router.task_context_teams(db_session, admin, "operational")
    assert [team.code for team in visible] == ["operations"]
    assert task_router.task_team_allowed_for_workspace(
        db_session, admin, "operational", operations.id
    )
    assert not task_router.task_team_allowed_for_workspace(
        db_session, admin, "operational", workshop.id
    )


def test_clean_transition_and_note_are_authorized_audited_and_fail_closed(
    authenticated_client, db_session
):
    task = Task(
        title="Ações inline protegidas",
        task_type="operational_task",
        category="Documentação",
        status="new",
    )
    db_session.add(task)
    db_session.commit()
    return_url = "/v2-clean/tasks?workspace=all&status=open&category=all#task-1"

    forged = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/transition",
        data={"status": "closed", "return_url": return_url},
        follow_redirects=False,
    )
    assert forged.status_code == 303
    assert "invalid_transition=1" in forged.headers["location"]
    db_session.refresh(task)
    assert task.status == "new"

    changed = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/transition",
        data={"status": "in_execution", "return_url": return_url},
        follow_redirects=False,
    )
    noted = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/comments",
        data={"comment": "Nota operacional", "return_url": return_url},
        follow_redirects=False,
    )
    assert "transitioned=1" in changed.headers["location"]
    assert "commented=1" in noted.headers["location"]
    db_session.refresh(task)
    assert task.status == "in_execution"
    assert db_session.scalar(
        select(TaskHistory).where(
            TaskHistory.task_id == task.id,
            TaskHistory.field_name == "status",
            TaskHistory.old_value == "new",
            TaskHistory.new_value == "in_execution",
        )
    )
    assert db_session.scalar(
        select(TaskComment).where(
            TaskComment.task_id == task.id,
            TaskComment.comment == "Nota operacional",
        )
    )


def test_terminal_transition_revalidates_close_capability(
    authenticated_client, db_session, monkeypatch
):
    task = Task(
        title="Cancelamento protegido",
        task_type="operational_task",
        category="Documentação",
        status="new",
    )
    db_session.add(task)
    db_session.commit()
    original = task_router.user_can_access_task_workspace

    def capability(db, user, workspace, *, write=False, action=None):
        if action == "close":
            return False
        return original(db, user, workspace, write=write, action=action)

    monkeypatch.setattr(task_router, "user_can_access_task_workspace", capability)
    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/transition",
        data={"status": "cancelled", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )

    assert "forbidden=1" in response.headers["location"]
    db_session.refresh(task)
    assert task.status == "new"


def test_inline_transition_preserves_sla_pause_resume_and_terminal_resolution(
    authenticated_client, db_session
):
    task = Task(
        title="SLA da transição inline",
        task_type="operational_task",
        category="Documentação",
        status="in_execution",
        sla_resolution_minutes=120,
    )
    db_session.add(task)
    db_session.commit()
    endpoint = f"/v2-clean/tasks/{task.id}/transition"

    authenticated_client.post(
        endpoint,
        data={"status": "waiting", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )
    db_session.refresh(task)
    assert task.sla_paused_at is not None

    authenticated_client.post(
        endpoint,
        data={"status": "in_execution", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )
    db_session.refresh(task)
    assert task.sla_paused_at is None

    authenticated_client.post(
        endpoint,
        data={"status": "resolved", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )
    db_session.refresh(task)
    assert task.resolved_at is not None

    authenticated_client.post(
        endpoint,
        data={"status": "in_execution", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )
    db_session.refresh(task)
    assert task.resolved_at is None
    assert task.resolution_due_at is not None

    authenticated_client.post(
        endpoint,
        data={"status": "resolved", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )

    authenticated_client.post(
        endpoint,
        data={"status": "closed", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )
    db_session.refresh(task)
    assert task.closed_at is not None


def test_out_of_scope_user_cannot_open_or_forge_task_actions(client, db_session):
    outsider = create_user(
        db_session,
        name="Operador fora do âmbito",
        email="operator.outside@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    hidden = Task(title="Fora do âmbito", task_type="operational_task", status="new")
    db_session.add(hidden)
    db_session.commit()
    _login(client, outsider.email)

    opened = client.get(
        f"/v2-clean/tasks/{hidden.id}/open",
        params={"return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )
    transition = client.post(
        f"/v2-clean/tasks/{hidden.id}/transition",
        data={"status": "in_execution", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )
    note = client.post(
        f"/v2-clean/tasks/{hidden.id}/comments",
        data={"comment": "forjada", "return_url": "/v2-clean/tasks"},
        follow_redirects=False,
    )

    assert "forbidden=1" in opened.headers["location"]
    assert "forbidden=1" in transition.headers["location"]
    assert "forbidden=1" in note.headers["location"]
    db_session.refresh(hidden)
    assert hidden.status == "new"
    assert db_session.scalar(select(TaskComment).where(TaskComment.task_id == hidden.id)) is None


def test_assignment_candidates_and_server_validation_use_same_scope(
    authenticated_client, db_session
):
    queue, department = _tasks_hierarchy(db_session)
    unauthorized = User(
        name="Sem perfil elegível",
        email="no.assignment.profile@carfast.local",
        password_hash="not-used",
        active=True,
    )
    db_session.add(unauthorized)
    db_session.commit()

    candidates = authenticated_client.get(
        "/v2-clean/tasks/assignable-users",
        params={"work_queue_id": queue.id, "work_department_id": department.id},
    )
    assert candidates.status_code == 200
    assert unauthorized.id not in {item["id"] for item in candidates.json()["users"]}

    task = Task(
        title="Atribuição protegida",
        task_type="operational_task",
        status="new",
        work_queue_id=queue.id,
        work_department_id=department.id,
        classification_status="classified",
    )
    db_session.add(task)
    db_session.commit()
    rejected = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "title": task.title,
            "status": "new",
            "priority": "normal",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "assigned_to_id": str(unauthorized.id),
            "return_url": "/v2-clean/tasks",
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert "assignment_not_allowed" in rejected.headers["location"]
    db_session.refresh(task)
    assert task.assigned_to_id is None


def test_notifications_collaboration_and_team_support_round_trip(
    authenticated_client, client, db_session
):
    queue, department = _tasks_hierarchy(db_session)
    operator = create_user(
        db_session,
        name="Apoio Operacional",
        email="support.notifications@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    support_team = db_session.scalar(select(Team).where(Team.code == "support"))
    db_session.add(TeamMember(team_id=support_team.id, user_id=operator.id))
    db_session.commit()

    created = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "Tarefa com notificações",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "assigned_to_id": str(operator.id),
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    task = db_session.scalar(select(Task).where(Task.title == "Tarefa com notificações"))
    notification = db_session.scalar(
        select(TaskNotification).where(
            TaskNotification.task_id == task.id,
            TaskNotification.user_id == operator.id,
            TaskNotification.event_type == "task_created",
        )
    )
    assert notification is not None

    added = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/participants",
        data={"participant_user_id": operator.id, "role": "participant"},
        follow_redirects=False,
    )
    assert added.status_code == 303
    participant = db_session.scalar(
        select(TaskParticipant).where(
            TaskParticipant.task_id == task.id,
            TaskParticipant.user_id == operator.id,
            TaskParticipant.role == "participant",
        )
    )
    assert participant is not None and participant.status == "active"

    support = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_target": f"team:{support_team.id}",
            "message": "Validar com a equipa",
        },
        follow_redirects=False,
    )
    assert support.status_code == 303
    help_request = db_session.scalar(
        select(TaskHelpRequest).where(TaskHelpRequest.task_id == task.id)
    )
    assert help_request.requested_team_id == support_team.id

    _login(client, operator.email)
    page = client.get("/v2-clean/tasks?workspace=mine")
    assert page.status_code == 200
    assert "Notificações" in page.text
    assert "Tarefa com notificações" in page.text
    assert "Equipa · Suporte" in page.text

    opened = client.get(
        f"/v2-clean/tasks/notifications/{notification.id}/open",
        follow_redirects=False,
    )
    assert opened.status_code == 303
    db_session.expire_all()
    assert db_session.get(TaskNotification, notification.id).read_at is not None

    answered = client.post(
        f"/v2-clean/tasks/{task.id}/help/{help_request.id}",
        data={"response": "responded", "comment": "Apoio concluído"},
        follow_redirects=False,
    )
    assert answered.status_code == 303
    db_session.expire_all()
    assert db_session.get(TaskHelpRequest, help_request.id).status == "responded"


def test_task_table_has_compact_responsive_overflow_contract():
    css = Path("app/static/css/app.css").read_text(encoding="utf-8")
    template = Path("app/templates/clean_task_center.html").read_text(encoding="utf-8")

    assert ".clean-task-table-wrap" in css
    assert "overflow: auto" in css
    assert "min-width: 820px" in css
    assert 'data-label="Executor"' in template
    assert 'data-service-desk-executor="user"' in template
    assert template.count("const form = root.closest('form');") == 1
    assert "Só são apresentados utilizadores elegíveis" in template
