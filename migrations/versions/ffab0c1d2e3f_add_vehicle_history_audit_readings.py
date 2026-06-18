"""Add vehicle history audit extracted readings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffab0c1d2e3f"
down_revision: str | Sequence[str] | None = "ffaa0b1c2d3e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("vehicle_history_audit_documents", sa.Column("extracted_values_json", sa.JSON(), nullable=True))
    op.add_column("vehicle_history_audit_documents", sa.Column("extraction_error", sa.Text(), nullable=True))

    op.create_table(
        "vehicle_history_audit_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("audit_id", sa.Integer(), nullable=False),
        sa.Column("audit_document_id", sa.Integer(), nullable=True),
        sa.Column("field_code", sa.String(length=120), nullable=False),
        sa.Column("field_label", sa.String(length=200), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("unit", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("confidence_level", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["audit_document_id"],
            ["vehicle_history_audit_documents.id"],
            name=op.f("fk_vehicle_history_audit_readings_audit_document_id_vehicle_history_audit_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["vehicle_history_audits.id"],
            name=op.f("fk_vehicle_history_audit_readings_audit_id_vehicle_history_audits"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_vehicle_history_audit_readings")),
    )
    for column in ["audit_id", "audit_document_id", "field_code", "status", "confidence_level"]:
        op.create_index(op.f(f"ix_vehicle_history_audit_readings_{column}"), "vehicle_history_audit_readings", [column], unique=False)


def downgrade() -> None:
    op.drop_table("vehicle_history_audit_readings")
    op.drop_column("vehicle_history_audit_documents", "extraction_error")
    op.drop_column("vehicle_history_audit_documents", "extracted_values_json")
