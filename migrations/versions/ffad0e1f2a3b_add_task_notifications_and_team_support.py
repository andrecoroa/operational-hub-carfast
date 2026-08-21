"""Add task notifications and team-directed support.

Revision ID: ffad0e1f2a3b
Revises: ffac0d1e2f3a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ffad0e1f2a3b"
down_revision: str | Sequence[str] | None = "fff26e7f8a9c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("task_help_requests") as batch_op:
        batch_op.alter_column(
            "requested_user_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.add_column(
            sa.Column("requested_team_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_task_help_requests_requested_team_id_teams",
            "teams",
            ["requested_team_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index(
            "ix_task_help_requests_requested_team_id",
            ["requested_team_id"],
            unique=False,
        )

    op.create_table(
        "task_notifications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_notifications_task_id", "task_notifications", ["task_id"]
    )
    op.create_index(
        "ix_task_notifications_user_id", "task_notifications", ["user_id"]
    )
    op.create_index(
        "ix_task_notifications_actor_user_id",
        "task_notifications",
        ["actor_user_id"],
    )
    op.create_index(
        "ix_task_notifications_event_type", "task_notifications", ["event_type"]
    )
    op.create_index(
        "ix_task_notifications_created_at", "task_notifications", ["created_at"]
    )
    op.create_index(
        "ix_task_notifications_read_at", "task_notifications", ["read_at"]
    )


def downgrade() -> None:
    op.drop_table("task_notifications")
    with op.batch_alter_table("task_help_requests") as batch_op:
        batch_op.drop_index("ix_task_help_requests_requested_team_id")
        batch_op.drop_constraint(
            "fk_task_help_requests_requested_team_id_teams",
            type_="foreignkey",
        )
        batch_op.drop_column("requested_team_id")
        batch_op.alter_column(
            "requested_user_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
