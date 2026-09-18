"""Allow inbox rules to target one original recipient alias.

Revision ID: 10006a0f12bc
Revises: 100069ef01ab
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10006a0f12bc"
down_revision: str | Sequence[str] | None = "100069ef01ab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_inbox_rules",
        sa.Column("recipient_alias_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_email_inbox_rules_recipient_alias_id",
        "email_inbox_rules",
        "email_channel_aliases",
        ["recipient_alias_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_email_inbox_rules_recipient_alias_id",
        "email_inbox_rules",
        ["recipient_alias_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_email_inbox_rules_recipient_alias_id", table_name="email_inbox_rules")
    op.drop_constraint(
        "fk_email_inbox_rules_recipient_alias_id", "email_inbox_rules", type_="foreignkey"
    )
    op.drop_column("email_inbox_rules", "recipient_alias_id")
