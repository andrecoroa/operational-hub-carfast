"""Add vehicle document history module tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "ff2a3b4c5d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_document_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("source_record_type", sa.String(length=40), nullable=False, server_default="archive"),
        sa.Column("main_group", sa.String(length=40), nullable=False),
        sa.Column("subtype", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("comparison_state", sa.String(length=40), nullable=True),
        sa.Column("process_reference", sa.String(length=80), nullable=True),
        sa.Column("external_reference", sa.String(length=120), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("plate", sa.String(length=40), nullable=True),
        sa.Column("vin", sa.String(length=80), nullable=True),
        sa.Column("supplier_name", sa.String(length=200), nullable=True),
        sa.Column("raw_description", sa.Text(), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("km", sa.Integer(), nullable=True),
        sa.Column("end_km", sa.Integer(), nullable=True),
        sa.Column("has_physical_file", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_path", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("source_system", sa.String(length=80), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vehicle_document_records_vehicle_id"), "vehicle_document_records", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_document_id"), "vehicle_document_records", ["document_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_source_record_type"), "vehicle_document_records", ["source_record_type"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_main_group"), "vehicle_document_records", ["main_group"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_subtype"), "vehicle_document_records", ["subtype"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_status"), "vehicle_document_records", ["status"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_comparison_state"), "vehicle_document_records", ["comparison_state"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_process_reference"), "vehicle_document_records", ["process_reference"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_external_reference"), "vehicle_document_records", ["external_reference"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_title"), "vehicle_document_records", ["title"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_plate"), "vehicle_document_records", ["plate"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_vin"), "vehicle_document_records", ["vin"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_supplier_name"), "vehicle_document_records", ["supplier_name"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_document_date"), "vehicle_document_records", ["document_date"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_end_date"), "vehicle_document_records", ["end_date"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_km"), "vehicle_document_records", ["km"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_end_km"), "vehicle_document_records", ["end_km"], unique=False)
    op.create_index(op.f("ix_vehicle_document_records_source_system"), "vehicle_document_records", ["source_system"], unique=False)

    op.create_table(
        "vehicle_document_record_tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=True),
        sa.Column("free_text", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["record_id"], ["vehicle_document_records.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vehicle_document_record_tags_vehicle_id"), "vehicle_document_record_tags", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_record_tags_record_id"), "vehicle_document_record_tags", ["record_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_record_tags_document_id"), "vehicle_document_record_tags", ["document_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_record_tags_category"), "vehicle_document_record_tags", ["category"], unique=False)
    op.create_index(op.f("ix_vehicle_document_record_tags_value"), "vehicle_document_record_tags", ["value"], unique=False)
    op.create_index(op.f("ix_vehicle_document_record_tags_source_kind"), "vehicle_document_record_tags", ["source_kind"], unique=False)

    op.create_table(
        "vehicle_document_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False, server_default="warning"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["record_id"], ["vehicle_document_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vehicle_document_alerts_vehicle_id"), "vehicle_document_alerts", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_alerts_record_id"), "vehicle_document_alerts", ["record_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_alerts_document_id"), "vehicle_document_alerts", ["document_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_alerts_alert_type"), "vehicle_document_alerts", ["alert_type"], unique=False)
    op.create_index(op.f("ix_vehicle_document_alerts_severity"), "vehicle_document_alerts", ["severity"], unique=False)
    op.create_index(op.f("ix_vehicle_document_alerts_status"), "vehicle_document_alerts", ["status"], unique=False)

    op.create_table(
        "vehicle_document_pending_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("record_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="open"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["record_id"], ["vehicle_document_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_vehicle_document_pending_actions_vehicle_id"), "vehicle_document_pending_actions", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_pending_actions_record_id"), "vehicle_document_pending_actions", ["record_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_pending_actions_document_id"), "vehicle_document_pending_actions", ["document_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_pending_actions_task_id"), "vehicle_document_pending_actions", ["task_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_pending_actions_action_type"), "vehicle_document_pending_actions", ["action_type"], unique=False)
    op.create_index(op.f("ix_vehicle_document_pending_actions_status"), "vehicle_document_pending_actions", ["status"], unique=False)

    op.create_table(
        "vehicle_document_audit_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("field_code", sa.String(length=120), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=True),
        sa.Column("audited_on", sa.Date(), nullable=True),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("document_basis", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vehicle_id", "field_code", name="uq_vehicle_document_audit_field"),
    )
    op.create_index(op.f("ix_vehicle_document_audit_fields_vehicle_id"), "vehicle_document_audit_fields", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_vehicle_document_audit_fields_field_code"), "vehicle_document_audit_fields", ["field_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_vehicle_document_audit_fields_field_code"), table_name="vehicle_document_audit_fields")
    op.drop_index(op.f("ix_vehicle_document_audit_fields_vehicle_id"), table_name="vehicle_document_audit_fields")
    op.drop_table("vehicle_document_audit_fields")

    op.drop_index(op.f("ix_vehicle_document_pending_actions_status"), table_name="vehicle_document_pending_actions")
    op.drop_index(op.f("ix_vehicle_document_pending_actions_action_type"), table_name="vehicle_document_pending_actions")
    op.drop_index(op.f("ix_vehicle_document_pending_actions_task_id"), table_name="vehicle_document_pending_actions")
    op.drop_index(op.f("ix_vehicle_document_pending_actions_document_id"), table_name="vehicle_document_pending_actions")
    op.drop_index(op.f("ix_vehicle_document_pending_actions_record_id"), table_name="vehicle_document_pending_actions")
    op.drop_index(op.f("ix_vehicle_document_pending_actions_vehicle_id"), table_name="vehicle_document_pending_actions")
    op.drop_table("vehicle_document_pending_actions")

    op.drop_index(op.f("ix_vehicle_document_alerts_status"), table_name="vehicle_document_alerts")
    op.drop_index(op.f("ix_vehicle_document_alerts_severity"), table_name="vehicle_document_alerts")
    op.drop_index(op.f("ix_vehicle_document_alerts_alert_type"), table_name="vehicle_document_alerts")
    op.drop_index(op.f("ix_vehicle_document_alerts_document_id"), table_name="vehicle_document_alerts")
    op.drop_index(op.f("ix_vehicle_document_alerts_record_id"), table_name="vehicle_document_alerts")
    op.drop_index(op.f("ix_vehicle_document_alerts_vehicle_id"), table_name="vehicle_document_alerts")
    op.drop_table("vehicle_document_alerts")

    op.drop_index(op.f("ix_vehicle_document_record_tags_source_kind"), table_name="vehicle_document_record_tags")
    op.drop_index(op.f("ix_vehicle_document_record_tags_value"), table_name="vehicle_document_record_tags")
    op.drop_index(op.f("ix_vehicle_document_record_tags_category"), table_name="vehicle_document_record_tags")
    op.drop_index(op.f("ix_vehicle_document_record_tags_document_id"), table_name="vehicle_document_record_tags")
    op.drop_index(op.f("ix_vehicle_document_record_tags_record_id"), table_name="vehicle_document_record_tags")
    op.drop_index(op.f("ix_vehicle_document_record_tags_vehicle_id"), table_name="vehicle_document_record_tags")
    op.drop_table("vehicle_document_record_tags")

    op.drop_index(op.f("ix_vehicle_document_records_source_system"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_end_km"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_km"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_end_date"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_document_date"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_supplier_name"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_vin"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_plate"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_title"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_external_reference"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_process_reference"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_comparison_state"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_status"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_subtype"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_main_group"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_source_record_type"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_document_id"), table_name="vehicle_document_records")
    op.drop_index(op.f("ix_vehicle_document_records_vehicle_id"), table_name="vehicle_document_records")
    op.drop_table("vehicle_document_records")
