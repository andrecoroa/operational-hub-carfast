"""Add one-level task cases and optional task association.

Revision ID: fff6ab1c2d3e
Revises: fff59a0b1c2d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff6ab1c2d3e"
down_revision: str | Sequence[str] | None = "fff59a0b1c2d"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "cases.read": "Consultar casos de tarefas",
    "cases.create": "Criar casos de tarefas",
    "cases.update": "Alterar casos de tarefas",
}


def upgrade() -> None:
    op.create_table(
        "task_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("workspace", sa.String(40), nullable=False),
        sa.Column("work_queue_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "workspace IN ('tasks_support', 'administration')",
            name="ck_task_cases_workspace",
        ),
        sa.ForeignKeyConstraint(["work_queue_id"], ["work_queues.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_task_cases_title", "task_cases", ["title"])
    op.create_index("ix_task_cases_workspace", "task_cases", ["workspace"])
    op.create_index("ix_task_cases_work_queue_id", "task_cases", ["work_queue_id"])
    op.create_index("ix_task_cases_created_by_id", "task_cases", ["created_by_id"])
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.add_column(sa.Column("case_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tasks_case_id_task_cases",
            "task_cases",
            ["case_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_tasks_case_id", ["case_id"])
    bind = op.get_bind()
    for code, name in PERMISSIONS.items():
        bind.execute(
            sa.text(
                "INSERT INTO permissions (code, name, description) "
                "SELECT :code, :name, NULL WHERE NOT EXISTS "
                "(SELECT 1 FROM permissions WHERE code = :code)"
            ),
            {"code": code, "name": name},
        )


def downgrade() -> None:
    bind = op.get_bind()
    case_count = bind.execute(sa.text("SELECT COUNT(*) FROM task_cases")).scalar_one()
    grants = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM role_permissions rp JOIN permissions p "
            "ON p.id = rp.permission_id WHERE p.code IN "
            "('cases.read','cases.create','cases.update')"
        )
    ).scalar_one()
    if case_count or grants:
        raise RuntimeError(
            "Task cases downgrade blocked to preserve data/grants: "
            f"cases={case_count}, grants={grants}."
        )
    with op.batch_alter_table("tasks") as batch_op:
        batch_op.drop_index("ix_tasks_case_id")
        batch_op.drop_constraint("fk_tasks_case_id_task_cases", type_="foreignkey")
        batch_op.drop_column("case_id")
    op.drop_index("ix_task_cases_created_by_id", table_name="task_cases")
    op.drop_index("ix_task_cases_work_queue_id", table_name="task_cases")
    op.drop_index("ix_task_cases_workspace", table_name="task_cases")
    op.drop_index("ix_task_cases_title", table_name="task_cases")
    op.drop_table("task_cases")
    # Retain catalogue rows: they may have predated this migration, and their
    # ownership cannot be inferred safely during downgrade.
