"""add document entry email fields

Revision ID: f6a7b8c9d0e1
Revises: f5a6b7c8d9e0
Create Date: 2026-05-13 00:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f6a7b8c9d0e1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("entry_channel", sa.String(length=120), nullable=True))
    op.add_column("documents", sa.Column("source_sender", sa.String(length=255), nullable=True))
    op.add_column("documents", sa.Column("source_subject", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_documents_entry_channel"), "documents", ["entry_channel"], unique=False)
    op.create_index(op.f("ix_documents_source_sender"), "documents", ["source_sender"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_source_sender"), table_name="documents")
    op.drop_index(op.f("ix_documents_entry_channel"), table_name="documents")
    op.drop_column("documents", "source_subject")
    op.drop_column("documents", "source_sender")
    op.drop_column("documents", "entry_channel")
