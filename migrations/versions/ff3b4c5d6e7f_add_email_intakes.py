"""Add email intake records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ff3b4c5d6e7f"
down_revision: str | Sequence[str] | None = "ff2a3b4c5d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_intakes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_mailbox", sa.String(length=255), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("subject", sa.String(length=255), nullable=True),
        sa.Column("body_preview", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_url", sa.Text(), nullable=True),
        sa.Column("attachments_url", sa.Text(), nullable=True),
        sa.Column("list_item_id", sa.String(length=255), nullable=True),
        sa.Column("list_item_url", sa.Text(), nullable=True),
        sa.Column("external_message_id", sa.String(length=255), nullable=True),
        sa.Column("conversation_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=60), nullable=False, server_default="received"),
        sa.Column("target_entity_type", sa.String(length=80), nullable=True),
        sa.Column("target_entity_id", sa.String(length=120), nullable=True),
        sa.Column("target_url", sa.Text(), nullable=True),
        sa.Column("routing_note", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_intakes")),
    )
    for column in (
        "source_mailbox",
        "sender",
        "subject",
        "received_at",
        "list_item_id",
        "external_message_id",
        "conversation_id",
        "status",
        "target_entity_type",
        "target_entity_id",
    ):
        op.create_index(op.f(f"ix_email_intakes_{column}"), "email_intakes", [column], unique=False)


def downgrade() -> None:
    for column in (
        "target_entity_id",
        "target_entity_type",
        "status",
        "conversation_id",
        "external_message_id",
        "list_item_id",
        "received_at",
        "subject",
        "sender",
        "source_mailbox",
    ):
        op.drop_index(op.f(f"ix_email_intakes_{column}"), table_name="email_intakes")
    op.drop_table("email_intakes")
