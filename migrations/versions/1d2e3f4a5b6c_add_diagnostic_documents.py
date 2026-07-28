"""Add diagnostic-specific document metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "1d2e3f4a5b6c"
down_revision: str | Sequence[str] | None = "0c1d2e3f4a5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("diagnostic_type", sa.String(length=120), nullable=False),
        sa.Column(
            "diagnostic_status",
            sa.String(length=40),
            nullable=False,
            server_default="received",
        ),
        sa.Column(
            "association_status",
            sa.String(length=40),
            nullable=False,
            server_default="unassociated",
        ),
        sa.Column("report_number", sa.String(length=160), nullable=True),
        sa.Column("diagnostic_tool", sa.String(length=160), nullable=True),
        sa.Column("diagnostic_tool_serial", sa.String(length=160), nullable=True),
        sa.Column("technician_name", sa.String(length=160), nullable=True),
        sa.Column("odometer_km", sa.Integer(), nullable=True),
        sa.Column("detected_plate", sa.String(length=40), nullable=True),
        sa.Column("detected_vin", sa.String(length=80), nullable=True),
        sa.Column(
            "ocr_status",
            sa.String(length=40),
            nullable=False,
            server_default="not_requested",
        ),
        sa.Column("ocr_confidence", sa.Float(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("ocr_payload_json", sa.JSON(), nullable=True),
        sa.Column(
            "validation_status",
            sa.String(length=40),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("validation_notes", sa.Text(), nullable=True),
        sa.Column("validated_by_id", sa.Integer(), nullable=True),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_diagnostic_documents_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["validated_by_id"],
            ["users.id"],
            name=op.f("fk_diagnostic_documents_validated_by_id_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_documents")),
        sa.UniqueConstraint("document_id", name=op.f("uq_diagnostic_documents_document_id")),
    )
    for column in (
        "document_id",
        "diagnostic_type",
        "diagnostic_status",
        "association_status",
        "report_number",
        "detected_plate",
        "detected_vin",
        "ocr_status",
        "validation_status",
    ):
        op.create_index(
            op.f(f"ix_diagnostic_documents_{column}"),
            "diagnostic_documents",
            [column],
            unique=column == "document_id",
        )

    diagnostic_documents = sa.table(
        "diagnostic_documents",
        sa.column("document_id", sa.Integer()),
        sa.column("diagnostic_type", sa.String()),
        sa.column("association_status", sa.String()),
    )
    documents = sa.table(
        "documents",
        sa.column("id", sa.Integer()),
        sa.column("document_type", sa.String()),
        sa.column("vehicle_id", sa.Integer()),
    )
    connection = op.get_bind()
    existing = connection.execute(
        sa.select(documents.c.id, documents.c.vehicle_id).where(
            documents.c.document_type == "workshop_diagnostic"
        )
    )
    legacy_rows = [
        {
            "document_id": row.id,
            "diagnostic_type": "other_diagnostic",
            "association_status": "confirmed" if row.vehicle_id else "unassociated",
        }
        for row in existing
    ]
    if legacy_rows:
        connection.execute(diagnostic_documents.insert(), legacy_rows)


def downgrade() -> None:
    op.drop_table("diagnostic_documents")
