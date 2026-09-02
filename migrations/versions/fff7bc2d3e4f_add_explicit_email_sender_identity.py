"""Add explicit From and Reply-To identities to email channels.

Revision ID: fff7bc2d3e4f
Revises: fff6ab1c2d3e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff7bc2d3e4f"
down_revision: str | Sequence[str] | None = "fff6ab1c2d3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_channels", sa.Column("from_address", sa.String(255), nullable=True))
    op.add_column("email_channels", sa.Column("from_name", sa.String(160), nullable=True))
    op.add_column("email_channels", sa.Column("reply_to_address", sa.String(255), nullable=True))
    op.create_index(op.f("ix_email_channels_from_address"), "email_channels", ["from_address"])
    op.create_index(
        op.f("ix_email_channels_reply_to_address"),
        "email_channels",
        ["reply_to_address"],
    )
    op.execute(
        "UPDATE email_channels SET from_address = 'central@carfast.pt', "
        "reply_to_address = CASE code "
        "WHEN 'test' THEN 'hub@carfast.pt' WHEN 'central' THEN 'central@carfast.pt' END "
    )
    op.execute("UPDATE email_channels SET from_name = left('CarFast — ' || name, 160)")


def downgrade() -> None:
    op.drop_index(op.f("ix_email_channels_reply_to_address"), table_name="email_channels")
    op.drop_index(op.f("ix_email_channels_from_address"), table_name="email_channels")
    op.drop_column("email_channels", "reply_to_address")
    op.drop_column("email_channels", "from_name")
    op.drop_column("email_channels", "from_address")
