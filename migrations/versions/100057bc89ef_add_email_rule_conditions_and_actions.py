"""add email rule conditions and actions

Revision ID: 100057bc89ef
Revises: 100056bc78de
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "100057bc89ef"
down_revision: str | Sequence[str] | None = "100056bc78de"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_inbox_rules", sa.Column("sender_match", sa.String(255)))
    op.add_column(
        "email_inbox_rules",
        sa.Column("sender_match_type", sa.String(20), nullable=False, server_default="contains"),
    )
    op.add_column(
        "email_inbox_rules",
        sa.Column("condition_operator", sa.String(10), nullable=False, server_default="and"),
    )
    op.add_column(
        "email_inbox_rules",
        sa.Column("status_action", sa.String(20), nullable=False, server_default="none"),
    )
    op.add_column(
        "email_inbox_rules",
        sa.Column("deterministic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_check_constraint(
        "ck_email_inbox_rules_condition_operator",
        "email_inbox_rules",
        "condition_operator IN ('and', 'or')",
    )
    op.create_check_constraint(
        "ck_email_inbox_rules_sender_match_type",
        "email_inbox_rules",
        "sender_match_type IN ('contains', 'exact', 'domain')",
    )
    op.create_check_constraint(
        "ck_email_inbox_rules_status_action",
        "email_inbox_rules",
        "status_action IN ('none', 'in_progress', 'resolved', 'archived')",
    )
    op.create_index("ix_email_inbox_rules_sender_match", "email_inbox_rules", ["sender_match"])
    op.create_index("ix_email_inbox_rules_status_action", "email_inbox_rules", ["status_action"])
    op.create_index("ix_email_inbox_rules_deterministic", "email_inbox_rules", ["deterministic"])


def downgrade() -> None:
    for name in ("deterministic", "status_action", "sender_match"):
        op.drop_index(f"ix_email_inbox_rules_{name}", table_name="email_inbox_rules")
    for name in ("status_action", "sender_match_type", "condition_operator"):
        op.drop_constraint(f"ck_email_inbox_rules_{name}", "email_inbox_rules", type_="check")
    for name in (
        "deterministic",
        "status_action",
        "condition_operator",
        "sender_match_type",
        "sender_match",
    ):
        op.drop_column("email_inbox_rules", name)
