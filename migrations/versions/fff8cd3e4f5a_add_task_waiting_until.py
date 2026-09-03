"""Add an explicit task wait/resume deadline.

Revision ID: fff8cd3e4f5a
Revises: fff7bc2d3e4f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff8cd3e4f5a"
down_revision: str | Sequence[str] | None = "fff7bc2d3e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("waiting_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(op.f("ix_tasks_waiting_until"), "tasks", ["waiting_until"])


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_waiting_until"), table_name="tasks")
    op.drop_column("tasks", "waiting_until")
