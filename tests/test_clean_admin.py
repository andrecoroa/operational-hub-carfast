from sqlalchemy import delete, select

from app.models.admin import Permission, Role, RolePermission, User, UserRole
from app.models.audit import AuditLog
from app.models.documents import Document
from app.models.tasks import Task
from app.models.work_hierarchy import RoleWorkScope, WorkDepartment, WorkQueue
from app.models.workshop_phased import WorkshopPhasedProcess, WorkshopPhasedProcessPhase
from app.services.bootstrap import seed_roles
from app.services.users import create_user
from app.web import clean_admin


def _login(client, email: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    notice = client.post(
        "/change-notice",
        data={"next_url": "/v2-clean"},
        follow_redirects=False,
    )
    assert notice.status_code == 303


def test_clean_admin_pages_are_available_to_admin(authenticated_client):
    root = authenticated_client.get("/v2-clean/admin", follow_redirects=False)
    assert root.status_code == 303
    assert root.headers["location"] == "/v2-clean/admin/overview"

    for path, marker in (
        ("/v2-clean/admin/overview", "Modo local"),
        ("/v2-clean/admin/users", "Utilizadores"),
        ("/v2-clean/admin/roles", "Perfis e permissões"),
        ("/v2-clean/admin/organization", "Áreas organizacionais"),
        ("/v2-clean/admin/settings", "Configurações"),
        ("/v2-clean/admin/audit", "Auditoria do sistema"),
        ("/v2-clean/admin/integrations", "Entradas de integração"),
        ("/v2-clean/admin/security", "Utilizadores administrativos"),
    ):
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert marker in response.text

    roles_page = authenticated_client.get("/v2-clean/admin/roles")
    assert "clean-admin-role-table" in roles_page.text
    assert "clean-admin-role-picker" in roles_page.text
    assert "clean-admin-permission-groups" in roles_page.text
    assert "Matriz de permissões" in roles_page.text
    assert "Código técnico" in roles_page.text
    assert ">Email<" in roles_page.text
    assert "/v2-clean/admin/work-classification?view=channels" in roles_page.text


def test_seed_roles_preserves_manually_removed_profile_permission(db_session):
    role = db_session.scalar(select(Role).where(Role.code == "operator"))
    permission = db_session.scalar(select(Permission).where(Permission.code == "email.read"))
    assert role is not None
    assert permission is not None
    db_session.execute(
        delete(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
    )
    db_session.commit()

    seed_roles(db_session)
    db_session.flush()

    restored = db_session.scalar(
        select(RolePermission).where(
            RolePermission.role_id == role.id,
            RolePermission.permission_id == permission.id,
        )
    )
    assert restored is None


def test_clean_admin_users_uses_compact_table_and_wide_access_dialog(authenticated_client):
    response = authenticated_client.get("/v2-clean/admin/users")

    assert response.status_code == 200
    assert 'class="clean-admin-user-table"' in response.text
    assert 'data-label="Último acesso"' in response.text
    assert 'class="clean-admin-dialog"' in response.text
    assert 'class="clean-admin-access-option"' in response.text
    assert "Gestão de acessos" in response.text
    assert "O último Super Admin não pode ser desativado" in response.text
    assert 'class="clean-admin-user-grid"' not in response.text


def test_work_classification_uses_compact_hierarchy_table_and_editors(authenticated_client):
    response = authenticated_client.get("/v2-clean/admin/work-classification")

    assert response.status_code == 200
    assert 'data-work-admin-tab="structure"' in response.text
    assert 'data-work-level="category"' in response.text
    assert 'class="clean-table clean-work-structure-table"' in response.text
    assert 'class="clean-work-editor"' in response.text
    assert 'data-work-edit-parent' in response.text
    assert "Código estável (não editável)" in response.text
    assert "Administração da hierarquia" in response.text


def test_work_classification_registers_lisbon_datetime_filter():
    assert "lisbon_datetime" in clean_admin.templates.env.filters


def test_work_scope_permissions_have_an_edit_action(authenticated_client, db_session):
    role = db_session.scalar(select(Role).where(Role.code == "operator"))
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    assert role is not None
    assert queue is not None
    scope = RoleWorkScope(
        role_id=role.id,
        queue_id=queue.id,
        can_read=True,
        can_create=False,
        can_update=False,
        can_assign=False,
        can_close=False,
        can_manage=False,
    )
    db_session.add(scope)
    db_session.commit()

    response = authenticated_client.get("/v2-clean/admin/work-classification")

    assert response.status_code == 200
    assert f'data-dialog-open="work-edit-scope-{scope.id}"' in response.text
    assert f'action="/v2-clean/admin/work-classification/scopes/{scope.id}"' in response.text


def test_work_scope_permissions_can_be_edited(authenticated_client, db_session):
    role = db_session.scalar(select(Role).where(Role.code == "operator"))
    tasks_queue = db_session.scalar(
        select(WorkQueue).where(WorkQueue.code == "tasks_support")
    )
    admin_queue = db_session.scalar(
        select(WorkQueue).where(WorkQueue.code == "administration")
    )
    assert role is not None
    assert tasks_queue is not None
    assert admin_queue is not None
    audit_department = db_session.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == admin_queue.id,
            WorkDepartment.code == "audit",
        )
    )
    assert audit_department is not None
    scope = RoleWorkScope(role_id=role.id, queue_id=tasks_queue.id, can_read=True)
    db_session.add(scope)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/admin/work-classification/scopes/{scope.id}",
        data={
            "role_id": role.id,
            "queue_id": admin_queue.id,
            "department_id": audit_department.id,
            "can_read": "on",
            "can_update": "on",
            "can_assign": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("?saved=1")
    db_session.expire_all()
    updated = db_session.get(RoleWorkScope, scope.id)
    assert updated is not None
    assert updated.queue_id == admin_queue.id
    assert updated.department_id == audit_department.id
    assert updated.can_read is True
    assert updated.can_update is True
    assert updated.can_assign is True
    assert updated.can_create is False


def test_work_classification_editor_can_change_parent_and_fields(
    authenticated_client, db_session
):
    department = db_session.scalar(
        select(WorkDepartment).where(WorkDepartment.code == "operations")
    )
    administration = db_session.scalar(
        select(WorkQueue).where(WorkQueue.code == "administration")
    )
    assert department is not None
    assert administration is not None

    response = authenticated_client.post(
        f"/v2-clean/admin/work-classification/items/department/{department.id}",
        data={
            "parent_id": administration.id,
            "name": "Operações revistas",
            "description": "Descrição atualizada pela edição.",
            "sort_order": 35,
            "requires_description": "on",
            "active": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("?saved=1")
    db_session.expire_all()
    updated = db_session.get(WorkDepartment, department.id)
    assert updated is not None
    assert updated.queue_id == administration.id
    assert updated.name == "Operações revistas"
    assert updated.description == "Descrição atualizada pela edição."
    assert updated.sort_order == 35
    assert updated.requires_description is True
    assert updated.active is True


def test_clean_admin_settings_shows_portuguese_labels_without_changing_codes(
    authenticated_client,
):
    response = authenticated_client.get("/v2-clean/admin/settings")

    assert response.status_code == 200
    assert "Tipos de documento" in response.text
    assert "Tipos de importação" in response.text
    assert "Código técnico: <code>document_type</code>" in response.text
    assert "Código técnico: <code>import_type</code>" in response.text
    assert "Frota Rentway" in response.text


def test_user_admin_is_limited_to_assigned_admin_sections(client, db_session):
    create_user(
        db_session,
        name="Admin Utilizadores",
        email="users.admin@carfast.local",
        password="Secret12345!",
        role_codes=["user_admin"],
        organizational_unit_codes=["administration"],
    )
    db_session.commit()
    _login(client, "users.admin@carfast.local", "Secret12345!")

    users_page = client.get("/v2-clean/admin/users")
    assert users_page.status_code == 200
    assert "Criar utilizador" in users_page.text

    settings_page = client.get("/v2-clean/admin/settings", follow_redirects=False)
    assert settings_page.status_code == 303
    assert settings_page.headers["location"] == "/v2-clean?error=forbidden"


def test_last_active_admin_cannot_lose_admin_role(authenticated_client, db_session):
    admin = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    viewer = db_session.scalar(select(Role).where(Role.code == "viewer"))
    assert admin is not None
    assert viewer is not None

    response = authenticated_client.post(
        f"/v2-clean/admin/users/{admin.id}/access",
        data={
            "active": "on",
            "role_codes": ["viewer"],
            "unit_codes": ["carfast"],
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "error=last_admin" in response.headers["location"]
    db_session.expire_all()
    assert "admin" in {
        row[0]
        for row in db_session.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == admin.id)
        ).all()
    }


def test_admin_user_deactivation_preserves_operational_records(
    authenticated_client,
    db_session,
):
    target = create_user(
        db_session,
        name="Operador Preservado",
        email="preserve@carfast.local",
        password="Secret12345!",
        role_codes=["operator"],
        organizational_unit_codes=["workshop"],
    )
    task = Task(
        title="Tarefa preservada",
        task_type="workshop_task",
        status="new",
        created_by_id=target.id,
    )
    db_session.add(task)
    db_session.flush()
    document = Document(
        title="Foto preservada",
        document_type="workshop_photo",
        original_name="foto.jpg",
        file_name="foto.jpg",
        storage_provider="local",
        storage_path="uploads/workshop/foto.jpg",
        uploaded_by_id=target.id,
    )
    db_session.add(document)
    process = WorkshopPhasedProcess(
        process_type="workshop",
        title="Processo preservado",
        creation_mode="operational",
        status="open",
        plate_snapshot="AA-00-AA",
        priority="normal",
        created_by_id=target.id,
        metadata_json={"evidence": "preserve"},
    )
    db_session.add(process)
    db_session.flush()
    phase = WorkshopPhasedProcessPhase(
        process_id=process.id,
        phase_code="entrada",
        name="Entrada",
        status="completed",
        sort_order=1,
        data_json={
            "uploads": [
                {
                    "stored_name": "foto-entrada.jpg",
                    "path": "uploads/workshop_entry/1/foto-entrada.jpg",
                }
            ]
        },
    )
    db_session.add(phase)
    db_session.commit()
    ids = (target.id, task.id, document.id, process.id, phase.id)

    response = authenticated_client.post(
        f"/v2-clean/admin/users/{target.id}/access",
        data={"role_codes": ["operator"], "unit_codes": ["workshop"]},
        follow_redirects=False,
    )
    assert response.status_code == 303

    db_session.expire_all()
    preserved_user = db_session.get(User, ids[0])
    preserved_task = db_session.get(Task, ids[1])
    preserved_document = db_session.get(Document, ids[2])
    preserved_process = db_session.get(WorkshopPhasedProcess, ids[3])
    preserved_phase = db_session.get(WorkshopPhasedProcessPhase, ids[4])
    assert preserved_user is not None and not preserved_user.active
    assert preserved_task is not None and preserved_task.created_by_id == preserved_user.id
    assert preserved_document is not None
    assert preserved_document.storage_path == "uploads/workshop/foto.jpg"
    assert preserved_process is not None and preserved_process.metadata_json == {
        "evidence": "preserve"
    }
    assert preserved_phase is not None
    assert preserved_phase.data_json["uploads"][0]["stored_name"] == "foto-entrada.jpg"


def test_password_reset_is_audited_without_storing_password(
    authenticated_client,
    db_session,
):
    target = create_user(
        db_session,
        name="Password Test",
        email="password@carfast.local",
        password="Secret12345!",
        role_codes=["viewer"],
    )
    db_session.commit()
    new_password = "Temporary98765!"

    response = authenticated_client.post(
        f"/v2-clean/admin/users/{target.id}/password",
        data={"password": new_password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    entry = db_session.scalar(
        select(AuditLog)
        .where(
            AuditLog.action == "clean_admin.user.password_reset",
            AuditLog.entity_id == str(target.id),
        )
        .order_by(AuditLog.id.desc())
    )
    assert entry is not None
    serialized = f"{entry.detail} {entry.before_json} {entry.after_json}"
    assert new_password not in serialized


def test_audit_export_requires_export_permission(authenticated_client):
    response = authenticated_client.get("/v2-clean/admin/audit/export")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "carfast-auditoria-" in response.headers["content-disposition"]
