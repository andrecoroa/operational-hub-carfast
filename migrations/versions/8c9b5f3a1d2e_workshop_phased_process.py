# ruff: noqa: E501
"""Add phased workshop process tables."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8c9b5f3a1d2e"
down_revision: str | Sequence[str] | None = "ff6e7f8a9b0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "workshop_phased_processes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("creation_mode", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("plate_snapshot", sa.String(length=40), nullable=True),
        sa.Column("current_phase_code", sa.String(length=120), nullable=True),
        sa.Column("priority", sa.String(length=80), nullable=False),
        sa.Column("origin", sa.String(length=120), nullable=True),
        sa.Column("origin_detail", sa.Text(), nullable=True),
        sa.Column("initial_km", sa.Integer(), nullable=True),
        sa.Column("initial_observation", sa.Text(), nullable=True),
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("process_type", "title", "creation_mode", "status", "plate_snapshot", "current_phase_code", "priority", "origin"):
        op.create_index(op.f(f"ix_workshop_phased_processes_{column}"), "workshop_phased_processes", [column])

    op.create_table(
        "workshop_phased_process_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("service_code", sa.String(length=120), nullable=False),
        sa.Column("service_label", sa.String(length=160), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("zone", sa.String(length=120), nullable=True),
        sa.Column("short_observation", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workshop_phased_process_services_service_code"), "workshop_phased_process_services", ["service_code"])
    op.create_index(op.f("ix_workshop_phased_process_services_zone"), "workshop_phased_process_services", ["zone"])

    op.create_table(
        "workshop_phased_process_phases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("phase_code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by_id", sa.Integer(), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["completed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workshop_phased_process_phases_phase_code"), "workshop_phased_process_phases", ["phase_code"])
    op.create_index(op.f("ix_workshop_phased_process_phases_status"), "workshop_phased_process_phases", ["status"])

    op.create_table(
        "workshop_phased_process_alerts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=True),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("message", sa.String(length=240), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["phase_id"], ["workshop_phased_process_phases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("code", "severity", "source", "status"):
        op.create_index(op.f(f"ix_workshop_phased_process_alerts_{column}"), "workshop_phased_process_alerts", [column])

    op.create_table(
        "workshop_phased_technical_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=True),
        sa.Column("report_code", sa.String(length=120), nullable=False),
        sa.Column("report_name", sa.String(length=180), nullable=False),
        sa.Column("reading_origin", sa.String(length=80), nullable=False),
        sa.Column("reading_origin_detail", sa.Text(), nullable=True),
        sa.Column("report_moment", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("original_document_id", sa.Integer(), nullable=True),
        sa.Column("original_link", sa.Text(), nullable=True),
        sa.Column("raw_values_json", sa.JSON(), nullable=True),
        sa.Column("extracted_values_json", sa.JSON(), nullable=True),
        sa.Column("validated_values_json", sa.JSON(), nullable=True),
        sa.Column("correction_json", sa.JSON(), nullable=True),
        sa.Column("added_by_id", sa.Integer(), nullable=True),
        sa.Column("validated_by_id", sa.Integer(), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["original_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["phase_id"], ["workshop_phased_process_phases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["validated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("reading_origin", "report_code", "report_moment", "status"):
        op.create_index(op.f(f"ix_workshop_phased_technical_reports_{column}"), "workshop_phased_technical_reports", [column])

    op.create_table(
        "workshop_phased_technical_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=True),
        sa.Column("check_code", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("evidence_document_id", sa.Integer(), nullable=True),
        sa.Column("evidence_link", sa.Text(), nullable=True),
        sa.Column("creates_task", sa.Boolean(), nullable=False),
        sa.Column("potential_customer_charge", sa.Boolean(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("incident_id", sa.Integer(), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["evidence_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["phase_id"], ["workshop_phased_process_phases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workshop_phased_technical_checks_check_code"), "workshop_phased_technical_checks", ["check_code"])
    op.create_index(op.f("ix_workshop_phased_technical_checks_status"), "workshop_phased_technical_checks", ["status"])

    op.create_table(
        "workshop_phased_technical_incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=True),
        sa.Column("report_id", sa.Integer(), nullable=True),
        sa.Column("check_id", sa.Integer(), nullable=True),
        sa.Column("related_field", sa.String(length=160), nullable=True),
        sa.Column("incident_type", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(length=40), nullable=False),
        sa.Column("recommended_action", sa.String(length=160), nullable=True),
        sa.Column("vehicle_can_circulate", sa.String(length=80), nullable=True),
        sa.Column("evidence_document_id", sa.Integer(), nullable=True),
        sa.Column("evidence_link", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["check_id"], ["workshop_phased_technical_checks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["evidence_document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["phase_id"], ["workshop_phased_process_phases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["report_id"], ["workshop_phased_technical_reports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("incident_type", "related_field", "recommended_action", "severity", "status", "vehicle_can_circulate"):
        op.create_index(op.f(f"ix_workshop_phased_technical_incidents_{column}"), "workshop_phased_technical_incidents", [column])

    op.create_table(
        "workshop_phased_closure_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("check_code", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workshop_phased_closure_checks_check_code"), "workshop_phased_closure_checks", ["check_code"])
    op.create_index(op.f("ix_workshop_phased_closure_checks_status"), "workshop_phased_closure_checks", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_workshop_phased_closure_checks_status"), table_name="workshop_phased_closure_checks")
    op.drop_index(op.f("ix_workshop_phased_closure_checks_check_code"), table_name="workshop_phased_closure_checks")
    op.drop_table("workshop_phased_closure_checks")
    for column in ("vehicle_can_circulate", "status", "severity", "recommended_action", "related_field", "incident_type"):
        op.drop_index(op.f(f"ix_workshop_phased_technical_incidents_{column}"), table_name="workshop_phased_technical_incidents")
    op.drop_table("workshop_phased_technical_incidents")
    op.drop_index(op.f("ix_workshop_phased_technical_checks_status"), table_name="workshop_phased_technical_checks")
    op.drop_index(op.f("ix_workshop_phased_technical_checks_check_code"), table_name="workshop_phased_technical_checks")
    op.drop_table("workshop_phased_technical_checks")
    for column in ("status", "report_moment", "report_code", "reading_origin"):
        op.drop_index(op.f(f"ix_workshop_phased_technical_reports_{column}"), table_name="workshop_phased_technical_reports")
    op.drop_table("workshop_phased_technical_reports")
    for column in ("status", "source", "severity", "code"):
        op.drop_index(op.f(f"ix_workshop_phased_process_alerts_{column}"), table_name="workshop_phased_process_alerts")
    op.drop_table("workshop_phased_process_alerts")
    op.drop_index(op.f("ix_workshop_phased_process_phases_status"), table_name="workshop_phased_process_phases")
    op.drop_index(op.f("ix_workshop_phased_process_phases_phase_code"), table_name="workshop_phased_process_phases")
    op.drop_table("workshop_phased_process_phases")
    op.drop_index(op.f("ix_workshop_phased_process_services_zone"), table_name="workshop_phased_process_services")
    op.drop_index(op.f("ix_workshop_phased_process_services_service_code"), table_name="workshop_phased_process_services")
    op.drop_table("workshop_phased_process_services")
    for column in ("origin", "priority", "current_phase_code", "plate_snapshot", "status", "creation_mode", "title", "process_type"):
        op.drop_index(op.f(f"ix_workshop_phased_processes_{column}"), table_name="workshop_phased_processes")
    op.drop_table("workshop_phased_processes")
