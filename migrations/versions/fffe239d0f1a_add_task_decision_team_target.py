"""Allow a task decision to target one person or one team.

Revision ID: fffe239d0f1a
Revises: fffd128c9e0f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fffe239d0f1a"
down_revision: str | Sequence[str] | None = "fffd128c9e0f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("task_decisions", "decider_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "task_decisions",
        sa.Column("decider_team_id", sa.Integer(), sa.ForeignKey("teams.id"), nullable=True),
    )
    op.create_index(
        "ix_task_decisions_decider_team_id", "task_decisions", ["decider_team_id"]
    )
    op.create_check_constraint(
        "ck_task_decisions_single_target",
        "task_decisions",
        "(decider_id IS NOT NULL AND decider_team_id IS NULL) OR "
        "(decider_id IS NULL AND decider_team_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_task_decisions_single_target", "task_decisions", type_="check")
    op.drop_index("ix_task_decisions_decider_team_id", table_name="task_decisions")
    op.drop_column("task_decisions", "decider_team_id")
    op.alter_column("task_decisions", "decider_id", existing_type=sa.Integer(), nullable=False)
