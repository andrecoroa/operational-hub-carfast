"""Add the local report timestamp to diagnostic documents."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffa0b1c2d3e4"
down_revision: str | Sequence[str] | None = "2e3f4a5b6c7d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "diagnostic_documents",
        sa.Column("report_datetime", sa.DateTime(timezone=False), nullable=True),
    )
    op.create_index(
        op.f("ix_diagnostic_documents_report_datetime"),
        "diagnostic_documents",
        ["report_datetime"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_diagnostic_documents_report_datetime"),
        table_name="diagnostic_documents",
    )
    op.drop_column("diagnostic_documents", "report_datetime")
