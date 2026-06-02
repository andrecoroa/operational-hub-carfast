"""Add task guided flows and recurrence fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ff6e7f8a9b0c"
down_revision: str | Sequence[str] | None = "ff5d6e7f8a9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("planned_for", sa.Date(), nullable=True))
    op.add_column("tasks", sa.Column("guided_flow_code", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_enabled", sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column("tasks", sa.Column("recurrence_rule", sa.String(length=80), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_interval", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_next_on", sa.Date(), nullable=True))
    op.add_column("tasks", sa.Column("recurrence_created_from_task_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_recurrence_created_from_task_id_tasks"),
        "tasks",
        "tasks",
        ["recurrence_created_from_task_id"],
        ["id"],
    )
    op.create_index(op.f("ix_tasks_planned_for"), "tasks", ["planned_for"], unique=False)
    op.create_index(op.f("ix_tasks_guided_flow_code"), "tasks", ["guided_flow_code"], unique=False)
    op.create_index(op.f("ix_tasks_recurrence_rule"), "tasks", ["recurrence_rule"], unique=False)
    op.create_index(op.f("ix_tasks_recurrence_next_on"), "tasks", ["recurrence_next_on"], unique=False)

    op.create_table(
        "task_guided_flow_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("flow_code", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("started_by_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["started_by_id"], ["users.id"], name=op.f("fk_task_guided_flow_runs_started_by_id_users")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_task_guided_flow_runs_task_id_tasks"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_guided_flow_runs")),
    )
    op.create_index(op.f("ix_task_guided_flow_runs_task_id"), "task_guided_flow_runs", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_guided_flow_runs_flow_code"), "task_guided_flow_runs", ["flow_code"], unique=False)
    op.create_index(op.f("ix_task_guided_flow_runs_status"), "task_guided_flow_runs", ["status"], unique=False)

    op.create_table(
        "task_guided_flow_step_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("flow_run_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("step_code", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("completed_by_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_task_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], name=op.f("fk_task_guided_flow_step_runs_completed_by_id_users")),
        sa.ForeignKeyConstraint(["flow_run_id"], ["task_guided_flow_runs.id"], name=op.f("fk_task_guided_flow_step_runs_flow_run_id_task_guided_flow_runs"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_task_id"], ["tasks.id"], name=op.f("fk_task_guided_flow_step_runs_generated_task_id_tasks")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_task_guided_flow_step_runs_task_id_tasks"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_guided_flow_step_runs")),
    )
    op.create_index(op.f("ix_task_guided_flow_step_runs_flow_run_id"), "task_guided_flow_step_runs", ["flow_run_id"], unique=False)
    op.create_index(op.f("ix_task_guided_flow_step_runs_task_id"), "task_guided_flow_step_runs", ["task_id"], unique=False)
    op.create_index(op.f("ix_task_guided_flow_step_runs_step_code"), "task_guided_flow_step_runs", ["step_code"], unique=False)
    op.create_index(op.f("ix_task_guided_flow_step_runs_status"), "task_guided_flow_step_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_task_guided_flow_step_runs_status"), table_name="task_guided_flow_step_runs")
    op.drop_index(op.f("ix_task_guided_flow_step_runs_step_code"), table_name="task_guided_flow_step_runs")
    op.drop_index(op.f("ix_task_guided_flow_step_runs_task_id"), table_name="task_guided_flow_step_runs")
    op.drop_index(op.f("ix_task_guided_flow_step_runs_flow_run_id"), table_name="task_guided_flow_step_runs")
    op.drop_table("task_guided_flow_step_runs")
    op.drop_index(op.f("ix_task_guided_flow_runs_status"), table_name="task_guided_flow_runs")
    op.drop_index(op.f("ix_task_guided_flow_runs_flow_code"), table_name="task_guided_flow_runs")
    op.drop_index(op.f("ix_task_guided_flow_runs_task_id"), table_name="task_guided_flow_runs")
    op.drop_table("task_guided_flow_runs")
    op.drop_index(op.f("ix_tasks_recurrence_next_on"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_recurrence_rule"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_guided_flow_code"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_planned_for"), table_name="tasks")
    op.drop_constraint(op.f("fk_tasks_recurrence_created_from_task_id_tasks"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "recurrence_created_from_task_id")
    op.drop_column("tasks", "recurrence_next_on")
    op.drop_column("tasks", "recurrence_interval")
    op.drop_column("tasks", "recurrence_rule")
    op.drop_column("tasks", "recurrence_enabled")
    op.drop_column("tasks", "guided_flow_code")
    op.drop_column("tasks", "planned_for")
