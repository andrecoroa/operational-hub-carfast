import re

from sqlalchemy import select

import app.web.router as task_router
from app.models import (
    Permission,
    Role,
    RolePermission,
    RoleWorkScope,
    Task,
    User,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
)
from app.services.task_queues import resolve_task_queue_capabilities
from app.services.users import create_user


EMAIL = "queue.matrix@carfast.local"
PASSWORD = "Secret123!"


def _user_with_queue_grants(db, *codes: str) -> tuple[User, Role]:
    role = Role(code="queue_matrix", name="Queue matrix", active=True)
    db.add(role)
    db.flush()
    for code in codes:
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, name=code)
            db.add(permission)
            db.flush()
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    user = create_user(
        db, name="Queue matrix", email=EMAIL, password=PASSWORD,
        role_codes=[role.code], organizational_unit_codes=["carfast"],
    )
    db.commit()
    return user, role


def _web_login(client) -> None:
    assert client.post(
        "/login", data={"email": EMAIL, "password": PASSWORD},
        follow_redirects=False,
    ).status_code == 303
    assert client.post(
        "/change-notice", data={"next_url": "/v2-clean"},
        follow_redirects=False,
    ).status_code == 303


def _api_headers(client) -> dict[str, str]:
    client.cookies.clear()
    response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_audit_alias_never_exposes_administration_queue_web_api_or_resolver(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    monkeypatch.setattr(task_router.settings, "task_cases_enabled", True)
    user, _ = _user_with_queue_grants(
        db_session,
        "navigation.tasks.access", "tasks.read", "tasks.operational.read", "tasks.operational.write",
        "tasks.audit.read", "cases.read", "cases.create", "cases.update",
    )
    assert [item.code for item in resolve_task_queue_capabilities(db_session, user)] == [
        "tasks_support"
    ]

    _web_login(client)
    default = client.get("/v2-clean/tasks")
    forged = client.get("/v2-clean/tasks?queue=administration")
    legacy_forged = client.get("/v2-clean/tasks?queue=audit")
    invalid = client.get("/v2-clean/tasks?queue=forged")
    assert default.status_code == 200, default.text
    assert 'data-active-queue="tasks_support"' in default.text
    assert '<option value="administration"' not in default.text
    assert forged.status_code == 403
    assert legacy_forged.status_code == 403
    assert invalid.status_code == 400

    headers = _api_headers(client)
    administrative_task = Task(
        title="Administrative API secret",
        task_type="administration_task",
        status="new",
        priority="normal",
    )
    db_session.add(administrative_task)
    db_session.commit()
    queues = client.get("/api/tasks/queues", headers=headers)
    assert queues.status_code == 200
    assert [item["code"] for item in queues.json()] == ["tasks_support"]
    assert client.get("/api/tasks/queues/tasks_support", headers=headers).status_code == 200
    assert client.get("/api/tasks/queues/administration", headers=headers).status_code == 403
    assert client.get("/api/tasks/queues/audit", headers=headers).status_code == 403
    assert client.get("/api/tasks/queues/forged", headers=headers).status_code == 400
    assert client.get("/api/tasks?task_type=administration_task", headers=headers).status_code == 403
    assert client.get(f"/api/tasks/{administrative_task.id}", headers=headers).status_code == 403
    assert client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Forged administrative create",
            "task_type": "administration_task",
            "status": "new",
            "priority": "normal",
        },
    ).status_code == 403
    assert client.patch(
        f"/api/tasks/{administrative_task.id}",
        headers=headers,
        json={"title": "Forged administrative update"},
    ).status_code == 403


def test_direct_administration_grant_exposes_only_the_explicit_queue_capability(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    user, _ = _user_with_queue_grants(
        db_session,
        "navigation.tasks.access", "tasks.read", "tasks.operational.read", "tasks.administration.read",
    )
    assert [item.code for item in resolve_task_queue_capabilities(db_session, user)] == [
        "tasks_support", "administration"
    ]
    _web_login(client)
    page = client.get("/v2-clean/tasks?queue=administration")
    assert page.status_code == 200
    assert 'data-active-queue="administration"' in page.text
    assert '<option value="tasks_support"' in page.text
    assert '<option value="administration"' in page.text
    headers = _api_headers(client)
    assert client.get("/api/tasks/queues/administration", headers=headers).status_code == 200


def test_administration_read_grant_never_authorizes_mutation(
    client, db_session
) -> None:
    _user_with_queue_grants(
        db_session, "tasks.read", "tasks.write", "tasks.administration.read"
    )
    task = Task(
        title="Read-only administration task",
        task_type="administration_task",
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()
    headers = _api_headers(client)

    assert client.get(f"/api/tasks/{task.id}", headers=headers).status_code == 200
    assert client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Forbidden administration create",
            "task_type": "administration_task",
            "status": "new",
            "priority": "normal",
        },
    ).status_code == 403
    assert client.patch(
        f"/api/tasks/{task.id}", headers=headers, json={"title": "Forbidden update"}
    ).status_code == 403


def test_create_hierarchy_exposes_only_writable_authorized_queues(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    _, role = _user_with_queue_grants(
        db_session,
        "navigation.tasks.access",
        "tasks.read",
        "tasks.operational.read",
        "tasks.operational.write",
        "tasks.administration.read",
        "classification.active.use",
    )
    administration = db_session.scalar(
        select(WorkQueue).where(WorkQueue.code == "administration")
    )
    operational = db_session.scalar(
        select(WorkQueue).where(WorkQueue.code == "tasks_support")
    )
    operational_department = db_session.scalar(
        select(WorkDepartment)
        .where(WorkDepartment.queue_id == operational.id)
        .order_by(WorkDepartment.id)
    )
    if not db_session.scalar(
        select(WorkCategory).where(
            WorkCategory.department_id == operational_department.id
        )
    ):
        db_session.add(
            WorkCategory(
                department_id=operational_department.id,
                code="queue-matrix-operational",
                name="Operacional autorizada",
                active=True,
            )
        )
    db_session.add(
        RoleWorkScope(
            role_id=role.id,
            queue_id=operational.id,
            can_read=True,
            can_create=True,
        )
    )
    db_session.commit()
    _web_login(client)

    page = client.get("/v2-clean/tasks?queue=administration")
    queue_select = re.search(
        r'<select name="work_queue_id".*?</select>', page.text, re.S
    ).group(0)

    assert page.status_code == 200
    assert f'<option value="{operational.id}"' in queue_select
    assert f'<option value="{administration.id}"' not in queue_select


def test_authorized_creation_in_administration_uses_the_selected_hierarchy(
    client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    _, role = _user_with_queue_grants(
        db_session,
        "navigation.tasks.access",
        "tasks.read",
        "tasks.operational.read",
        "tasks.operational.write",
        "tasks.administration.read",
        "tasks.administration.write",
        "classification.active.use",
    )
    queue = db_session.scalar(
        select(WorkQueue).where(WorkQueue.code == "administration")
    )
    department = db_session.scalar(
        select(WorkDepartment)
        .where(WorkDepartment.queue_id == queue.id, WorkDepartment.active.is_(True))
        .order_by(WorkDepartment.id)
    )
    category = db_session.scalar(
        select(WorkCategory)
        .where(
            WorkCategory.department_id == department.id,
            WorkCategory.active.is_(True),
        )
        .order_by(WorkCategory.id)
    )
    if category is None:
        category = WorkCategory(
            department_id=department.id,
            code="queue-matrix-administration",
            name="Administração autorizada",
            active=True,
        )
        db_session.add(category)
        db_session.flush()
    db_session.add(
        RoleWorkScope(
            role_id=role.id,
            queue_id=queue.id,
            can_read=True,
            can_create=True,
        )
    )
    db_session.commit()
    _web_login(client)
    page = client.get("/v2-clean/tasks?queue=administration")
    queue_select = re.search(
        r'<select name="work_queue_id".*?</select>', page.text, re.S
    ).group(0)
    assert f'<option value="{queue.id}"' in queue_select
    assert f'data-parent="{queue.id}"' in page.text
    assert f'data-parent="{department.id}"' in page.text

    created = client.post(
        "/v2-clean/tasks",
        data={
            "title": "Revisão administrativa autorizada",
            "record_type": "task",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
            "priority": "normal",
        },
        follow_redirects=False,
    )

    assert created.status_code == 303
    task = db_session.scalar(
        select(Task).where(Task.title == "Revisão administrativa autorizada")
    )
    assert task is not None
    assert task.task_type == "administration_task"
    assert task.work_queue_id == queue.id
    assert task.work_department_id == department.id
    assert task.work_category_id == category.id


def test_admin_manage_cannot_forge_administration_creation(client, db_session) -> None:
    _user_with_queue_grants(
        db_session,
        "navigation.tasks.access",
        "admin.manage",
        "classification.active.use",
    )
    _web_login(client)

    forged = client.post(
        "/v2-clean/tasks",
        data={
            "title": "Administração sem grant direto",
            "record_type": "task",
            "classification_version": "2",
            "workspace": "administration",
            "category": "Financeiro",
            "subcategory": "Validação",
            "priority": "normal",
        },
        follow_redirects=False,
    )

    assert forged.status_code == 303
    assert "error=forbidden" in forged.headers["location"]
    assert db_session.scalar(
        select(Task).where(Task.title == "Administração sem grant direto")
    ) is None


def test_unknown_task_types_fail_closed_on_list_create_and_update(
    client, db_session
) -> None:
    _user_with_queue_grants(db_session, "tasks.read", "tasks.write")
    task = Task(
        title="Known support task", task_type="task", status="new", priority="normal"
    )
    db_session.add(task)
    db_session.commit()
    headers = _api_headers(client)

    assert client.get("/api/tasks?task_type=forged", headers=headers).status_code == 400
    assert client.post(
        "/api/tasks",
        headers=headers,
        json={
            "title": "Unknown task type",
            "task_type": "forged",
            "status": "new",
            "priority": "normal",
        },
    ).status_code == 400
    assert client.patch(
        f"/api/tasks/{task.id}", headers=headers, json={"task_type": "forged"}
    ).status_code == 400


def test_admin_manage_does_not_replace_explicit_administration_task_grant(
    db_session,
) -> None:
    user, _ = _user_with_queue_grants(
        db_session, "tasks.operational.read", "admin.manage"
    )
    assert [item.code for item in resolve_task_queue_capabilities(db_session, user)] == [
        "tasks_support"
    ]


def test_inactive_user_has_no_queue_capabilities(db_session) -> None:
    user, _ = _user_with_queue_grants(db_session, "tasks.operational.read")
    user.active = False
    db_session.commit()
    assert resolve_task_queue_capabilities(db_session, user) == ()
