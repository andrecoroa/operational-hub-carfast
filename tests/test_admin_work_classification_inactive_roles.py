import pytest
from sqlalchemy import func, select

from app.models.admin import Role
from app.models.audit import AuditLog
from app.models.email import EmailChannel, EmailChannelRole
from app.services.users import create_user


@pytest.mark.parametrize("view", ["desk", "permissions", "channels"])
def test_work_classification_renders_active_inactive_and_orphan_role_grants_without_writes(
    authenticated_client, db_session, view
):
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    assert channel is not None
    active_role = Role(code="p1_active_role", name="Perfil P1 ativo", active=True)
    inactive_role = Role(code="p1_inactive_role", name="Perfil P1 inativo", active=False)
    db_session.add_all([active_role, inactive_role])
    db_session.flush()
    active_grant = EmailChannelRole(channel_id=channel.id, role_id=active_role.id, can_read=True)
    inactive_grant = EmailChannelRole(
        channel_id=channel.id, role_id=inactive_role.id, can_read=True
    )
    orphan_grant = EmailChannelRole(channel_id=channel.id, role_id=987654321, can_read=True)
    db_session.add_all([active_grant, inactive_grant, orphan_grant])
    db_session.commit()

    grant_count_before = db_session.scalar(select(func.count()).select_from(EmailChannelRole))
    audit_count_before = db_session.scalar(select(func.count()).select_from(AuditLog))

    response = authenticated_client.get(f"/v2-clean/admin/work-classification?view={view}")

    assert response.status_code == 200
    assert active_role.name in response.text
    assert inactive_role.name in response.text
    assert "Inativo" in response.text
    assert "Perfil indisponível" in response.text
    assert "987654321" not in response.text
    assert (
        f'<option value="{inactive_role.id}">{inactive_role.name}</option>'
        not in response.text
    )
    assert f'data-dialog-open="work-edit-channel-role-{active_grant.id}"' in response.text
    assert f'data-dialog-open="work-edit-channel-role-{inactive_grant.id}"' not in response.text
    assert f'data-dialog-open="work-edit-channel-role-{orphan_grant.id}"' not in response.text
    assert (
        db_session.scalar(select(func.count()).select_from(EmailChannelRole)) == grant_count_before
    )
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == audit_count_before


def test_active_role_grant_behavior_is_unchanged(authenticated_client, db_session):
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    role = Role(code="p1_new_active_role", name="Novo perfil P1", active=True)
    db_session.add(role)
    db_session.commit()

    response = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-channel-roles",
        data={
            "channel_id": channel.id,
            "role_id": role.id,
            "can_read": "on",
            "visibility_mode": "scope_all",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    grant = db_session.scalar(
        select(EmailChannelRole).where(
            EmailChannelRole.channel_id == channel.id,
            EmailChannelRole.role_id == role.id,
        )
    )
    assert grant is not None and grant.can_read is True


@pytest.mark.parametrize("role_kind", ["inactive", "missing"])
def test_single_grant_post_rejects_unavailable_roles_without_writes_or_leakage(
    authenticated_client, db_session, role_kind
):
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    assert channel is not None
    role_id = 987654322
    forbidden_name = "Perfil secreto inativo"
    if role_kind == "inactive":
        role = Role(code="p1_forbidden_role", name=forbidden_name, active=False)
        db_session.add(role)
        db_session.commit()
        role_id = role.id
    grant_count_before = db_session.scalar(select(func.count()).select_from(EmailChannelRole))
    audit_count_before = db_session.scalar(select(func.count()).select_from(AuditLog))

    response = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-channel-roles",
        data={
            "channel_id": channel.id,
            "role_id": role_id,
            "can_read": "on",
            "visibility_mode": "scope_all",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert forbidden_name not in response.text
    assert str(role_id) not in response.text
    assert (
        db_session.scalar(select(func.count()).select_from(EmailChannelRole)) == grant_count_before
    )
    assert db_session.scalar(select(func.count()).select_from(AuditLog)) == audit_count_before


def test_batch_post_rejects_inactive_role_without_partial_write(authenticated_client, db_session):
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    role = Role(code="p1_batch_inactive", name="Batch inativo", active=False)
    db_session.add(role)
    db_session.commit()

    response = authenticated_client.post(
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

    assert response.status_code == 400
    assert (
        db_session.scalar(
            select(EmailChannelRole).where(
                EmailChannelRole.channel_id == channel.id,
                EmailChannelRole.role_id == role.id,
            )
        )
        is None
    )


def test_batch_preview_rejects_inactive_role(authenticated_client, db_session):
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    role = Role(code="p1_preview_inactive", name="Preview inativo", active=False)
    db_session.add(role)
    db_session.commit()

    response = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-access/batch/preview",
        data={
            "role_ids": [str(role.id)],
            "channel_ids": [str(channel.id)],
            "operation": "apply",
            "preset": "triage_reply",
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "invalid_selection"}


def test_batch_preview_rejects_inactive_copy_source(
    authenticated_client, db_session
):
    channel = db_session.scalar(select(EmailChannel).order_by(EmailChannel.id))
    active_role = Role(code="p1_copy_target", name="Destino ativo", active=True)
    inactive_role = Role(code="p1_copy_source", name="Origem inativa", active=False)
    db_session.add_all([active_role, inactive_role])
    db_session.commit()

    response = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-access/batch/preview",
        data={
            "role_ids": [str(active_role.id)],
            "channel_ids": [str(channel.id)],
            "operation": "copy",
            "source_role_id": str(inactive_role.id),
            "source_channel_id": str(channel.id),
        },
    )

    assert response.status_code == 400
    assert response.json() == {"error": "missing_copy_source"}


def test_work_classification_requires_authorization(client, db_session):
    user = create_user(
        db_session,
        name="Operador sem administração",
        email="p1.no.admin@example.test",
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
        "/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False
    )
    response = client.get(
        "/v2-clean/admin/work-classification?view=channels",
        follow_redirects=False,
    )

    assert response.status_code == 403
