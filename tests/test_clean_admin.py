from sqlalchemy import select

from app.models.admin import Role, User, UserRole
from app.models.audit import AuditLog
from app.models.documents import Document
from app.models.tasks import Task
from app.models.workshop_phased import WorkshopPhasedProcess, WorkshopPhasedProcessPhase
from app.services.users import create_user


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
    assert "Matriz de permissões" in roles_page.text
    assert "Código técnico" in roles_page.text


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
