"""Add email intake attachments."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ff4c5d6e7f8a"
down_revision: str | Sequence[str] | None = "ff3b4c5d6e7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_intake_attachments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email_intake_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=160), nullable=True),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="pending"),
        sa.Column("archive_url", sa.Text(), nullable=True),
        sa.Column("archive_folder_path", sa.Text(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], name=op.f("fk_email_intake_attachments_document_id_documents"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["email_intake_id"], ["email_intakes.id"], name=op.f("fk_email_intake_attachments_email_intake_id_email_intakes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_intake_attachments")),
    )
    op.create_index(op.f("ix_email_intake_attachments_document_id"), "email_intake_attachments", ["document_id"], unique=False)
    op.create_index(op.f("ix_email_intake_attachments_email_intake_id"), "email_intake_attachments", ["email_intake_id"], unique=False)
    op.create_index(op.f("ix_email_intake_attachments_status"), "email_intake_attachments", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_email_intake_attachments_status"), table_name="email_intake_attachments")
    op.drop_index(op.f("ix_email_intake_attachments_email_intake_id"), table_name="email_intake_attachments")
    op.drop_index(op.f("ix_email_intake_attachments_document_id"), table_name="email_intake_attachments")
    op.drop_table("email_intake_attachments")
