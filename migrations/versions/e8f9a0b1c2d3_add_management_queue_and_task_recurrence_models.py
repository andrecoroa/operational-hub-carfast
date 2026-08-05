"""Add Management task queue permissions and recurrence models.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "tasks.management.read": "Consultar fila de tarefas Gestão",
    "tasks.management.create": "Criar tarefas na fila Gestão",
    "tasks.management.update": "Alterar tarefas na fila Gestão",
    "tasks.management.close": "Fechar e reabrir tarefas na fila Gestão",
    "tasks.recurring.manage": "Gerir modelos de tarefas recorrentes",
}
ROLE_PERMISSIONS = {
    "admin": set(PERMISSIONS),
    "manager": set(PERMISSIONS),
}


def _seed_permissions() -> None:
    for code, name in PERMISSIONS.items():
        escaped_code = code.replace("'", "''")
        escaped_name = name.replace("'", "''")
        op.execute(
            sa.text(
                "INSERT INTO permissions (code, name, created_at) "
                f"SELECT '{escaped_code}', '{escaped_name}', CURRENT_TIMESTAMP "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM permissions "
                f"WHERE code = '{escaped_code}'"
                ")"
            )
        )
    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        for permission_code in permission_codes:
            op.execute(
                sa.text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT roles.id, permissions.id FROM roles, permissions "
                    f"WHERE roles.code = '{role_code}' "
                    f"AND permissions.code = '{permission_code}' "
                    "AND NOT EXISTS ("
                    "SELECT 1 FROM role_permissions existing "
                    "WHERE existing.role_id = roles.id "
                    "AND existing.permission_id = permissions.id"
                    ")"
                )
            )


def upgrade() -> None:
    op.create_table(
        "task_recurrence_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("timezone", sa.String(length=80), nullable=False, server_default="Europe/Lisbon"),
        sa.Column("frequency", sa.String(length=40), nullable=False),
        sa.Column("interval", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace", sa.String(length=40), nullable=False),
        sa.Column("task_type", sa.String(length=80), nullable=False),
        sa.Column("task_title", sa.String(length=200), nullable=False),
        sa.Column("task_description", sa.Text(), nullable=True),
        sa.Column("task_priority", sa.String(length=40), nullable=False, server_default="normal"),
        sa.Column("task_category", sa.String(length=80), nullable=True),
        sa.Column("task_subcategory", sa.String(length=120), nullable=True),
        sa.Column("due_offset_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=False),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "enabled",
        "frequency",
        "next_run_at",
        "last_run_at",
        "workspace",
        "task_type",
        "assigned_to_id",
        "created_by_id",
    ):
        op.create_index(
            f"ix_task_recurrence_templates_{column}", "task_recurrence_templates", [column]
        )

    op.create_table(
        "task_recurrence_occurrences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="created"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.ForeignKeyConstraint(
            ["template_id"], ["task_recurrence_templates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id"),
        sa.UniqueConstraint(
            "template_id", "scheduled_for", name="uq_task_recurrence_occurrence_schedule"
        ),
    )
    for column in ("template_id", "scheduled_for", "task_id", "status"):
        op.create_index(
            f"ix_task_recurrence_occurrences_{column}", "task_recurrence_occurrences", [column]
        )
    _seed_permissions()


def downgrade() -> None:
    permission_codes = ", ".join(f"'{code}'" for code in PERMISSIONS)
    op.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN ("
            f"SELECT id FROM permissions WHERE code IN ({permission_codes})"
            ")"
        )
    )
    op.execute(sa.text(f"DELETE FROM permissions WHERE code IN ({permission_codes})"))
    for column in ("status", "task_id", "scheduled_for", "template_id"):
        op.drop_index(
            f"ix_task_recurrence_occurrences_{column}", table_name="task_recurrence_occurrences"
        )
    op.drop_table("task_recurrence_occurrences")
    for column in (
        "created_by_id",
        "assigned_to_id",
        "task_type",
        "workspace",
        "last_run_at",
        "next_run_at",
        "frequency",
        "enabled",
    ):
        op.drop_index(
            f"ix_task_recurrence_templates_{column}", table_name="task_recurrence_templates"
        )
    op.drop_table("task_recurrence_templates")
