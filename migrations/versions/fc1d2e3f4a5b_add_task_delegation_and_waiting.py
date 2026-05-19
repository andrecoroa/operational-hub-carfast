"""Add task delegation and waiting reason fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "fc1d2e3f4a5b"
down_revision: str | Sequence[str] | None = "fb1c2d3e4f5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("delegated_to_user_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("delegated_to_team_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("waiting_reason", sa.String(length=80), nullable=True))
    op.add_column("tasks", sa.Column("waiting_reason_detail", sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_delegated_to_user_id_users"),
        "tasks",
        "users",
        ["delegated_to_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_tasks_delegated_to_team_id_teams"),
        "tasks",
        "teams",
        ["delegated_to_team_id"],
        ["id"],
    )
    op.create_index(op.f("ix_tasks_waiting_reason"), "tasks", ["waiting_reason"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_waiting_reason"), table_name="tasks")
    op.drop_constraint(op.f("fk_tasks_delegated_to_team_id_teams"), "tasks", type_="foreignkey")
    op.drop_constraint(op.f("fk_tasks_delegated_to_user_id_users"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "waiting_reason_detail")
    op.drop_column("tasks", "waiting_reason")
    op.drop_column("tasks", "delegated_to_team_id")
    op.drop_column("tasks", "delegated_to_user_id")
