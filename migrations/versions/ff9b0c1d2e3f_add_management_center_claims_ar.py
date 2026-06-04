"""Add management center claims AR foundation."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ff9b0c1d2e3f"
down_revision: str | Sequence[str] | None = "ff8a9b0c1d2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "management_process_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_management_process_types")),
    )
    op.create_index(op.f("ix_management_process_types_code"), "management_process_types", ["code"], unique=True)
    op.create_index(op.f("ix_management_process_types_active"), "management_process_types", ["active"], unique=False)

    op.create_table(
        "management_processes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_type_id", sa.Integer(), nullable=False),
        sa.Column("internal_reference", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("phase", sa.String(length=120), nullable=False),
        sa.Column("priority", sa.String(length=80), nullable=False),
        sa.Column("plate", sa.String(length=40), nullable=True),
        sa.Column("document_reference", sa.String(length=160), nullable=True),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("driver_name", sa.String(length=200), nullable=True),
        sa.Column("pending_reason", sa.String(length=160), nullable=True),
        sa.Column("pending_detail", sa.Text(), nullable=True),
        sa.Column("total_claim_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("total_cost_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("sla_due_on", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_summary_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["process_type_id"],
            ["management_process_types.id"],
            name=op.f("fk_management_processes_process_type_id_management_process_types"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_management_processes")),
    )
    for column in [
        "internal_reference",
        "status",
        "phase",
        "priority",
        "plate",
        "document_reference",
        "customer_name",
        "driver_name",
        "pending_reason",
        "opened_on",
        "sla_due_on",
        "closed_at",
    ]:
        op.create_index(op.f(f"ix_management_processes_{column}"), "management_processes", [column], unique=column == "internal_reference")

    op.create_table(
        "claim_incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("sin_reference", sa.String(length=80), nullable=False),
        sa.Column("accident_date", sa.Date(), nullable=True),
        sa.Column("plate", sa.String(length=40), nullable=True),
        sa.Column("operational_status", sa.String(length=80), nullable=False),
        sa.Column("rentway_status", sa.String(length=120), nullable=True),
        sa.Column("has_missing_ar", sa.Boolean(), nullable=False),
        sa.Column("has_missing_minimum_data", sa.Boolean(), nullable=False),
        sa.Column("components_json", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["management_processes.id"], name=op.f("fk_claim_incidents_process_id_management_processes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_incidents")),
    )
    for column in ["process_id", "sin_reference", "accident_date", "plate", "operational_status", "rentway_status", "has_missing_ar", "has_missing_minimum_data"]:
        op.create_index(op.f(f"ix_claim_incidents_{column}"), "claim_incidents", [column], unique=column in {"process_id", "sin_reference"})

    op.create_table(
        "claim_rentway_ars",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ar_reference", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=120), nullable=True),
        sa.Column("raw_state", sa.String(length=120), nullable=True),
        sa.Column("request_date", sa.Date(), nullable=True),
        sa.Column("plate", sa.String(length=40), nullable=True),
        sa.Column("vehicle_reference", sa.String(length=120), nullable=True),
        sa.Column("driver_name", sa.String(length=200), nullable=True),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("ra_reference", sa.String(length=120), nullable=True),
        sa.Column("impro_reference", sa.String(length=120), nullable=True),
        sa.Column("daaa_reference", sa.String(length=120), nullable=True),
        sa.Column("insurance_policy", sa.String(length=160), nullable=True),
        sa.Column("rental_station_out", sa.String(length=160), nullable=True),
        sa.Column("created_by_rental_station", sa.String(length=160), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_rentway_ars")),
    )
    for column in ["ar_reference", "status", "raw_state", "request_date", "plate", "vehicle_reference", "driver_name", "customer_name", "ra_reference", "impro_reference", "daaa_reference", "insurance_policy", "rental_station_out", "created_by_rental_station", "source_file"]:
        op.create_index(op.f(f"ix_claim_rentway_ars_{column}"), "claim_rentway_ars", [column], unique=False)

    op.create_table(
        "claim_refstro_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("refstro_reference", sa.String(length=160), nullable=True),
        sa.Column("document_reference", sa.String(length=160), nullable=True),
        sa.Column("plate", sa.String(length=40), nullable=True),
        sa.Column("accident_date", sa.Date(), nullable=True),
        sa.Column("component", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=120), nullable=True),
        sa.Column("close_date", sa.Date(), nullable=True),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("driver_name", sa.String(length=200), nullable=True),
        sa.Column("claim_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("cost_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("source_file", sa.String(length=255), nullable=True),
        sa.Column("source_row_number", sa.Integer(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_claim_refstro_lines")),
    )
    for column in ["refstro_reference", "document_reference", "plate", "accident_date", "component", "status", "close_date", "customer_name", "driver_name", "source_file"]:
        op.create_index(op.f(f"ix_claim_refstro_lines_{column}"), "claim_refstro_lines", [column], unique=False)

    op.create_table(
        "management_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_type_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["process_type_id"], ["management_process_types.id"], name=op.f("fk_management_rules_process_type_id_management_process_types")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_management_rules")),
    )
    op.create_index(op.f("ix_management_rules_code"), "management_rules", ["code"], unique=False)
    op.create_index(op.f("ix_management_rules_severity"), "management_rules", ["severity"], unique=False)
    op.create_index(op.f("ix_management_rules_active"), "management_rules", ["active"], unique=False)

    op.create_table(
        "management_process_associations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("association_role", sa.String(length=80), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("ended_by_id", sa.Integer(), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_management_process_associations_created_by_id_users")),
        sa.ForeignKeyConstraint(["ended_by_id"], ["users.id"], name=op.f("fk_management_process_associations_ended_by_id_users")),
        sa.ForeignKeyConstraint(["process_id"], ["management_processes.id"], name=op.f("fk_management_process_associations_process_id_management_processes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_management_process_associations")),
    )
    for column in ["process_id", "entity_type", "entity_id", "association_role", "active", "ended_at"]:
        op.create_index(op.f(f"ix_management_process_associations_{column}"), "management_process_associations", [column], unique=False)

    op.create_table(
        "management_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=220), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("completed_by_id", sa.Integer(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"], name=op.f("fk_management_actions_completed_by_id_users")),
        sa.ForeignKeyConstraint(["process_id"], ["management_processes.id"], name=op.f("fk_management_actions_process_id_management_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_id"], ["management_rules.id"], name=op.f("fk_management_actions_rule_id_management_rules")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_management_actions")),
    )
    for column in ["process_id", "status", "mandatory", "due_on", "completed_at"]:
        op.create_index(op.f(f"ix_management_actions_{column}"), "management_actions", [column], unique=False)

    op.create_table(
        "management_evidences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_management_evidences_created_by_id_users")),
        sa.ForeignKeyConstraint(["process_id"], ["management_processes.id"], name=op.f("fk_management_evidences_process_id_management_processes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_management_evidences")),
    )
    op.create_index(op.f("ix_management_evidences_process_id"), "management_evidences", ["process_id"], unique=False)
    op.create_index(op.f("ix_management_evidences_evidence_type"), "management_evidences", ["evidence_type"], unique=False)

    op.create_table(
        "management_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=120), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["management_processes.id"], name=op.f("fk_management_history_process_id_management_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_management_history_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_management_history")),
    )
    for column in ["process_id", "action", "entity_type", "entity_id"]:
        op.create_index(op.f(f"ix_management_history_{column}"), "management_history", [column], unique=False)


def downgrade() -> None:
    for column in ["process_id", "action", "entity_type", "entity_id"]:
        op.drop_index(op.f(f"ix_management_history_{column}"), table_name="management_history")
    op.drop_table("management_history")
    op.drop_index(op.f("ix_management_evidences_evidence_type"), table_name="management_evidences")
    op.drop_index(op.f("ix_management_evidences_process_id"), table_name="management_evidences")
    op.drop_table("management_evidences")
    for column in ["process_id", "status", "mandatory", "due_on", "completed_at"]:
        op.drop_index(op.f(f"ix_management_actions_{column}"), table_name="management_actions")
    op.drop_table("management_actions")
    for column in ["process_id", "entity_type", "entity_id", "association_role", "active", "ended_at"]:
        op.drop_index(op.f(f"ix_management_process_associations_{column}"), table_name="management_process_associations")
    op.drop_table("management_process_associations")
    op.drop_index(op.f("ix_management_rules_active"), table_name="management_rules")
    op.drop_index(op.f("ix_management_rules_severity"), table_name="management_rules")
    op.drop_index(op.f("ix_management_rules_code"), table_name="management_rules")
    op.drop_table("management_rules")
    for column in ["refstro_reference", "document_reference", "plate", "accident_date", "component", "status", "close_date", "customer_name", "driver_name", "source_file"]:
        op.drop_index(op.f(f"ix_claim_refstro_lines_{column}"), table_name="claim_refstro_lines")
    op.drop_table("claim_refstro_lines")
    for column in ["ar_reference", "status", "raw_state", "request_date", "plate", "vehicle_reference", "driver_name", "customer_name", "ra_reference", "impro_reference", "daaa_reference", "insurance_policy", "rental_station_out", "created_by_rental_station", "source_file"]:
        op.drop_index(op.f(f"ix_claim_rentway_ars_{column}"), table_name="claim_rentway_ars")
    op.drop_table("claim_rentway_ars")
    for column in ["process_id", "sin_reference", "accident_date", "plate", "operational_status", "rentway_status", "has_missing_ar", "has_missing_minimum_data"]:
        op.drop_index(op.f(f"ix_claim_incidents_{column}"), table_name="claim_incidents")
    op.drop_table("claim_incidents")
    for column in ["internal_reference", "status", "phase", "priority", "plate", "document_reference", "customer_name", "driver_name", "pending_reason", "opened_on", "sla_due_on", "closed_at"]:
        op.drop_index(op.f(f"ix_management_processes_{column}"), table_name="management_processes")
    op.drop_table("management_processes")
    op.drop_index(op.f("ix_management_process_types_active"), table_name="management_process_types")
    op.drop_index(op.f("ix_management_process_types_code"), table_name="management_process_types")
    op.drop_table("management_process_types")
