"""Add task waiting target fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "fd1e2f3a4b5c"
down_revision: str | Sequence[str] | None = "fc1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("waiting_for_user_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("waiting_for_team_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_waiting_for_user_id_users"),
        "tasks",
        "users",
        ["waiting_for_user_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_tasks_waiting_for_team_id_teams"),
        "tasks",
        "teams",
        ["waiting_for_team_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_tasks_waiting_for_team_id_teams"), "tasks", type_="foreignkey")
    op.drop_constraint(op.f("fk_tasks_waiting_for_user_id_users"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "waiting_for_team_id")
    op.drop_column("tasks", "waiting_for_user_id")
