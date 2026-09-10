"""Track source and ingestion state for email attachments.

Revision ID: ffff34ae102b
Revises: fffe239d0f1a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffff34ae102b"
down_revision: str | Sequence[str] | None = "fffe239d0f1a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("email_attachments", "storage_path", existing_type=sa.Text(), nullable=True)
    op.alter_column("email_attachments", "sha256", existing_type=sa.String(64), nullable=True)
    op.add_column("email_attachments", sa.Column("webhook_event_id", sa.Integer(), nullable=True))
    op.add_column(
        "email_attachments",
        sa.Column("source_provider", sa.String(40), nullable=False, server_default="local"),
    )
    op.add_column("email_attachments", sa.Column("source_attachment_id", sa.String(128), nullable=True))
    op.add_column(
        "email_attachments",
        sa.Column("ingest_state", sa.String(40), nullable=False, server_default="stored"),
    )
    op.add_column("email_attachments", sa.Column("ingest_reason", sa.String(120), nullable=True))
    op.create_foreign_key(
        "fk_email_attachment_webhook_event",
        "email_attachments",
        "email_webhook_events",
        ["webhook_event_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in ("webhook_event_id", "source_provider", "source_attachment_id", "ingest_state"):
        op.create_index(f"ix_email_attachments_{column}", "email_attachments", [column])
    op.create_unique_constraint(
        "uq_email_attachment_webhook_source",
        "email_attachments",
        ["webhook_event_id", "source_attachment_id"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_email_attachment_webhook_source", "email_attachments", type_="unique")
    for column in ("ingest_state", "source_attachment_id", "source_provider", "webhook_event_id"):
        op.drop_index(f"ix_email_attachments_{column}", table_name="email_attachments")
    op.drop_constraint("fk_email_attachment_webhook_event", "email_attachments", type_="foreignkey")
    for column in ("ingest_reason", "ingest_state", "source_attachment_id", "source_provider", "webhook_event_id"):
        op.drop_column("email_attachments", column)
    op.alter_column("email_attachments", "sha256", existing_type=sa.String(64), nullable=False)
    op.alter_column("email_attachments", "storage_path", existing_type=sa.Text(), nullable=False)
