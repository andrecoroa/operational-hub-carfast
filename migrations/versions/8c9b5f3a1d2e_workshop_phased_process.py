"""workshop phased process

Revision ID: 8c9b5f3a1d2e
Revises: 4eaddbe5f0a7
Create Date: 2026-06-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8c9b5f3a1d2e"
down_revision = "4eaddbe5f0a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workshop_processes",
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_workshop_processes_created_by_id_users")),
        sa.ForeignKeyConstraint(
            ["responsible_user_id"],
            ["users.id"],
            name=op.f("fk_workshop_processes_responsible_user_id_users"),
        ),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name=op.f("fk_workshop_processes_vehicle_id_vehicles")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_processes")),
    )
    op.create_index(op.f("ix_workshop_processes_creation_mode"), "workshop_processes", ["creation_mode"])
    op.create_index(op.f("ix_workshop_processes_current_phase_code"), "workshop_processes", ["current_phase_code"])
    op.create_index(op.f("ix_workshop_processes_origin"), "workshop_processes", ["origin"])
    op.create_index(op.f("ix_workshop_processes_plate_snapshot"), "workshop_processes", ["plate_snapshot"])
    op.create_index(op.f("ix_workshop_processes_priority"), "workshop_processes", ["priority"])
    op.create_index(op.f("ix_workshop_processes_process_type"), "workshop_processes", ["process_type"])
    op.create_index(op.f("ix_workshop_processes_status"), "workshop_processes", ["status"])
    op.create_index(op.f("ix_workshop_processes_title"), "workshop_processes", ["title"])

    op.create_table(
        "workshop_process_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("service_code", sa.String(length=120), nullable=False),
        sa.Column("service_label", sa.String(length=160), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("zone", sa.String(length=120), nullable=True),
        sa.Column("short_observation", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_workshop_process_services_process_id_workshop_processes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_process_services")),
    )
    op.create_index(op.f("ix_workshop_process_services_service_code"), "workshop_process_services", ["service_code"])
    op.create_index(op.f("ix_workshop_process_services_zone"), "workshop_process_services", ["zone"])

    op.create_table(
        "workshop_process_phases",
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["completed_by_id"], ["users.id"], name=op.f("fk_workshop_process_phases_completed_by_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_workshop_process_phases_process_id_workshop_processes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_process_phases")),
    )
    op.create_index(op.f("ix_workshop_process_phases_phase_code"), "workshop_process_phases", ["phase_code"])
    op.create_index(op.f("ix_workshop_process_phases_status"), "workshop_process_phases", ["status"])

    op.create_table(
        "workshop_process_alerts",
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["phase_id"],
            ["workshop_process_phases.id"],
            name=op.f("fk_workshop_process_alerts_phase_id_workshop_process_phases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_workshop_process_alerts_process_id_workshop_processes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"], ["users.id"], name=op.f("fk_workshop_process_alerts_resolved_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_process_alerts")),
    )
    op.create_index(op.f("ix_workshop_process_alerts_code"), "workshop_process_alerts", ["code"])
    op.create_index(op.f("ix_workshop_process_alerts_severity"), "workshop_process_alerts", ["severity"])
    op.create_index(op.f("ix_workshop_process_alerts_source"), "workshop_process_alerts", ["source"])
    op.create_index(op.f("ix_workshop_process_alerts_status"), "workshop_process_alerts", ["status"])

    op.create_table(
        "workshop_technical_reports",
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
        sa.Column(
            "added_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observations", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["added_by_id"], ["users.id"], name=op.f("fk_workshop_technical_reports_added_by_id_users")),
        sa.ForeignKeyConstraint(
            ["original_document_id"], ["documents.id"], name=op.f("fk_workshop_technical_reports_original_document_id_documents")
        ),
        sa.ForeignKeyConstraint(
            ["phase_id"],
            ["workshop_process_phases.id"],
            name=op.f("fk_workshop_technical_reports_phase_id_workshop_process_phases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_workshop_technical_reports_process_id_workshop_processes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["validated_by_id"], ["users.id"], name=op.f("fk_workshop_technical_reports_validated_by_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_technical_reports")),
    )
    op.create_index(op.f("ix_workshop_technical_reports_reading_origin"), "workshop_technical_reports", ["reading_origin"])
    op.create_index(op.f("ix_workshop_technical_reports_report_code"), "workshop_technical_reports", ["report_code"])
    op.create_index(op.f("ix_workshop_technical_reports_report_moment"), "workshop_technical_reports", ["report_moment"])
    op.create_index(op.f("ix_workshop_technical_reports_status"), "workshop_technical_reports", ["status"])

    op.create_table(
        "workshop_technical_checks",
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_document_id"], ["documents.id"], name=op.f("fk_workshop_technical_checks_evidence_document_id_documents")
        ),
        sa.ForeignKeyConstraint(
            ["phase_id"],
            ["workshop_process_phases.id"],
            name=op.f("fk_workshop_technical_checks_phase_id_workshop_process_phases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_workshop_technical_checks_process_id_workshop_processes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_workshop_technical_checks_task_id_tasks")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_technical_checks")),
    )
    op.create_index(op.f("ix_workshop_technical_checks_check_code"), "workshop_technical_checks", ["check_code"])
    op.create_index(op.f("ix_workshop_technical_checks_status"), "workshop_technical_checks", ["status"])

    op.create_table(
        "workshop_technical_incidents",
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_workshop_technical_incidents_created_by_id_users")),
        sa.ForeignKeyConstraint(
            ["evidence_document_id"], ["documents.id"], name=op.f("fk_workshop_technical_incidents_evidence_document_id_documents")
        ),
        sa.ForeignKeyConstraint(
            ["phase_id"],
            ["workshop_process_phases.id"],
            name=op.f("fk_workshop_technical_incidents_phase_id_workshop_process_phases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_workshop_technical_incidents_process_id_workshop_processes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["workshop_technical_reports.id"],
            name=op.f("fk_workshop_technical_incidents_report_id_workshop_technical_reports"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["check_id"],
            ["workshop_technical_checks.id"],
            name=op.f("fk_workshop_technical_incidents_check_id_workshop_technical_checks"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_technical_incidents")),
    )
    op.create_index(op.f("ix_workshop_technical_incidents_incident_type"), "workshop_technical_incidents", ["incident_type"])
    op.create_index(op.f("ix_workshop_technical_incidents_related_field"), "workshop_technical_incidents", ["related_field"])
    op.create_index(op.f("ix_workshop_technical_incidents_recommended_action"), "workshop_technical_incidents", ["recommended_action"])
    op.create_index(op.f("ix_workshop_technical_incidents_severity"), "workshop_technical_incidents", ["severity"])
    op.create_index(op.f("ix_workshop_technical_incidents_status"), "workshop_technical_incidents", ["status"])
    op.create_index(op.f("ix_workshop_technical_incidents_vehicle_can_circulate"), "workshop_technical_incidents", ["vehicle_can_circulate"])

    op.create_table(
        "workshop_closure_checks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("check_code", sa.String(length=120), nullable=False),
        sa.Column("label", sa.String(length=180), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_workshop_closure_checks_process_id_workshop_processes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["responsible_user_id"], ["users.id"], name=op.f("fk_workshop_closure_checks_responsible_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_closure_checks")),
    )
    op.create_index(op.f("ix_workshop_closure_checks_check_code"), "workshop_closure_checks", ["check_code"])
    op.create_index(op.f("ix_workshop_closure_checks_status"), "workshop_closure_checks", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_workshop_closure_checks_status"), table_name="workshop_closure_checks")
    op.drop_index(op.f("ix_workshop_closure_checks_check_code"), table_name="workshop_closure_checks")
    op.drop_table("workshop_closure_checks")
    op.drop_index(op.f("ix_workshop_technical_incidents_vehicle_can_circulate"), table_name="workshop_technical_incidents")
    op.drop_index(op.f("ix_workshop_technical_incidents_status"), table_name="workshop_technical_incidents")
    op.drop_index(op.f("ix_workshop_technical_incidents_severity"), table_name="workshop_technical_incidents")
    op.drop_index(op.f("ix_workshop_technical_incidents_recommended_action"), table_name="workshop_technical_incidents")
    op.drop_index(op.f("ix_workshop_technical_incidents_related_field"), table_name="workshop_technical_incidents")
    op.drop_index(op.f("ix_workshop_technical_incidents_incident_type"), table_name="workshop_technical_incidents")
    op.drop_table("workshop_technical_incidents")
    op.drop_index(op.f("ix_workshop_technical_checks_status"), table_name="workshop_technical_checks")
    op.drop_index(op.f("ix_workshop_technical_checks_check_code"), table_name="workshop_technical_checks")
    op.drop_table("workshop_technical_checks")
    op.drop_index(op.f("ix_workshop_technical_reports_status"), table_name="workshop_technical_reports")
    op.drop_index(op.f("ix_workshop_technical_reports_report_moment"), table_name="workshop_technical_reports")
    op.drop_index(op.f("ix_workshop_technical_reports_report_code"), table_name="workshop_technical_reports")
    op.drop_index(op.f("ix_workshop_technical_reports_reading_origin"), table_name="workshop_technical_reports")
    op.drop_table("workshop_technical_reports")
    op.drop_index(op.f("ix_workshop_process_alerts_status"), table_name="workshop_process_alerts")
    op.drop_index(op.f("ix_workshop_process_alerts_source"), table_name="workshop_process_alerts")
    op.drop_index(op.f("ix_workshop_process_alerts_severity"), table_name="workshop_process_alerts")
    op.drop_index(op.f("ix_workshop_process_alerts_code"), table_name="workshop_process_alerts")
    op.drop_table("workshop_process_alerts")
    op.drop_index(op.f("ix_workshop_process_phases_status"), table_name="workshop_process_phases")
    op.drop_index(op.f("ix_workshop_process_phases_phase_code"), table_name="workshop_process_phases")
    op.drop_table("workshop_process_phases")
    op.drop_index(op.f("ix_workshop_process_services_zone"), table_name="workshop_process_services")
    op.drop_index(op.f("ix_workshop_process_services_service_code"), table_name="workshop_process_services")
    op.drop_table("workshop_process_services")
    op.drop_index(op.f("ix_workshop_processes_title"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_status"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_process_type"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_priority"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_plate_snapshot"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_origin"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_current_phase_code"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_creation_mode"), table_name="workshop_processes")
    op.drop_table("workshop_processes")
