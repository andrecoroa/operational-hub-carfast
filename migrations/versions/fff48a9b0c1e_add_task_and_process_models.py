"""Add versioned task templates and process models.

Revision ID: fff48a9b0c1e
Revises: fff37f8a9b0d
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff48a9b0c1e"
down_revision: str | Sequence[str] | None = "fff37f8a9b0d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("task_templates", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(120), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("code", name="uq_task_templates_code"))
    op.create_index("ix_task_templates_active", "task_templates", ["active"])
    op.create_table("task_template_versions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("template_id", sa.Integer(), sa.ForeignKey("task_templates.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False, server_default="draft"), sa.Column("definition_json", sa.JSON(), nullable=False), sa.Column("definition_digest", sa.String(64), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.CheckConstraint("status IN ('draft','published','retired')", name="ck_task_template_version_status"), sa.UniqueConstraint("template_id", "version", name="uq_task_template_version"))
    op.create_index("ix_task_template_versions_template_id", "task_template_versions", ["template_id"])
    op.create_index("ix_task_template_versions_status", "task_template_versions", ["status"])
    op.create_table("task_template_usages", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("template_id", sa.Integer(), sa.ForeignKey("task_templates.id", ondelete="CASCADE"), nullable=False), sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False), sa.Column("favorite", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("last_used_at", sa.DateTime(timezone=True)), sa.UniqueConstraint("template_id", "user_id", name="uq_task_template_usage"))
    op.create_index("ix_task_template_usages_template_id", "task_template_usages", ["template_id"])
    op.create_index("ix_task_template_usages_user_id", "task_template_usages", ["user_id"])
    op.create_table("process_models", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("code", sa.String(120), nullable=False), sa.Column("name", sa.String(200), nullable=False), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.UniqueConstraint("code", name="uq_process_models_code"))
    op.create_index("ix_process_models_active", "process_models", ["active"])
    op.create_table("process_model_versions", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("model_id", sa.Integer(), sa.ForeignKey("process_models.id", ondelete="CASCADE"), nullable=False), sa.Column("version", sa.Integer(), nullable=False), sa.Column("status", sa.String(24), nullable=False, server_default="draft"), sa.Column("definition_json", sa.JSON(), nullable=False), sa.Column("definition_digest", sa.String(64), nullable=False), sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.CheckConstraint("status IN ('draft','published','retired')", name="ck_process_model_version_status"), sa.UniqueConstraint("model_id", "version", name="uq_process_model_version"))
    op.create_index("ix_process_model_versions_model_id", "process_model_versions", ["model_id"])
    op.create_index("ix_process_model_versions_status", "process_model_versions", ["status"])
    op.create_table("process_instances", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("model_version_id", sa.Integer(), sa.ForeignKey("process_model_versions.id", ondelete="RESTRICT"), nullable=False), sa.Column("model_snapshot_json", sa.JSON(), nullable=False), sa.Column("model_snapshot_digest", sa.String(64), nullable=False), sa.Column("title", sa.String(200), nullable=False), sa.Column("status", sa.String(24), nullable=False, server_default="active"), sa.Column("source", sa.String(40), nullable=False, server_default="manual"), sa.Column("context_json", sa.JSON(), nullable=False), sa.Column("organizational_unit_code", sa.String(80)), sa.Column("manager_exception_justification", sa.Text()), sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()), sa.CheckConstraint("status IN ('active','blocked','completed','cancelled')", name="ck_process_instance_status"))
    op.create_index("ix_process_instances_model_version_id", "process_instances", ["model_version_id"])
    op.create_index("ix_process_instances_organizational_unit_code", "process_instances", ["organizational_unit_code"])
    op.create_index("ix_process_instances_status", "process_instances", ["status"])
    op.create_index("ix_process_instances_source", "process_instances", ["source"])
    op.create_index("ix_process_instances_created_by_id", "process_instances", ["created_by_id"])
    op.create_table("process_instance_events", sa.Column("id", sa.Integer(), primary_key=True), sa.Column("process_instance_id", sa.Integer(), sa.ForeignKey("process_instances.id", ondelete="CASCADE"), nullable=False), sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("action", sa.String(80), nullable=False), sa.Column("details_json", sa.JSON()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()))
    op.create_index("ix_process_instance_events_process_instance_id", "process_instance_events", ["process_instance_id"])
    op.create_index("ix_process_instance_events_actor_user_id", "process_instance_events", ["actor_user_id"])
    op.create_index("ix_process_instance_events_action", "process_instance_events", ["action"])
    op.add_column("tasks", sa.Column("task_template_version_id", sa.Integer(), sa.ForeignKey("task_template_versions.id", ondelete="RESTRICT")))
    op.add_column("tasks", sa.Column("task_template_snapshot_json", sa.JSON()))
    op.add_column("tasks", sa.Column("task_template_snapshot_digest", sa.String(64)))
    op.add_column("tasks", sa.Column("process_instance_id", sa.Integer(), sa.ForeignKey("process_instances.id", ondelete="SET NULL")))
    op.add_column("tasks", sa.Column("process_step_code", sa.String(120)))
    op.create_index("ix_tasks_task_template_version_id", "tasks", ["task_template_version_id"])
    op.create_index("ix_tasks_process_instance_id", "tasks", ["process_instance_id"])
    op.create_index("ix_tasks_process_step_code", "tasks", ["process_step_code"])


def downgrade() -> None:
    for name in ("ix_tasks_process_step_code", "ix_tasks_process_instance_id", "ix_tasks_task_template_version_id"):
        op.drop_index(name, table_name="tasks")
    for name in ("process_step_code", "process_instance_id", "task_template_snapshot_digest", "task_template_snapshot_json", "task_template_version_id"):
        op.drop_column("tasks", name)
    op.drop_table("process_instance_events")
    op.drop_table("process_instances")
    op.drop_table("process_model_versions")
    op.drop_table("process_models")
    op.drop_table("task_template_usages")
    op.drop_table("task_template_versions")
    op.drop_table("task_templates")
