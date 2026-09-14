"""Allow multiple physical Microsoft 365 mailboxes per functional channel.

Revision ID: 100056bc78de
Revises: ffff45bf213c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "100056bc78de"
down_revision: str | Sequence[str] | None = "ffff45bf213c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_email_channel_transports_channel_id", table_name="email_channel_transports")
    op.drop_constraint(
        "uq_email_channel_transport_channel",
        "email_channel_transports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_email_channel_transport_mailbox",
        "email_channel_transports",
        ["channel_id", "mailbox_address"],
    )
    op.create_index(
        "ix_email_channel_transports_channel_id",
        "email_channel_transports",
        ["channel_id"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.execute(
        sa.text(
            "SELECT channel_id FROM email_channel_transports "
            "GROUP BY channel_id HAVING count(*) > 1"
        )
    ).first()
    if duplicates:
        raise RuntimeError(
            "Cannot restore one transport per channel while multiple mailbox transports exist."
        )
    op.drop_index("ix_email_channel_transports_channel_id", table_name="email_channel_transports")
    op.drop_constraint(
        "uq_email_channel_transport_mailbox",
        "email_channel_transports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_email_channel_transport_channel",
        "email_channel_transports",
        ["channel_id"],
    )
    op.create_index(
        "ix_email_channel_transports_channel_id",
        "email_channel_transports",
        ["channel_id"],
        unique=True,
    )
