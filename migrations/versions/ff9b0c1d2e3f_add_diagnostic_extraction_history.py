"""Add lossless, versioned diagnostic extraction history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ff9b0c1d2e3f"
down_revision: str | Sequence[str] | None = "ff8a9b0c1d2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "diagnostic_extractions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("diagnostic_document_id", sa.Integer(), nullable=False),
        sa.Column("extractor_name", sa.String(length=120), nullable=False),
        sa.Column("extractor_version", sa.String(length=40), nullable=False),
        sa.Column("parser_name", sa.String(length=120), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("source_machine", sa.String(length=80), nullable=True),
        sa.Column("source_family", sa.String(length=40), nullable=True),
        sa.Column("source_filename", sa.String(length=255), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_page_count", sa.Integer(), nullable=False),
        sa.Column("extraction_method", sa.String(length=80), nullable=False),
        sa.Column("extraction_status", sa.String(length=40), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("native_text", sa.Text(), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("raw_metadata_json", sa.JSON(), nullable=True),
        sa.Column("pages_json", sa.JSON(), nullable=True),
        sa.Column("normalized_data_json", sa.JSON(), nullable=True),
        sa.Column("dynamic_fields_json", sa.JSON(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["diagnostic_document_id"],
            ["diagnostic_documents.id"],
            name=op.f(
                "fk_diagnostic_extractions_diagnostic_document_id_diagnostic_documents"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_diagnostic_extractions")),
    )
    for column in (
        "diagnostic_document_id",
        "source_machine",
        "source_family",
        "source_sha256",
        "extraction_status",
    ):
        op.create_index(
            op.f(f"ix_diagnostic_extractions_{column}"),
            "diagnostic_extractions",
            [column],
            unique=False,
        )


def downgrade() -> None:
    op.drop_table("diagnostic_extractions")
