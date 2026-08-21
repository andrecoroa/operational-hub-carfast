"""Add role-managed navigation and module access permissions.

Revision ID: ffae1f2a3b4c
Revises: ffad0e1f2a3b
"""

from alembic import op
import sqlalchemy as sa


revision = "ffae1f2a3b4c"
down_revision = "ffad0e1f2a3b"
branch_labels = None
depends_on = None


NAVIGATION_PERMISSIONS = {
    "navigation.home.access": "Aceder a Início",
    "navigation.tasks.access": "Aceder ao Centro de Tarefas",
    "navigation.processes.access": "Aceder ao Centro de Processos",
    "navigation.workshop.access": "Aceder à Oficina",
    "navigation.fleet.access": "Aceder à Frota",
    "navigation.stock.access": "Aceder ao Stock",
    "navigation.email.access": "Aceder ao Email",
    "navigation.documentation.access": "Aceder à Documentação",
    "navigation.admin.access": "Aceder à Administração",
}

FUNCTIONAL_SOURCES = {
    "navigation.home.access": {"dashboard.read"},
    "navigation.tasks.access": {"tasks.read", "tasks.operational.read", "tasks.operational.write", "tasks.workshop.read", "tasks.workshop.write", "tasks.audit.read", "tasks.audit.write", "tasks.administration.read", "tasks.administration.write", "tasks.management.read", "tasks.management.create", "tasks.management.update", "tasks.management.close", "tasks.recurring.manage"},
    "navigation.processes.access": {"management_center.read", "management_center.write"},
    "navigation.workshop.access": {"workshop.read", "workshop.write"},
    "navigation.fleet.access": {"vehicles.read", "vehicles.write", "fleet.commerce.manage"},
    "navigation.stock.access": {"stock.read", "stock.operate", "stock.manage", "stock.orders.manage", "stock.inventory.count", "stock.inventory.confirm", "stock.compatibility.manage", "stock.conference"},
    "navigation.email.access": {"email.read", "email.triage", "email.reply", "email.approve", "email.manage"},
    "navigation.documentation.access": {"documents.read", "documents.write", "imports.run", "imports.approve"},
    "navigation.admin.access": {"admin.manage", "users.manage", "settings.manage", "admin.dashboard.read", "admin.users.read", "admin.users.manage", "admin.users.credentials", "admin.roles.read", "admin.roles.manage", "admin.organization.read", "admin.organization.manage", "admin.settings.read", "admin.settings.manage", "admin.workshop_models.read", "admin.workshop_models.manage", "admin.workshop_models.publish", "admin.audit.read", "admin.audit.export", "admin.integrations.read", "admin.integrations.manage", "admin.integrations.credentials", "admin.security.read", "admin.security.manage"},
}


def upgrade() -> None:
    connection = op.get_bind()
    for code, name in NAVIGATION_PERMISSIONS.items():
        exists = connection.execute(
            sa.text("SELECT id FROM permissions WHERE code = :code"), {"code": code}
        ).scalar()
        if exists is None:
            connection.execute(
                sa.text(
                    "INSERT INTO permissions (code, name, description) "
                    "VALUES (:code, :name, :description)"
                ),
                {
                    "code": code,
                    "name": name,
                    "description": "Controla a visibilidade do menu e o acesso ao módulo; não concede ações de escrita.",
                },
            )

    navigation_ids = dict(
        connection.execute(
            sa.text(
                "SELECT code, id FROM permissions WHERE code LIKE 'navigation.%.access'"
            )
        ).all()
    )
    roles = connection.execute(sa.text("SELECT id, code FROM roles")).all()
    for role_id, role_code in roles:
        functional_codes = {
            row[0]
            for row in connection.execute(
                sa.text(
                    "SELECT p.code FROM permissions p "
                    "JOIN role_permissions rp ON rp.permission_id = p.id "
                    "WHERE rp.role_id = :role_id"
                ),
                {"role_id": role_id},
            ).all()
        }
        derived = (
            set(NAVIGATION_PERMISSIONS)
            if role_code == "admin" or "admin.manage" in functional_codes
            else {
                nav_code
                for nav_code, source_codes in FUNCTIONAL_SOURCES.items()
                if functional_codes.intersection(source_codes)
            }
        )
        for nav_code in derived:
            permission_id = navigation_ids[nav_code]
            exists = connection.execute(
                sa.text(
                    "SELECT id FROM role_permissions "
                    "WHERE role_id = :role_id AND permission_id = :permission_id"
                ),
                {"role_id": role_id, "permission_id": permission_id},
            ).scalar()
            if exists is None:
                connection.execute(
                    sa.text(
                        "INSERT INTO role_permissions (role_id, permission_id) "
                        "VALUES (:role_id, :permission_id)"
                    ),
                    {"role_id": role_id, "permission_id": permission_id},
                )


def downgrade() -> None:
    connection = op.get_bind()
    codes = tuple(NAVIGATION_PERMISSIONS)
    permission_ids = [
        row[0]
        for row in connection.execute(
            sa.select(sa.column("id"))
            .select_from(sa.table("permissions"))
            .where(sa.column("code").in_(codes))
        ).all()
    ]
    if permission_ids:
        connection.execute(
            sa.delete(sa.table("role_permissions", sa.column("permission_id"))).where(
                sa.column("permission_id").in_(permission_ids)
            )
        )
        connection.execute(
            sa.delete(sa.table("permissions", sa.column("id"))).where(
                sa.column("id").in_(permission_ids)
            )
        )
