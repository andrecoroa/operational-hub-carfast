"""add email triage classification

Revision ID: eb0c1d2e3f4a
Revises: ea0b1c2d3e4f
"""

from alembic import op
import sqlalchemy as sa


revision = "eb0c1d2e3f4a"
down_revision = "ea0b1c2d3e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, length in (("content_type", 60), ("nature", 60), ("document_type", 80)):
        op.add_column("email_threads", sa.Column(name, sa.String(length), nullable=True))
        op.create_index(f"ix_email_threads_{name}", "email_threads", [name])
    op.add_column("email_threads", sa.Column("triage_notes", sa.Text(), nullable=True))
    op.add_column("email_attachments", sa.Column("status", sa.String(40), nullable=False, server_default="pending"))
    for name, length in (("document_type", 80), ("nature", 60), ("destination", 60)):
        op.add_column("email_attachments", sa.Column(name, sa.String(length), nullable=True))
        op.create_index(f"ix_email_attachments_{name}", "email_attachments", [name])
    op.add_column("email_attachments", sa.Column("notes", sa.Text(), nullable=True))
    op.create_index("ix_email_attachments_status", "email_attachments", ["status"])


def downgrade() -> None:
    op.drop_index("ix_email_attachments_status", table_name="email_attachments")
    op.drop_column("email_attachments", "notes")
    for name in ("destination", "nature", "document_type"):
        op.drop_index(f"ix_email_attachments_{name}", table_name="email_attachments")
        op.drop_column("email_attachments", name)
    op.drop_column("email_attachments", "status")
    op.drop_column("email_threads", "triage_notes")
    for name in ("document_type", "nature", "content_type"):
        op.drop_index(f"ix_email_threads_{name}", table_name="email_threads")
        op.drop_column("email_threads", name)
