"""add email inbox rules

Revision ID: ffad1e2f3a4b
Revises: ffac0d1e2f3a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffad1e2f3a4b"
down_revision: str | Sequence[str] | None = "ffac0d1e2f3a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_inbox_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("email_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("subject_match", sa.String(length=500), nullable=False),
        sa.Column("match_type", sa.String(length=20), nullable=False, server_default="contains"),
        sa.Column(
            "default_queue_id", sa.Integer(), sa.ForeignKey("work_queues.id", ondelete="SET NULL")
        ),
        sa.Column(
            "default_department_id",
            sa.Integer(),
            sa.ForeignKey("work_departments.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "default_category_id",
            sa.Integer(),
            sa.ForeignKey("work_categories.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "default_subcategory_id",
            sa.Integer(),
            sa.ForeignKey("work_subcategories.id", ondelete="SET NULL"),
        ),
        sa.Column("default_document_type", sa.String(length=80)),
        sa.Column(
            "default_assignee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("default_due_days", sa.Integer()),
        sa.Column("default_wait_days", sa.Integer()),
        sa.Column("auto_task_mode", sa.String(length=40)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in (
        "channel_id",
        "match_type",
        "default_queue_id",
        "default_department_id",
        "default_category_id",
        "default_subcategory_id",
        "default_document_type",
        "default_assignee_id",
        "auto_task_mode",
        "active",
        "sort_order",
    ):
        op.create_index(f"ix_email_inbox_rules_{column}", "email_inbox_rules", [column])


def downgrade() -> None:
    op.drop_table("email_inbox_rules")
