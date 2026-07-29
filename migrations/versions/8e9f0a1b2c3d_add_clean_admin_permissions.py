"""Add granular permissions and starter roles for Clean administration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e9f0a1b2c3d"
down_revision: str | Sequence[str] | None = "7d8e9f0a1b2c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "admin.dashboard.read": "Ver visão geral da administração",
    "admin.users.read": "Ver utilizadores",
    "admin.users.manage": "Gerir utilizadores e acessos",
    "admin.users.credentials": "Definir credenciais temporárias",
    "admin.roles.read": "Ver perfis e permissões",
    "admin.roles.manage": "Gerir perfis e permissões",
    "admin.organization.read": "Ver organização e equipas",
    "admin.organization.manage": "Gerir organização e equipas",
    "admin.settings.read": "Ver configurações",
    "admin.settings.manage": "Gerir configurações",
    "admin.workshop_models.read": "Ver modelos da Oficina",
    "admin.workshop_models.manage": "Gerir modelos da Oficina",
    "admin.workshop_models.publish": "Publicar modelos da Oficina",
    "admin.audit.read": "Consultar auditoria do sistema",
    "admin.audit.export": "Exportar auditoria do sistema",
    "admin.integrations.read": "Ver integrações",
    "admin.integrations.manage": "Gerir integrações",
    "admin.integrations.credentials": "Gerir credenciais de integrações",
    "admin.security.read": "Ver revisão de acessos",
    "admin.security.manage": "Gerir controlos de segurança",
}

ROLE_PERMISSIONS = {
    "user_admin": {
        "dashboard.read",
        "admin.dashboard.read",
        "admin.users.read",
        "admin.users.manage",
        "admin.users.credentials",
        "admin.roles.read",
        "admin.roles.manage",
        "admin.organization.read",
        "admin.security.read",
    },
    "functional_admin": {
        "dashboard.read",
        "admin.dashboard.read",
        "admin.settings.read",
        "admin.settings.manage",
        "admin.workshop_models.read",
        "admin.workshop_models.manage",
        "admin.workshop_models.publish",
        "admin.integrations.read",
        "admin.integrations.manage",
        "admin.audit.read",
    },
    "auditor": {
        "dashboard.read",
        "admin.dashboard.read",
        "admin.users.read",
        "admin.roles.read",
        "admin.organization.read",
        "admin.settings.read",
        "admin.workshop_models.read",
        "admin.audit.read",
        "admin.audit.export",
        "admin.integrations.read",
        "admin.security.read",
        "vehicles.read",
        "workshop.read",
        "tasks.read",
        "documents.read",
    },
}

LEGACY_PERMISSION_MAP = {
    "admin.manage": set(PERMISSIONS),
    "users.manage": {
        "admin.dashboard.read",
        "admin.users.read",
        "admin.users.manage",
        "admin.users.credentials",
        "admin.roles.read",
        "admin.organization.read",
        "admin.security.read",
    },
    "settings.manage": {
        "admin.dashboard.read",
        "admin.settings.read",
        "admin.settings.manage",
        "admin.workshop_models.read",
        "admin.workshop_models.manage",
        "admin.workshop_models.publish",
        "admin.integrations.read",
        "admin.integrations.manage",
        "admin.audit.read",
    },
}


def _id_for(connection, table: str, code: str) -> int | None:
    return connection.execute(
        sa.text(f"SELECT id FROM {table} WHERE code = :code"),
        {"code": code},
    ).scalar()


def _grant(connection, role_id: int, permission_id: int) -> None:
    exists = connection.execute(
        sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": role_id, "permission_id": permission_id},
    ).scalar()
    if not exists:
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": role_id, "permission_id": permission_id},
        )


def upgrade() -> None:
    connection = op.get_bind()
    for code, name in PERMISSIONS.items():
        if _id_for(connection, "permissions", code) is None:
            connection.execute(
                sa.text(
                    "INSERT INTO permissions (code, name, description) "
                    "VALUES (:code, :name, :description)"
                ),
                {"code": code, "name": name, "description": None},
            )

    starter_roles = {
        "user_admin": "Administrador de Utilizadores",
        "functional_admin": "Administrador Funcional",
        "auditor": "Auditor / Conformidade",
    }
    for code, name in starter_roles.items():
        if _id_for(connection, "roles", code) is None:
            connection.execute(
                sa.text(
                    "INSERT INTO roles (code, name, description, active, is_system) "
                    "VALUES (:code, :name, :description, :active, :is_system)"
                ),
                {
                    "code": code,
                    "name": name,
                    "description": None,
                    "active": True,
                    "is_system": True,
                },
            )

    admin_role_id = _id_for(connection, "roles", "admin")
    if admin_role_id is not None:
        for code in PERMISSIONS:
            permission_id = _id_for(connection, "permissions", code)
            if permission_id is not None:
                _grant(connection, admin_role_id, permission_id)

    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        role_id = _id_for(connection, "roles", role_code)
        if role_id is None:
            continue
        for code in permission_codes:
            permission_id = _id_for(connection, "permissions", code)
            if permission_id is not None:
                _grant(connection, role_id, permission_id)

    for legacy_code, new_codes in LEGACY_PERMISSION_MAP.items():
        legacy_permission_id = _id_for(connection, "permissions", legacy_code)
        if legacy_permission_id is None:
            continue
        role_ids = connection.execute(
            sa.text("SELECT role_id FROM role_permissions WHERE permission_id = :permission_id"),
            {"permission_id": legacy_permission_id},
        ).scalars()
        for role_id in role_ids:
            for code in new_codes:
                permission_id = _id_for(connection, "permissions", code)
                if permission_id is not None:
                    _grant(connection, role_id, permission_id)


def downgrade() -> None:
    connection = op.get_bind()
    permission_ids = [
        permission_id
        for code in PERMISSIONS
        if (permission_id := _id_for(connection, "permissions", code)) is not None
    ]
    for permission_id in permission_ids:
        connection.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id"),
            {"permission_id": permission_id},
        )
        connection.execute(
            sa.text("DELETE FROM permissions WHERE id = :permission_id"),
            {"permission_id": permission_id},
        )

    for role_code in ROLE_PERMISSIONS:
        role_id = _id_for(connection, "roles", role_code)
        if role_id is None:
            continue
        assigned_users = connection.execute(
            sa.text("SELECT id FROM user_roles WHERE role_id = :role_id LIMIT 1"),
            {"role_id": role_id},
        ).scalar()
        if not assigned_users:
            connection.execute(
                sa.text("DELETE FROM role_permissions WHERE role_id = :role_id"),
                {"role_id": role_id},
            )
            connection.execute(
                sa.text("DELETE FROM roles WHERE id = :role_id"),
                {"role_id": role_id},
            )
