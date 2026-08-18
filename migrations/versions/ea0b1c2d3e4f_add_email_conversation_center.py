"""add email conversation center

Revision ID: ea0b1c2d3e4f
Revises: e9f0a1b2c3d4
"""

from alembic import op
import sqlalchemy as sa

revision = "ea0b1c2d3e4f"
down_revision = "e9f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_channels",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("address", sa.String(255), nullable=False),
        sa.Column("inbound_hash", sa.String(255)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("approval_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("code"),
        sa.UniqueConstraint("address"),
        sa.UniqueConstraint("inbound_hash"),
    )
    op.create_table(
        "email_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("email_channels.id"), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("status", sa.String(60), nullable=False, server_default="triage"),
        sa.Column("sender_email", sa.String(255)),
        sa.Column("sender_name", sa.String(255)),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("assigned_to_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("external_conversation_id", sa.String(255)),
        sa.Column("last_message_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "email_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("external_message_id", sa.String(255), unique=True),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("state", sa.String(40), nullable=False, server_default="received"),
        sa.Column("sender", sa.String(255), nullable=False),
        sa.Column("recipients_json", sa.JSON()),
        sa.Column("cc_json", sa.JSON()),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("text_body", sa.Text()),
        sa.Column("html_body", sa.Text()),
        sa.Column("headers_json", sa.JSON()),
        sa.Column("received_at", sa.DateTime(timezone=True)),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("postmark_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "email_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "message_id",
            sa.Integer(),
            sa.ForeignKey("email_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("file_name", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(160)),
        sa.Column("content_id", sa.String(255)),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "email_webhook_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(128), nullable=False, unique=True),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "email_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("email_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id", sa.Integer(), sa.ForeignKey("email_messages.id", ondelete="SET NULL")
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("details_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_table(
        "email_channel_users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("email_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("can_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_approve", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("channel_id", "user_id", name="uq_email_channel_user"),
    )
    for table, columns in {
        "email_threads": ["channel_id", "status", "task_id", "last_message_at"],
        "email_messages": ["thread_id", "state"],
        "email_attachments": ["message_id", "sha256"],
        "email_audit_events": ["thread_id", "user_id"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    for table in (
        "email_channel_users",
        "email_audit_events",
        "email_webhook_events",
        "email_attachments",
        "email_messages",
        "email_threads",
        "email_channels",
    ):
        op.drop_table(table)
