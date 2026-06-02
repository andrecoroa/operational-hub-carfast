"""add document incident foundation

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-05-12 03:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("incident_type", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("severity", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("workshop_process_id", sa.Integer(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("plate", sa.String(length=40), nullable=True),
        sa.Column("station", sa.String(length=120), nullable=True),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.String(length=120), nullable=True),
        sa.Column("action_taken", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], name=op.f("fk_incidents_assigned_to_id_users")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_incidents_created_by_id_users")),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_incidents_task_id_tasks")),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name=op.f("fk_incidents_vehicle_id_vehicles")),
        sa.ForeignKeyConstraint(
            ["workshop_process_id"],
            ["workshop_processes.id"],
            name=op.f("fk_incidents_workshop_process_id_workshop_processes"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incidents")),
    )
    op.create_index(op.f("ix_incidents_category"), "incidents", ["category"], unique=False)
    op.create_index(op.f("ix_incidents_decision"), "incidents", ["decision"], unique=False)
    op.create_index(op.f("ix_incidents_incident_type"), "incidents", ["incident_type"], unique=False)
    op.create_index(op.f("ix_incidents_occurred_at"), "incidents", ["occurred_at"], unique=False)
    op.create_index(op.f("ix_incidents_plate"), "incidents", ["plate"], unique=False)
    op.create_index(op.f("ix_incidents_severity"), "incidents", ["severity"], unique=False)
    op.create_index(op.f("ix_incidents_source"), "incidents", ["source"], unique=False)
    op.create_index(op.f("ix_incidents_station"), "incidents", ["station"], unique=False)
    op.create_index(op.f("ix_incidents_status"), "incidents", ["status"], unique=False)
    op.create_index(op.f("ix_incidents_task_id"), "incidents", ["task_id"], unique=False)
    op.create_index(op.f("ix_incidents_vehicle_id"), "incidents", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_incidents_workshop_process_id"), "incidents", ["workshop_process_id"], unique=False)

    op.add_column("documents", sa.Column("title", sa.String(length=200), nullable=True))
    op.add_column("documents", sa.Column("document_type", sa.String(length=80), nullable=True))
    op.add_column("documents", sa.Column("classification", sa.String(length=120), nullable=True))
    op.add_column("documents", sa.Column("source", sa.String(length=80), nullable=True))
    op.add_column("documents", sa.Column("storage_key", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("folder_path", sa.Text(), nullable=True))
    op.add_column("documents", sa.Column("status", sa.String(length=40), server_default="received", nullable=False))
    op.add_column("documents", sa.Column("confidentiality_level", sa.String(length=40), nullable=True))
    op.add_column("documents", sa.Column("retention_policy", sa.String(length=80), nullable=True))
    op.add_column("documents", sa.Column("file_hash", sa.String(length=128), nullable=True))
    op.add_column("documents", sa.Column("vehicle_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("task_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("workshop_process_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("incident_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("plate", sa.String(length=40), nullable=True))
    op.add_column("documents", sa.Column("customer_name", sa.String(length=200), nullable=True))
    op.add_column("documents", sa.Column("supplier_name", sa.String(length=200), nullable=True))
    op.add_column("documents", sa.Column("reservation_number", sa.String(length=120), nullable=True))
    op.add_column("documents", sa.Column("contract_number", sa.String(length=120), nullable=True))
    op.add_column("documents", sa.Column("document_date", sa.Date(), nullable=True))
    op.add_column("documents", sa.Column("archived_by_id", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_documents_classification"), "documents", ["classification"], unique=False)
    op.create_index(op.f("ix_documents_confidentiality_level"), "documents", ["confidentiality_level"], unique=False)
    op.create_index(op.f("ix_documents_contract_number"), "documents", ["contract_number"], unique=False)
    op.create_index(op.f("ix_documents_customer_name"), "documents", ["customer_name"], unique=False)
    op.create_index(op.f("ix_documents_document_date"), "documents", ["document_date"], unique=False)
    op.create_index(op.f("ix_documents_document_type"), "documents", ["document_type"], unique=False)
    op.create_index(op.f("ix_documents_file_hash"), "documents", ["file_hash"], unique=False)
    op.create_index(op.f("ix_documents_plate"), "documents", ["plate"], unique=False)
    op.create_index(op.f("ix_documents_reservation_number"), "documents", ["reservation_number"], unique=False)
    op.create_index(op.f("ix_documents_source"), "documents", ["source"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)
    op.create_index(op.f("ix_documents_supplier_name"), "documents", ["supplier_name"], unique=False)
    op.create_index(op.f("ix_documents_title"), "documents", ["title"], unique=False)
    op.create_foreign_key(op.f("fk_documents_archived_by_id_users"), "documents", "users", ["archived_by_id"], ["id"])
    op.create_foreign_key(op.f("fk_documents_incident_id_incidents"), "documents", "incidents", ["incident_id"], ["id"])
    op.create_foreign_key(op.f("fk_documents_task_id_tasks"), "documents", "tasks", ["task_id"], ["id"])
    op.create_foreign_key(op.f("fk_documents_vehicle_id_vehicles"), "documents", "vehicles", ["vehicle_id"], ["id"])
    op.create_foreign_key(
        op.f("fk_documents_workshop_process_id_workshop_processes"),
        "documents",
        "workshop_processes",
        ["workshop_process_id"],
        ["id"],
    )

    op.create_table(
        "document_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_document_events_document_id_documents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_document_events_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_events")),
    )
    op.create_index(op.f("ix_document_events_action"), "document_events", ["action"], unique=False)
    op.create_index(op.f("ix_document_events_document_id"), "document_events", ["document_id"], unique=False)

    op.create_table(
        "incident_evidences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("storage_provider", sa.String(length=80), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_incident_evidences_document_id_documents")),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], name=op.f("fk_incident_evidences_incident_id_incidents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_incident_evidences_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_evidences")),
    )
    op.create_index(op.f("ix_incident_evidences_evidence_type"), "incident_evidences", ["evidence_type"], unique=False)
    op.create_index(op.f("ix_incident_evidences_incident_id"), "incident_evidences", ["incident_id"], unique=False)

    op.create_table(
        "incident_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("incident_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["incident_id"], ["incidents.id"], name=op.f("fk_incident_events_incident_id_incidents"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_incident_events_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_events")),
    )
    op.create_index(op.f("ix_incident_events_action"), "incident_events", ["action"], unique=False)
    op.create_index(op.f("ix_incident_events_incident_id"), "incident_events", ["incident_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_incident_events_incident_id"), table_name="incident_events")
    op.drop_index(op.f("ix_incident_events_action"), table_name="incident_events")
    op.drop_table("incident_events")
    op.drop_index(op.f("ix_incident_evidences_incident_id"), table_name="incident_evidences")
    op.drop_index(op.f("ix_incident_evidences_evidence_type"), table_name="incident_evidences")
    op.drop_table("incident_evidences")
    op.drop_index(op.f("ix_document_events_document_id"), table_name="document_events")
    op.drop_index(op.f("ix_document_events_action"), table_name="document_events")
    op.drop_table("document_events")

    for name in [
        "fk_documents_workshop_process_id_workshop_processes",
        "fk_documents_vehicle_id_vehicles",
        "fk_documents_task_id_tasks",
        "fk_documents_incident_id_incidents",
        "fk_documents_archived_by_id_users",
    ]:
        op.drop_constraint(op.f(name), "documents", type_="foreignkey")
    for name in [
        "ix_documents_title",
        "ix_documents_supplier_name",
        "ix_documents_status",
        "ix_documents_source",
        "ix_documents_reservation_number",
        "ix_documents_plate",
        "ix_documents_file_hash",
        "ix_documents_document_type",
        "ix_documents_document_date",
        "ix_documents_customer_name",
        "ix_documents_contract_number",
        "ix_documents_confidentiality_level",
        "ix_documents_classification",
    ]:
        op.drop_index(op.f(name), table_name="documents")
    for column in [
        "archived_at",
        "archived_by_id",
        "document_date",
        "contract_number",
        "reservation_number",
        "supplier_name",
        "customer_name",
        "plate",
        "incident_id",
        "workshop_process_id",
        "task_id",
        "vehicle_id",
        "file_hash",
        "retention_policy",
        "confidentiality_level",
        "status",
        "folder_path",
        "storage_key",
        "source",
        "classification",
        "document_type",
        "title",
    ]:
        op.drop_column("documents", column)

    op.drop_index(op.f("ix_incidents_workshop_process_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_vehicle_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_task_id"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_status"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_station"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_source"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_severity"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_plate"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_occurred_at"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_incident_type"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_decision"), table_name="incidents")
    op.drop_index(op.f("ix_incidents_category"), table_name="incidents")
    op.drop_table("incidents")
