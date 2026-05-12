"""add task type

Revision ID: a6b7c8d9e0f1
Revises: f5a6b7c8d9e0
Create Date: 2026-05-12 20:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("task_type", sa.String(length=80), nullable=True))
    op.create_index(op.f("ix_tasks_task_type"), "tasks", ["task_type"], unique=False)
    op.execute("UPDATE tasks SET task_type = 'task' WHERE task_type IS NULL")
    op.alter_column("tasks", "task_type", nullable=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_task_type"), table_name="tasks")
    op.drop_column("tasks", "task_type")
