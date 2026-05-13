"""repair task type column

Revision ID: f8a9b0c1d2e3
Revises: f7a8b9c0d1e2
Create Date: 2026-05-13 01:25:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f8a9b0c1d2e3"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    task_columns = {column["name"] for column in inspector.get_columns("tasks")}
    if "task_type" not in task_columns:
        op.add_column("tasks", sa.Column("task_type", sa.String(length=80), nullable=True))

    op.execute("UPDATE tasks SET task_type = 'task' WHERE task_type IS NULL")
    op.alter_column("tasks", "task_type", nullable=False)

    indexes = {index["name"] for index in inspector.get_indexes("tasks")}
    if "ix_tasks_task_type" not in indexes:
        op.create_index(op.f("ix_tasks_task_type"), "tasks", ["task_type"], unique=False)


def downgrade() -> None:
    pass
