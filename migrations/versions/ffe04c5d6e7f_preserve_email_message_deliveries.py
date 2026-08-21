"""Preserve logical email deliveries across Postmark forwards.

Revision ID: ffe04c5d6e7f
Revises: ffd03b4c5d6e
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffe04c5d6e7f"
down_revision: str | Sequence[str] | None = "ffd03b4c5d6e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_message_deliveries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.Integer(), nullable=False),
        sa.Column("webhook_event_id", sa.Integer(), nullable=False),
        sa.Column("logical_key", sa.String(length=128), nullable=False),
        sa.Column("canonical_marker", sa.String(length=20), nullable=True),
        sa.Column("postmark_message_id", sa.String(length=255), nullable=True),
        sa.Column("original_recipient", sa.String(length=500), nullable=True),
        sa.Column("technical_recipient", sa.String(length=500), nullable=True),
        sa.Column("inbound_address", sa.String(length=500), nullable=True),
        sa.Column("mailbox_hash", sa.String(length=255), nullable=True),
        sa.Column("to_json", sa.JSON(), nullable=True),
        sa.Column("cc_json", sa.JSON(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["channel_id"], ["email_channels.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["message_id"], ["email_messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["webhook_event_id"], ["email_webhook_events.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id",
            "logical_key",
            "canonical_marker",
            name="uq_email_message_delivery_canonical",
        ),
        sa.UniqueConstraint(
            "webhook_event_id", name="uq_email_message_delivery_event"
        ),
    )
    op.create_index(
        op.f("ix_email_message_deliveries_channel_id"),
        "email_message_deliveries",
        ["channel_id"],
    )
    op.create_index(
        op.f("ix_email_message_deliveries_logical_key"),
        "email_message_deliveries",
        ["logical_key"],
    )
    op.create_index(
        op.f("ix_email_message_deliveries_mailbox_hash"),
        "email_message_deliveries",
        ["mailbox_hash"],
    )
    op.create_index(
        op.f("ix_email_message_deliveries_message_id"),
        "email_message_deliveries",
        ["message_id"],
    )
    op.create_index(
        op.f("ix_email_message_deliveries_postmark_message_id"),
        "email_message_deliveries",
        ["postmark_message_id"],
    )
    op.create_index(
        op.f("ix_email_message_deliveries_received_at"),
        "email_message_deliveries",
        ["received_at"],
    )
    op.create_index(
        op.f("ix_email_message_deliveries_webhook_event_id"),
        "email_message_deliveries",
        ["webhook_event_id"],
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM email_message_deliveries) THEN "
        "RAISE EXCEPTION 'Cannot safely remove preserved email delivery history'; "
        "END IF; END $$"
    )
    op.drop_index(
        op.f("ix_email_message_deliveries_webhook_event_id"),
        table_name="email_message_deliveries",
    )
    op.drop_index(
        op.f("ix_email_message_deliveries_received_at"),
        table_name="email_message_deliveries",
    )
    op.drop_index(
        op.f("ix_email_message_deliveries_postmark_message_id"),
        table_name="email_message_deliveries",
    )
    op.drop_index(
        op.f("ix_email_message_deliveries_message_id"),
        table_name="email_message_deliveries",
    )
    op.drop_index(
        op.f("ix_email_message_deliveries_mailbox_hash"),
        table_name="email_message_deliveries",
    )
    op.drop_index(
        op.f("ix_email_message_deliveries_logical_key"),
        table_name="email_message_deliveries",
    )
    op.drop_index(
        op.f("ix_email_message_deliveries_channel_id"),
        table_name="email_message_deliveries",
    )
    op.drop_table("email_message_deliveries")
