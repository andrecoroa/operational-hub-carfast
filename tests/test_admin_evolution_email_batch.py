from sqlalchemy import select

from app.models.admin import Permission, Role, RolePermission
from app.models.audit import AuditLog
from app.models.email import EmailChannel, EmailChannelRole, EmailExecutorEligibility
from app.models.evolution import EvolutionRecord, EvolutionRecordHistory
from app.models.tasks import Task
from app.services.authorization import expand_permission_aliases
from app.services.users import create_user


def test_evolution_register_preserves_history_and_converts_approved_record(
    authenticated_client, db_session
):
    created = authenticated_client.post(
        "/v2-clean/admin/evolution",
        data={
            "record_type": "feature",
            "module": "email",
            "title": "Resposta assistida",
            "description": "Proposta a avaliar antes de criar trabalho.",
            "origin": "Reunião operacional",
            "priority": "high",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    record = db_session.scalar(
        select(EvolutionRecord).where(EvolutionRecord.title == "Resposta assistida")
    )
    assert record is not None
    assert created.headers["location"].startswith(f"/v2-clean/admin/evolution/{record.id}")

    updated = authenticated_client.post(
        f"/v2-clean/admin/evolution/{record.id}",
        data={
            "record_type": "feature",
            "module": "email",
            "title": "Resposta assistida aprovada",
            "description": record.description,
            "origin": record.origin,
            "priority": "urgent",
            "status": "approved",
            "decision": "Avançar por fases.",
            "notes": "Manter auditoria.",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.expire_all()
    history = db_session.scalars(
        select(EvolutionRecordHistory).where(EvolutionRecordHistory.record_id == record.id)
    ).all()
    assert {item.field_name for item in history} >= {"title", "priority", "status", "decision"}

    converted = authenticated_client.post(
        f"/v2-clean/admin/evolution/{record.id}/convert",
        follow_redirects=False,
    )
    assert converted.status_code == 303
    db_session.expire_all()
    converted_record = db_session.get(EvolutionRecord, record.id)
    assert converted_record.status == "implementation"
    assert converted_record.reference_task_id is not None
    task = db_session.get(Task, converted_record.reference_task_id)
    assert task is not None
    assert task.source == "admin_evolution"
    assert f"Registo de Evolução #{record.id}" in task.description

    repeated = authenticated_client.post(
        f"/v2-clean/admin/evolution/{record.id}/convert",
        follow_redirects=False,
    )
    assert "error=not_convertible" in repeated.headers["location"]
    assert len(db_session.scalars(select(Task).where(Task.source == "admin_evolution")).all()) == 1


def test_evolution_and_module_navigation_are_compact_and_compatible(authenticated_client):
    page = authenticated_client.get("/v2-clean/admin/evolution")
    assert page.status_code == 200
    assert "Registo de Evolução" in page.text
    assert "evolution-table" in page.text
    assert "Configuração por módulo" in page.text
    assert "Execução / elegibilidade" in page.text

    email_module = authenticated_client.get("/v2-clean/admin/modules/email", follow_redirects=False)
    assert email_module.status_code == 303
    assert email_module.headers["location"].endswith("work-classification?view=channels")


def test_permission_aliases_are_additive_and_do_not_conflate_portal_permissions():
    expanded = expand_permission_aliases({"users.manage", "tasks.audit.read"})
    assert "admin.users.manage" in expanded
    assert "tasks.administration.read" in expanded
    assert "users.manage" in expanded
    assert not any(code.startswith("portal.") for code in expanded)


def test_email_access_batch_requires_preview_confirmation_and_is_audited(
    authenticated_client, db_session
):
    role = db_session.scalar(select(Role).where(Role.code == "viewer"))
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    assert role is not None and channel is not None

    preview = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-access/batch/preview",
        data={
            "role_ids": [str(role.id)],
            "channel_ids": [str(channel.id)],
            "operation": "apply",
            "preset": "triage_reply",
        },
    )
    assert preview.status_code == 200
    assert preview.json()["count"] == 1
    assert preview.json()["changes"][0]["after"]["can_read"] is True
    assert preview.json()["changes"][0]["after"]["can_reply"] is True

    not_confirmed = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-access/batch",
        data={
            "role_ids": [str(role.id)],
            "channel_ids": [str(channel.id)],
            "operation": "apply",
            "preset": "triage_reply",
        },
        follow_redirects=False,
    )
    assert "error=preview_required" in not_confirmed.headers["location"]
    assert (
        db_session.scalar(
            select(EmailChannelRole).where(
                EmailChannelRole.role_id == role.id,
                EmailChannelRole.channel_id == channel.id,
            )
        )
        is None
    )

    applied = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-access/batch",
        data={
            "role_ids": [str(role.id)],
            "channel_ids": [str(channel.id)],
            "operation": "apply",
            "preset": "triage_reply",
            "confirmed": "on",
        },
        follow_redirects=False,
    )
    assert applied.status_code == 303
    db_session.expire_all()
    grant = db_session.scalar(
        select(EmailChannelRole).where(
            EmailChannelRole.role_id == role.id,
            EmailChannelRole.channel_id == channel.id,
        )
    )
    assert grant is not None
    assert grant.can_read and grant.can_reply and grant.can_assume
    assert (
        db_session.scalar(
            select(AuditLog).where(AuditLog.action == "clean_admin.email.access_batch_applied")
        )
        is not None
    )


def test_email_access_batch_rejects_invalid_dependency_without_partial_write(
    authenticated_client, db_session
):
    role = db_session.scalar(select(Role).where(Role.code == "operator"))
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id.desc()))
    assert role is not None and channel is not None
    existing = db_session.scalar(
        select(EmailChannelRole).where(
            EmailChannelRole.role_id == role.id,
            EmailChannelRole.channel_id == channel.id,
        )
    )
    if existing:
        db_session.delete(existing)
        db_session.commit()

    response = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-access/batch",
        data={
            "role_ids": [str(role.id)],
            "channel_ids": [str(channel.id)],
            "operation": "apply",
            "actions": ["can_reply"],
            "confirmed": "on",
        },
        follow_redirects=False,
    )
    assert "error=read_required" in response.headers["location"]
    assert (
        db_session.scalar(
            select(EmailChannelRole).where(
                EmailChannelRole.role_id == role.id,
                EmailChannelRole.channel_id == channel.id,
            )
        )
        is None
    )


def test_email_executor_batch_applies_cross_product_in_one_audited_operation(
    authenticated_client, db_session
):
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    admin_role = db_session.scalar(select(Role).where(Role.code == "admin"))
    assert channel is not None and admin_role is not None
    admin_permission = db_session.scalar(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == admin_role.id, Permission.code == "admin.manage")
    )
    assert admin_permission is not None
    from app.models.admin import User, UserRole

    admin_user = db_session.scalar(
        select(User)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.role_id == admin_role.id)
    )
    assert admin_user is not None

    applied = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-executors/batch",
        data={
            "channel_ids": [str(channel.id)],
            "category_ids": ["0"],
            "user_ids": [str(admin_user.id)],
            "operation": "apply",
            "confirmed": "on",
        },
        follow_redirects=False,
    )
    assert applied.status_code == 303
    db_session.expire_all()
    eligibility = db_session.scalar(
        select(EmailExecutorEligibility).where(
            EmailExecutorEligibility.channel_id == channel.id,
            EmailExecutorEligibility.category_id.is_(None),
            EmailExecutorEligibility.user_id == admin_user.id,
        )
    )
    assert eligibility is not None and eligibility.active
    assert (
        db_session.scalar(
            select(AuditLog).where(AuditLog.action == "clean_admin.email.executor_batch_applied")
        )
        is not None
    )


def test_admin_is_grouped_by_domains_with_central_operations_area(authenticated_client):
    response = authenticated_client.get("/v2-clean/admin/operations")

    assert response.status_code == 200
    assert "Pesquisar na Administração" in response.text
    assert "Operações e Service Desk" in response.text
    assert "Centro de Tarefas" in response.text
    assert "Centro de Processos" in response.text
    assert "Permissões operacionais" in response.text
    for label in (
        "Utilizadores e Acessos",
        "Organização",
        "Módulos Operacionais",
        "Integrações",
        "Sistema e Auditoria",
        "Evolução da Aplicação",
    ):
        assert label in response.text
    assert "data-admin-domain-search" in response.text
    assert "data-admin-domain-group" in response.text


def test_global_evolution_action_creates_with_automatic_context(authenticated_client, db_session):
    home = authenticated_client.get("/v2-clean")
    assert home.status_code == 200
    assert 'title="Novo registo de evolução"' in home.text
    assert 'action="/evolution/quick"' in home.text
    assert "future_implementation" in home.text

    response = authenticated_client.post(
        "/evolution/quick",
        data={
            "record_type": "decision",
            "title": "Manter histórico operacional",
            "description": "Decisão registada no contexto da fila.",
            "priority": "high",
            "current_url": "/v2-clean/tasks?workspace=operational",
            "module": "general",
            "context": "Centro de Tarefas",
        },
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 201
    record = db_session.get(EvolutionRecord, response.json()["id"])
    assert record is not None
    assert record.record_type == "decision"
    assert record.module == "service_desk"
    assert record.reference_chat == "/v2-clean/tasks?workspace=operational"
    assert "Centro de Tarefas" in (record.notes or "")
    assert db_session.scalar(
        select(AuditLog).where(AuditLog.action == "clean_admin.evolution.quick_created")
    )


def test_evolution_creation_permission_does_not_grant_management(client, db_session):
    user = create_user(
        db_session,
        name="Consulta com evolução",
        email="evolution.viewer@carfast.local",
        password="Secret123!",
        role_codes=["viewer"],
    )
    db_session.commit()
    login = client.post(
        "/login",
        data={"email": user.email, "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    client.post(
        "/change-notice",
        data={"next_url": "/v2-clean"},
        follow_redirects=False,
    )

    created = client.post(
        "/evolution/quick",
        data={
            "record_type": "error",
            "title": "Erro observado",
            "description": "Descrição para análise administrativa.",
            "priority": "normal",
            "current_url": "https://malicious.example/escape",
            "module": "fleet_sales",
            "context": "Página de consulta",
        },
        headers={"Accept": "application/json"},
    )
    assert created.status_code == 201
    record_id = created.json()["id"]
    record = db_session.get(EvolutionRecord, record_id)
    assert record is not None
    assert record.reference_chat == "/v2-clean"
    assert record.module == "fleet_sales"

    management_page = client.get("/v2-clean/admin/evolution", follow_redirects=False)
    assert management_page.status_code == 303
    assert management_page.headers["location"] == "/v2-clean?error=forbidden"

    update = client.post(
        f"/v2-clean/admin/evolution/{record_id}",
        data={
            "record_type": "error",
            "module": "fleet_sales",
            "title": "Tentativa sem autorização",
            "description": record.description,
            "priority": "urgent",
            "status": "approved",
        },
        follow_redirects=False,
    )
    assert update.status_code == 303
    assert update.headers["location"] == "/v2-clean?error=forbidden"
    db_session.expire_all()
    unchanged = db_session.get(EvolutionRecord, record_id)
    assert unchanged is not None
    assert unchanged.title == "Erro observado"
    assert unchanged.priority == "normal"
