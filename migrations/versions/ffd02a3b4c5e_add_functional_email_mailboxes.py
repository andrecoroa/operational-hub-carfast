"""add configurable functional email mailboxes and delivery origins

Revision ID: ffd02a3b4c5e
Revises: ffcf2a3b4c5d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffd02a3b4c5e"
down_revision: str | Sequence[str] | None = "ffcf2a3b4c5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def _index(table: str, *columns: str) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.alter_column("email_channels", "address", existing_type=sa.String(255), nullable=True)
    op.add_column("email_channels", sa.Column("default_reply_address", sa.String(255)))
    op.add_column(
        "email_channels",
        sa.Column("reply_policy", sa.String(20), nullable=False, server_default="mailbox"),
    )
    op.add_column(
        "email_channels",
        sa.Column("requires_triage", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "email_channels",
        sa.Column(
            "administrative_review_on_unclassified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "email_channels",
        sa.Column(
            "functional_owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )
    _index(
        "email_channels",
        "default_reply_address",
        "reply_policy",
        "requires_triage",
        "administrative_review_on_unclassified",
        "functional_owner_user_id",
    )
    op.create_unique_constraint(
        "uq_email_channels_default_reply_address",
        "email_channels",
        ["default_reply_address"],
    )
    op.create_check_constraint(
        "ck_email_channels_reply_policy",
        "email_channels",
        "reply_policy IN ('original', 'mailbox')",
    )
    op.execute(
        "UPDATE email_channels SET default_reply_address = address "
        "WHERE default_reply_address IS NULL"
    )

    op.create_table(
        "email_channel_aliases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("email_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("label", sa.String(160)),
        sa.Column("inbound_hash", sa.String(255)),
        sa.Column("inbound_forward_address", sa.String(255)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("address", name="uq_email_channel_alias_address"),
        sa.UniqueConstraint("inbound_hash", name="uq_email_channel_alias_inbound_hash"),
        sa.UniqueConstraint(
            "inbound_forward_address",
            name="uq_email_channel_alias_inbound_forward_address",
        ),
    )
    _index(
        "email_channel_aliases",
        "channel_id",
        "address",
        "inbound_hash",
        "inbound_forward_address",
        "active",
    )
    op.execute(
        "INSERT INTO email_channel_aliases "
        "(channel_id, address, label, inbound_hash, inbound_forward_address, active) "
        "SELECT id, address, 'Endereço migrado', inbound_hash, inbound_forward_address, active "
        "FROM email_channels WHERE address IS NOT NULL"
    )

    for column in (
        sa.Column(
            "functional_owner_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "administrative_review_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("original_recipient_address", sa.String(255)),
        sa.Column("technical_recipient_address", sa.String(255)),
    ):
        op.add_column("email_threads", column)
    _index(
        "email_threads",
        "functional_owner_user_id",
        "administrative_review_required",
        "original_recipient_address",
        "technical_recipient_address",
    )

    message_columns = (
        sa.Column("logical_message_key", sa.String(320)),
        sa.Column("bcc_json", sa.JSON()),
        sa.Column("approval_fingerprint", sa.String(64)),
        sa.Column("content_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("approved_revision", sa.Integer()),
        sa.Column("compose_mode", sa.String(20), nullable=False, server_default="reply"),
        sa.Column(
            "template_id",
            sa.Integer(),
            sa.ForeignKey("email_templates.id", ondelete="SET NULL"),
        ),
        sa.Column("template_version", sa.Integer()),
        sa.Column("template_snapshot_json", sa.JSON()),
    )
    for column in message_columns:
        op.add_column("email_messages", column)
    _index(
        "email_messages",
        "logical_message_key",
        "approval_fingerprint",
        "compose_mode",
        "template_id",
    )

    op.create_table(
        "email_delivery_origins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("email_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_alias_id",
            sa.Integer(),
            sa.ForeignKey("email_channel_aliases.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "webhook_event_id",
            sa.Integer(),
            sa.ForeignKey("email_webhook_events.id", ondelete="SET NULL"),
        ),
        sa.Column("delivery_key", sa.String(320), nullable=False),
        sa.Column("delivery_message_id", sa.String(255)),
        sa.Column("original_recipient", sa.String(255)),
        sa.Column("technical_recipient", sa.String(255)),
        sa.Column("postmark_mailbox_hash", sa.String(255)),
        sa.Column("recipients_json", sa.JSON()),
        sa.Column("cc_json", sa.JSON()),
        *_timestamps(),
        sa.UniqueConstraint("delivery_key", name="uq_email_delivery_origin_key"),
    )
    _index(
        "email_delivery_origins",
        "message_id",
        "channel_alias_id",
        "webhook_event_id",
        "delivery_key",
        "delivery_message_id",
        "original_recipient",
        "technical_recipient",
        "postmark_mailbox_hash",
    )

    for table in ("email_channel_users", "email_channel_roles"):
        for name in ("can_change_sender", "can_edit_recipients", "can_use_cc_bcc"):
            op.add_column(
                table,
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
            )

    op.add_column(
        "email_templates", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.add_column("email_templates", sa.Column("allowed_variables_json", sa.JSON()))

    op.create_table(
        "email_thread_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("link_type", sa.String(20), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("reference", sa.String(255)),
        sa.Column("url", sa.Text()),
        sa.Column(
            "created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "link_type IN ('process', 'entity')",
            name="ck_email_thread_links_type",
        ),
    )
    _index(
        "email_thread_links",
        "thread_id",
        "link_type",
        "reference",
        "created_by_id",
    )


def downgrade() -> None:
    op.drop_table("email_thread_links")
    op.drop_column("email_templates", "allowed_variables_json")
    op.drop_column("email_templates", "version")
    for table in ("email_channel_roles", "email_channel_users"):
        for name in ("can_use_cc_bcc", "can_edit_recipients", "can_change_sender"):
            op.drop_column(table, name)
    op.drop_table("email_delivery_origins")
    for name in (
        "template_snapshot_json",
        "template_version",
        "template_id",
        "compose_mode",
        "approved_revision",
        "content_revision",
        "approval_fingerprint",
        "bcc_json",
        "logical_message_key",
    ):
        op.drop_column("email_messages", name)
    for name in (
        "technical_recipient_address",
        "original_recipient_address",
        "administrative_review_required",
        "functional_owner_user_id",
    ):
        op.drop_column("email_threads", name)
    op.drop_table("email_channel_aliases")
    op.drop_constraint("ck_email_channels_reply_policy", "email_channels", type_="check")
    op.drop_constraint(
        "uq_email_channels_default_reply_address", "email_channels", type_="unique"
    )
    for name in (
        "functional_owner_user_id",
        "administrative_review_on_unclassified",
        "requires_triage",
        "reply_policy",
        "default_reply_address",
    ):
        op.drop_column("email_channels", name)
    op.alter_column("email_channels", "address", existing_type=sa.String(255), nullable=False)
