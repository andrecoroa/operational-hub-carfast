"""add task collaboration and email origin

Revision ID: 6c7d8e9f0a1b
Revises: 5b6c7d8e9f0a
"""

from alembic import op
import sqlalchemy as sa


revision = "6c7d8e9f0a1b"
down_revision = "5b6c7d8e9f0a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_participants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", "role", name="uq_task_participant_role"),
    )
    op.create_index("ix_task_participants_task_id", "task_participants", ["task_id"])
    op.create_index("ix_task_participants_user_id", "task_participants", ["user_id"])
    op.create_index("ix_task_participants_role", "task_participants", ["role"])
    op.create_index("ix_task_participants_status", "task_participants", ["status"])

    op.create_table(
        "task_email_origins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("message_id", sa.String(length=255), nullable=False),
        sa.Column("sender", sa.String(length=255), nullable=True),
        sa.Column("recipients_json", sa.JSON(), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mailbox", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("rule_code", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("message_id"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index("ix_task_email_origins_task_id", "task_email_origins", ["task_id"])
    op.create_index("ix_task_email_origins_message_id", "task_email_origins", ["message_id"])
    op.create_index("ix_task_email_origins_sender", "task_email_origins", ["sender"])
    op.create_index("ix_task_email_origins_received_at", "task_email_origins", ["received_at"])
    op.create_index("ix_task_email_origins_mailbox", "task_email_origins", ["mailbox"])
    op.create_index("ix_task_email_origins_rule_code", "task_email_origins", ["rule_code"])
    op.create_table(
        "task_help_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("requested_user_id", sa.Integer(), nullable=False),
        sa.Column("requested_by_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["requested_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_help_requests_task_id", "task_help_requests", ["task_id"])
    op.create_index("ix_task_help_requests_requested_user_id", "task_help_requests", ["requested_user_id"])
    op.create_index("ix_task_help_requests_status", "task_help_requests", ["status"])


def downgrade() -> None:
    op.drop_table("task_help_requests")
    op.drop_table("task_email_origins")
    op.drop_table("task_participants")
