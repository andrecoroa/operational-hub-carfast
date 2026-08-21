from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.models import (
    Base,
    Permission,
    Role,
    RolePermission,
    Task,
    TaskHelpRequest,
    TaskParticipant,
    TaskRecurrenceOccurrence,
    TaskRecurrenceTemplate,
    User,
    WorkDepartment,
    WorkQueue,
)
from app.services.task_recurrence import as_utc, generate_due_recurring_tasks
from app.services.users import create_user


def _login(client, email: str, password: str) -> None:
    client.cookies.clear()
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.post("/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False)


def _create_role_with_permissions(db, code: str, permission_codes: set[str]) -> Role:
    role = Role(code=code, name=code.replace("_", " ").title())
    db.add(role)
    db.flush()
    permissions = db.scalars(select(Permission).where(Permission.code.in_(permission_codes))).all()
    assert {item.code for item in permissions} == permission_codes
    db.add_all(
        [RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions]
    )
    return role


def test_mine_counters_and_all_relationship_badges_are_complete(
    authenticated_client,
    db_session,
):
    owner = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    task = Task(
        title="Tarefa com todas as relações",
        task_type="operational_task",
        source="v2_clean",
        status="new",
        priority="normal",
        assigned_to_id=owner.id,
        created_by_id=owner.id,
    )
    assigned_only = Task(
        title="Tarefa apenas atribuída",
        task_type="operational_task",
        source="v2_clean",
        status="new",
        priority="normal",
        assigned_to_id=owner.id,
    )
    db_session.add_all([task, assigned_only])
    db_session.flush()
    db_session.add_all(
        [
            TaskParticipant(task_id=task.id, user_id=owner.id, role="mentioned"),
            TaskParticipant(task_id=task.id, user_id=owner.id, role="follower"),
            TaskHelpRequest(
                task_id=task.id,
                requested_user_id=owner.id,
                requested_by_id=owner.id,
                status="pending",
            ),
        ]
    )
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=all")

    assert page.status_code == 200
    assert "<span>Todas as minhas</span><b>2</b>" in page.text
    assert "<span>Atribuídas</span><b>2</b>" in page.text
    assert "<span>Identificado</span><b>1</b>" in page.text
    assert "<span>A acompanhar</span><b>1</b>" in page.text
    assert "<span>Suporte solicitado</span><b>1</b>" in page.text
    assert "<span>Criadas por mim</span><b>1</b>" in page.text
    for badge in ("Responsável", "Identificado", "A acompanhar", "Suporte solicitado", "Criador"):
        assert f"<em>{badge}</em>" in page.text


def test_management_queue_is_isolated_and_uses_action_permissions(client, db_session):
    permission_codes = {
        "navigation.tasks.access",
        "tasks.management.read",
        "tasks.management.create",
    }
    role = _create_role_with_permissions(db_session, "management_creator", permission_codes)
    user = create_user(
        db_session,
        name="Gestor limitado",
        email="gestor.limitado@carfast.local",
        password="Secret123!",
        role_codes=[role.code],
        organizational_unit_codes=["management"],
    )
    management_task = Task(
        title="Decisão de gestão",
        task_type="management_task",
        source="v2_clean",
        status="new",
        priority="normal",
    )
    administration_task = Task(
        title="Segredo de administração",
        task_type="administration_task",
        source="v2_clean",
        status="new",
        priority="normal",
    )
    db_session.add_all([management_task, administration_task])
    db_session.commit()
    _login(client, user.email, "Secret123!")

    management_page = client.get("/v2-clean/tasks?workspace=management")
    assert management_page.status_code == 200
    assert "Decisão de gestão" in management_page.text
    assert "Segredo de administração" not in management_page.text

    created = client.post(
        "/v2-clean/tasks",
        data={"title": "Nova tarefa Gestão", "workspace": "management"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    created_task = db_session.scalar(select(Task).where(Task.title == "Nova tarefa Gestão"))
    assert created_task.task_type == "management_task"

    update_denied = client.post(
        f"/v2-clean/tasks/{created_task.id}/update",
        data={
            "title": "Alteração indevida",
            "workspace": "management",
            "status": "new",
            "priority": "normal",
        },
        follow_redirects=False,
    )
    assert update_denied.headers["location"].endswith("error=forbidden")
    db_session.refresh(created_task)
    assert created_task.title == "Nova tarefa Gestão"

    update_permission = db_session.scalar(
        select(Permission).where(Permission.code == "tasks.management.update")
    )
    db_session.add(RolePermission(role_id=role.id, permission_id=update_permission.id))
    db_session.commit()
    updated = client.post(
        f"/v2-clean/tasks/{created_task.id}/update",
        data={
            "title": "Gestão atualizada",
            "workspace": "management",
            "status": "in_execution",
            "priority": "high",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.refresh(created_task)
    assert created_task.title == "Gestão atualizada"

    close_denied = client.post(
        f"/v2-clean/tasks/{created_task.id}/close",
        follow_redirects=False,
    )
    assert close_denied.headers["location"].endswith("error=forbidden")
    db_session.refresh(created_task)
    assert created_task.closed_at is None

    close_permission = db_session.scalar(
        select(Permission).where(Permission.code == "tasks.management.close")
    )
    db_session.add(RolePermission(role_id=role.id, permission_id=close_permission.id))
    db_session.commit()
    closed = client.post(
        f"/v2-clean/tasks/{created_task.id}/close",
        follow_redirects=False,
    )
    assert closed.status_code == 303
    db_session.refresh(created_task)
    assert created_task.closed_at is not None


def test_recurring_area_requires_specific_permission(client, db_session):
    role = _create_role_with_permissions(
        db_session,
        "management_without_recurrence",
        {
            "navigation.tasks.access",
            "tasks.management.read",
            "tasks.management.create",
        },
    )
    user = create_user(
        db_session,
        name="Gestor sem recorrência",
        email="sem.recorrencia@carfast.local",
        password="Secret123!",
        role_codes=[role.code],
        organizational_unit_codes=["management"],
    )
    db_session.commit()
    _login(client, user.email, "Secret123!")

    denied = client.get("/v2-clean/tasks/recurring", follow_redirects=False)
    assert denied.status_code == 303
    assert denied.headers["location"].endswith("error=forbidden")

    permission = db_session.scalar(
        select(Permission).where(Permission.code == "tasks.recurring.manage")
    )
    db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db_session.commit()
    allowed = client.get("/v2-clean/tasks/recurring")
    assert allowed.status_code == 200
    assert "Tarefas recorrentes" in allowed.text
    assert "Europe/Lisbon" in allowed.text

    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "administration"))
    department = db_session.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == queue.id,
            WorkDepartment.code == "audit",
        )
    )

    created = client.post(
        "/v2-clean/tasks/recurring",
        data={
            "name": "Modelo mensal limitado",
            "task_title": "Rever decisão mensal",
            "workspace": "management",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "frequency": "monthly",
            "interval": "1",
            "next_run_at": "2026-08-10T09:30",
            "due_offset_days": "2",
            "task_priority": "high",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    model = db_session.scalar(
        select(TaskRecurrenceTemplate).where(
            TaskRecurrenceTemplate.name == "Modelo mensal limitado"
        )
    )
    assert model is not None and model.workspace == "administration"
    assert model.work_queue_id == queue.id
    assert model.work_department_id == department.id

    updated = client.post(
        f"/v2-clean/tasks/recurring/{model.id}/update",
        data={
            "name": "Modelo mensal revisto",
            "task_title": "Rever decisão mensal atualizada",
            "workspace": "management",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "frequency": "monthly",
            "interval": "2",
            "next_run_at": "2026-08-10T10:30",
            "due_offset_days": "3",
            "task_priority": "urgent",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.refresh(model)
    assert model.name == "Modelo mensal revisto"
    assert model.interval == 2
    assert model.updated_by_id == user.id

    toggled = client.post(
        f"/v2-clean/tasks/recurring/{model.id}/toggle",
        follow_redirects=False,
    )
    assert toggled.status_code == 303
    db_session.refresh(model)
    assert model.enabled is False


def test_recurrence_is_idempotent_and_records_schedule(authenticated_client, db_session):
    owner = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    scheduled_for = datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1)
    model = TaskRecurrenceTemplate(
        name="Verificação diária",
        enabled=True,
        timezone="Europe/Lisbon",
        frequency="daily",
        interval=1,
        next_run_at=scheduled_for,
        workspace="management",
        task_type="management_task",
        task_title="Rever indicadores",
        task_priority="normal",
        task_category="Acompanhamento",
        task_subcategory="task",
        due_offset_days=2,
        assigned_to_id=owner.id,
        created_by_id=owner.id,
    )
    db_session.add(model)
    db_session.commit()

    first = generate_due_recurring_tasks(db_session, now=datetime.now(UTC), commit=True)
    second = generate_due_recurring_tasks(db_session, now=datetime.now(UTC), commit=True)

    assert len(first) == 1
    assert second == []
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(TaskRecurrenceOccurrence)
            .where(TaskRecurrenceOccurrence.template_id == model.id)
        )
        == 1
    )
    generated_task = db_session.scalar(select(Task).where(Task.title == "Rever indicadores"))
    assert generated_task.task_type == "management_task"
    assert generated_task.source == "recurrence"
    assert generated_task.created_by_id == owner.id
    db_session.refresh(model)
    assert model.last_run_at is not None
    assert as_utc(model.next_run_at) > datetime.now(UTC)


def test_concurrent_generators_create_one_occurrence(tmp_path):
    database_path = tmp_path / "recurrence-concurrency.sqlite"
    engine = create_engine(
        f"sqlite+pysqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with sessions() as db:
        user = User(
            name="Criador concorrente",
            email="concorrencia@carfast.local",
            password_hash="not-used",
            active=True,
        )
        db.add(user)
        db.flush()
        model = TaskRecurrenceTemplate(
            name="Concorrência",
            enabled=True,
            timezone="Europe/Lisbon",
            frequency="weekly",
            interval=1,
            next_run_at=datetime.now(UTC).replace(microsecond=0) - timedelta(minutes=1),
            workspace="operational",
            task_type="operational_task",
            task_title="Ocorrência única",
            task_priority="normal",
            due_offset_days=0,
            created_by_id=user.id,
        )
        db.add(model)
        db.commit()
        model_id = model.id

    def run_generator() -> int:
        with sessions() as db:
            return len(generate_due_recurring_tasks(db, now=datetime.now(UTC), commit=True))

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: run_generator(), range(2)))

    with sessions() as db:
        assert sum(results) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(TaskRecurrenceOccurrence)
                .where(TaskRecurrenceOccurrence.template_id == model_id)
            )
            == 1
        )
        assert (
            db.scalar(
                select(func.count()).select_from(Task).where(Task.title == "Ocorrência única")
            )
            == 1
        )
