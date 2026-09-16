"""Add official vehicle document bundles.

Revision ID: ffff45bf213c
Revises: 100045ab67cd
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffff45bf213c"
down_revision: str | Sequence[str] | None = "100045ab67cd"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vehicle_official_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="current"),
        sa.Column("replaces_id", sa.Integer(), sa.ForeignKey("vehicle_official_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("vehicle_id", "document_type", "valid_until", "status", "replaces_id"):
        op.create_index(f"ix_vehicle_official_documents_{column}", "vehicle_official_documents", [column])
    op.create_table(
        "vehicle_official_document_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("official_document_id", sa.Integer(), sa.ForeignKey("vehicle_official_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("page_role", sa.String(20), nullable=False, server_default="single"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("official_document_id", "page_role", name="uq_vehicle_official_document_page"),
        sa.UniqueConstraint("document_id", name="uq_vehicle_official_document_file_document"),
    )
    op.create_index("ix_vehicle_official_document_files_official_document_id", "vehicle_official_document_files", ["official_document_id"])
    op.create_index("ix_vehicle_official_document_files_document_id", "vehicle_official_document_files", ["document_id"])


def downgrade() -> None:
    op.drop_table("vehicle_official_document_files")
    op.drop_table("vehicle_official_documents")
