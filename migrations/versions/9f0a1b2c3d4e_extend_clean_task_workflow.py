"""Extend Clean task queues, context and permissions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9f0a1b2c3d4e"
down_revision: str | Sequence[str] | None = "8e9f0a1b2c3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("invoice_number", sa.String(length=120), nullable=True))
    op.create_index("ix_tasks_invoice_number", "tasks", ["invoice_number"], unique=False)

    permissions = sa.table(
        "permissions",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("created_at", sa.DateTime),
        sa.column("updated_at", sa.DateTime),
    )
    op.bulk_insert(
        permissions,
        [
            {"code": "tasks.audit.read", "name": "Ver centro de tarefas auditoria"},
            {"code": "tasks.audit.write", "name": "Gerir centro de tarefas auditoria"},
            {"code": "tasks.assign.peer", "name": "Atribuir tarefas a utilizadores do mesmo nível"},
        ],
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ('tasks.audit.read','tasks.audit.write','tasks.assign.peer')
        WHERE r.code IN ('admin','manager','operator')
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    )
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        JOIN permissions p ON p.code IN ('tasks.audit.read','tasks.audit.write')
        WHERE r.code = 'auditor'
          AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
          )
        """
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code IN "
        "('tasks.audit.read','tasks.audit.write','tasks.assign.peer'))"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN "
        "('tasks.audit.read','tasks.audit.write','tasks.assign.peer')"
    )
    op.drop_index("ix_tasks_invoice_number", table_name="tasks")
    op.drop_column("tasks", "invoice_number")
