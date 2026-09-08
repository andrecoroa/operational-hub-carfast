"""Add per-mailbox Microsoft 365 transport configuration.

Revision ID: fffc017b8d9e
Revises: fffbf06a7c8d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fffc017b8d9e"
down_revision: str | Sequence[str] | None = "fffbf06a7c8d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_channel_transports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("email_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(30), nullable=False, server_default="postmark"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("mailbox_address", sa.String(255)),
        sa.Column("tenant_id", sa.String(80)),
        sa.Column("client_id", sa.String(80)),
        sa.Column("client_credential_reference", sa.String(255)),
        sa.Column("token_reference", sa.String(255)),
        sa.Column("delegated_user_principal_name", sa.String(255)),
        sa.Column("initial_sync_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("connected_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "provider IN ('postmark', 'microsoft365')", name="ck_email_channel_transports_provider"
        ),
        sa.CheckConstraint(
            "initial_sync_days > 0 AND initial_sync_days <= 30",
            name="ck_email_channel_transports_initial_sync_days",
        ),
        sa.UniqueConstraint("channel_id", name="uq_email_channel_transport_channel"),
    )
    op.create_index(
        "ix_email_channel_transports_channel_id",
        "email_channel_transports",
        ["channel_id"],
        unique=True,
    )
    op.create_index(
        "ix_email_channel_transports_provider", "email_channel_transports", ["provider"]
    )
    op.create_index("ix_email_channel_transports_enabled", "email_channel_transports", ["enabled"])
    op.create_index(
        "ix_email_channel_transports_mailbox_address",
        "email_channel_transports",
        ["mailbox_address"],
    )

    op.create_table(
        "email_sync_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "transport_id",
            sa.Integer(),
            sa.ForeignKey("email_channel_transports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("folder", sa.String(30), nullable=False),
        sa.Column("delta_link", sa.Text()),
        sa.Column("initial_window_started_at", sa.DateTime(timezone=True)),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "folder IN ('inbox', 'sentitems', 'drafts')", name="ck_email_sync_checkpoints_folder"
        ),
        sa.UniqueConstraint("transport_id", "folder", name="uq_email_sync_checkpoint_folder"),
    )
    op.create_index(
        "ix_email_sync_checkpoints_transport_id", "email_sync_checkpoints", ["transport_id"]
    )
    op.create_index("ix_email_sync_checkpoints_folder", "email_sync_checkpoints", ["folder"])
    op.create_index("ix_email_sync_checkpoints_status", "email_sync_checkpoints", ["status"])


def downgrade() -> None:
    op.drop_table("email_sync_checkpoints")
    op.drop_table("email_channel_transports")
