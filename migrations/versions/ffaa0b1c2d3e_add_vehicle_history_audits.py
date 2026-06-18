"""Add vehicle history audit pilot."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffaa0b1c2d3e"
down_revision: str | Sequence[str] | None = "ff9b0c1d2e3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_history_audits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("management_process_id", sa.Integer(), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("plate", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("phase", sa.String(length=120), nullable=False),
        sa.Column("responsible_user_id", sa.Integer(), nullable=True),
        sa.Column("priority", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["management_process_id"], ["management_processes.id"], name=op.f("fk_vehicle_history_audits_management_process_id_management_processes")),
        sa.ForeignKeyConstraint(["responsible_user_id"], ["users.id"], name=op.f("fk_vehicle_history_audits_responsible_user_id_users")),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name=op.f("fk_vehicle_history_audits_vehicle_id_vehicles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_history_audits")),
    )
    for column in ["vehicle_id", "plate", "status", "phase", "priority", "confidence_level", "opened_at", "closed_at"]:
        op.create_index(op.f(f"ix_vehicle_history_audits_{column}"), "vehicle_history_audits", [column], unique=False)

    op.create_table(
        "vehicle_history_audit_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("plate", sa.String(length=40), nullable=False),
        sa.Column("document_type", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("moment", sa.String(length=80), nullable=False),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column("extraction_status", sa.String(length=80), nullable=False),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["vehicle_history_audits.id"], name=op.f("fk_vehicle_history_audit_documents_audit_id_vehicle_history_audits"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_vehicle_history_audit_documents_document_id_documents"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_history_audit_documents")),
    )
    for column in ["audit_id", "plate", "document_type", "source", "moment", "extraction_status", "confidence_level"]:
        op.create_index(op.f(f"ix_vehicle_history_audit_documents_{column}"), "vehicle_history_audit_documents", [column], unique=False)

    op.create_table(
        "vehicle_history_audit_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=True),
        sa.Column("km", sa.Integer(), nullable=True),
        sa.Column("supplier", sa.String(length=200), nullable=True),
        sa.Column("family", sa.String(length=80), nullable=False),
        sa.Column("subtype", sa.String(length=160), nullable=True),
        sa.Column("quantity", sa.String(length=80), nullable=True),
        sa.Column("axle", sa.String(length=80), nullable=True),
        sa.Column("side", sa.String(length=80), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["vehicle_history_audits.id"], name=op.f("fk_vehicle_history_audit_services_audit_id_vehicle_history_audits"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_vehicle_history_audit_services_document_id_documents"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_history_audit_services")),
    )
    for column in ["audit_id", "service_date", "km", "supplier", "family", "subtype", "confidence_level"]:
        op.create_index(op.f(f"ix_vehicle_history_audit_services_{column}"), "vehicle_history_audit_services", [column], unique=False)

    op.create_table(
        "vehicle_history_audit_issues",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("issue_type", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("administrative_source", sa.Text(), nullable=True),
        sa.Column("technical_source", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("recommended_action", sa.Text(), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["vehicle_history_audits.id"], name=op.f("fk_vehicle_history_audit_issues_audit_id_vehicle_history_audits"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_history_audit_issues")),
    )
    for column in ["audit_id", "issue_type", "severity", "status"]:
        op.create_index(op.f(f"ix_vehicle_history_audit_issues_{column}"), "vehicle_history_audit_issues", [column], unique=False)

    op.create_table(
        "vehicle_history_audit_truths",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("assumed_start_date", sa.Date(), nullable=True),
        sa.Column("last_reliable_km", sa.Integer(), nullable=True),
        sa.Column("last_valid_maintenance", sa.Text(), nullable=True),
        sa.Column("estimated_maintenance_count", sa.Integer(), nullable=True),
        sa.Column("bsi_status", sa.String(length=160), nullable=True),
        sa.Column("telecharge_status", sa.String(length=160), nullable=True),
        sa.Column("assumed_version", sa.String(length=200), nullable=True),
        sa.Column("plan_to_follow", sa.Text(), nullable=True),
        sa.Column("pending_items", sa.Text(), nullable=True),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["vehicle_history_audits.id"], name=op.f("fk_vehicle_history_audit_truths_audit_id_vehicle_history_audits"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_history_audit_truths")),
        sa.UniqueConstraint("audit_id", name=op.f("uq_vehicle_history_audit_truths_audit_id")),
    )
    op.create_index(op.f("ix_vehicle_history_audit_truths_confidence_level"), "vehicle_history_audit_truths", ["confidence_level"], unique=False)

    op.create_table(
        "vehicle_history_audit_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("rule_type", sa.String(length=80), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False),
        sa.Column("applies_when", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["audit_id"], ["vehicle_history_audits.id"], name=op.f("fk_vehicle_history_audit_rules_audit_id_vehicle_history_audits"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_history_audit_rules")),
    )
    for column in ["audit_id", "rule_type", "mandatory", "status"]:
        op.create_index(op.f(f"ix_vehicle_history_audit_rules_{column}"), "vehicle_history_audit_rules", [column], unique=False)


def downgrade() -> None:
    op.drop_table("vehicle_history_audit_rules")
    op.drop_table("vehicle_history_audit_truths")
    op.drop_table("vehicle_history_audit_issues")
    op.drop_table("vehicle_history_audit_services")
    op.drop_table("vehicle_history_audit_documents")
    op.drop_table("vehicle_history_audits")
