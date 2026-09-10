"""Add an optional local deadline time to tasks.

Revision ID: fff9de4f5a6b
Revises: fff8cd3e4f5a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff9de4f5a6b"
down_revision: str | Sequence[str] | None = "fff8cd3e4f5a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("due_time", sa.Time(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "due_time")
