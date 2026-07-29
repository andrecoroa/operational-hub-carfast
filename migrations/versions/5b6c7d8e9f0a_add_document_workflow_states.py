"""Add independent document workflow dimensions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "5b6c7d8e9f0a"
down_revision: str | Sequence[str] | None = "4a5b6c7d8e9f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "document_workflow_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("ingestion_status", sa.String(length=40), server_default="received", nullable=False),
        sa.Column("association_status", sa.String(length=40), server_default="unassociated", nullable=False),
        sa.Column("extraction_status", sa.String(length=40), server_default="not_requested", nullable=False),
        sa.Column("validation_status", sa.String(length=40), server_default="pending", nullable=False),
        sa.Column("destination_status", sa.String(length=40), server_default="triage", nullable=False),
        sa.Column("invoice_nature", sa.String(length=40), nullable=True),
        sa.Column("suggested_invoice_nature", sa.String(length=40), nullable=True),
        sa.Column("suggestion_confidence", sa.Float(), nullable=True),
        sa.Column("human_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("confirmed_by_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ingestion_status IN ('received','queued','processing','completed','failed')",
            name="ck_document_workflow_ingestion",
        ),
        sa.CheckConstraint(
            "association_status IN ('unassociated','suggested','associated','failed')",
            name="ck_document_workflow_association",
        ),
        sa.CheckConstraint(
            "extraction_status IN ('not_requested','queued','processing','extracted','failed')",
            name="ck_document_workflow_extraction",
        ),
        sa.CheckConstraint(
            "validation_status IN ('pending','automatic_validated','human_validated','rejected')",
            name="ck_document_workflow_validation",
        ),
        sa.CheckConstraint(
            "destination_status IN ('triage','imports','invoices','diagnostics','archive','unknown')",
            name="ck_document_workflow_destination",
        ),
        sa.CheckConstraint(
            "invoice_nature IS NULL OR invoice_nature IN ('por_classificar','operacional','financeira')",
            name="ck_document_workflow_invoice_nature",
        ),
        sa.CheckConstraint(
            "suggested_invoice_nature IS NULL OR suggested_invoice_nature IN ('por_classificar','operacional','financeira')",
            name="ck_document_workflow_suggested_invoice_nature",
        ),
        sa.CheckConstraint(
            "suggestion_confidence IS NULL OR (suggestion_confidence >= 0 AND suggestion_confidence <= 1)",
            name="ck_document_workflow_suggestion_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_id"],
            ["users.id"],
            name=op.f("fk_document_workflow_states_confirmed_by_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_workflow_states_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_workflow_states")),
        sa.UniqueConstraint("document_id", name="uq_document_workflow_state_document"),
    )
    for column in (
        "document_id",
        "ingestion_status",
        "association_status",
        "extraction_status",
        "validation_status",
        "destination_status",
        "invoice_nature",
        "suggested_invoice_nature",
        "human_confirmed",
    ):
        op.create_index(
            op.f(f"ix_document_workflow_states_{column}"),
            "document_workflow_states",
            [column],
            unique=False,
        )

    # Backfill the legacy projection once. New/previously missed rows are still
    # handled by the compatibility adapter in app.services.document_workflow.
    op.execute(
        sa.text(
            """
            INSERT INTO document_workflow_states (
                document_id,
                ingestion_status,
                association_status,
                extraction_status,
                validation_status,
                destination_status,
                invoice_nature,
                human_confirmed
            )
            SELECT
                id,
                CASE
                    WHEN status IN ('failed','ocr_issue','unable_to_read','error') THEN 'failed'
                    WHEN status IN ('pending_triage','received','pending') THEN 'received'
                    ELSE 'completed'
                END,
                CASE WHEN vehicle_id IS NULL THEN 'unassociated' ELSE 'associated' END,
                CASE
                    WHEN status IN ('ocr_issue','unable_to_read') THEN 'failed'
                    WHEN status IN ('extracted','classified','pending_validation') THEN 'extracted'
                    ELSE 'not_requested'
                END,
                CASE
                    WHEN status IN ('classified','archived') THEN 'human_validated'
                    WHEN status = 'ignored' THEN 'rejected'
                    ELSE 'pending'
                END,
                CASE
                    WHEN status = 'pending_triage' THEN 'triage'
                    WHEN document_type IN ('workshop_diagnostic','workshop_report','diagnostic_report','technical_report') THEN 'diagnostics'
                    WHEN document_type = 'finance_supplier_invoice' THEN 'archive'
                    WHEN document_type = 'workshop_supplier_invoice' THEN 'invoices'
                    ELSE 'archive'
                END,
                CASE
                    WHEN document_type = 'finance_supplier_invoice' THEN 'financeira'
                    WHEN document_type = 'workshop_supplier_invoice' THEN 'operacional'
                    ELSE NULL
                END,
                CASE WHEN status IN ('classified','archived') THEN 1 ELSE 0 END
            FROM documents
            """
        )
    )


def downgrade() -> None:
    op.drop_table("document_workflow_states")
