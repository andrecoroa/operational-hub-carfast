"""Add permission-scoped task decision requests.

Revision ID: fffaef5a6b7c
Revises: fff9de4f5a6b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fffaef5a6b7c"
down_revision: str | Sequence[str] | None = "fff9de4f5a6b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision_needed", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("impact_value", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_task_status", sa.String(80), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("resolution_comment", sa.Text(), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'information_requested')",
            name="ck_task_decisions_status",
        ),
    )
    op.create_index("ix_task_decisions_task_id", "task_decisions", ["task_id"])
    op.create_index("ix_task_decisions_requested_by_id", "task_decisions", ["requested_by_id"])
    op.create_index("ix_task_decisions_decider_id", "task_decisions", ["decider_id"])
    op.create_index("ix_task_decisions_due_at", "task_decisions", ["due_at"])
    op.create_index("ix_task_decisions_status", "task_decisions", ["status"])


def downgrade() -> None:
    op.drop_table("task_decisions")
