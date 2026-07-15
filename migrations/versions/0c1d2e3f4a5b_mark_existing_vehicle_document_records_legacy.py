"""Mark existing vehicle document records as legacy baseline."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0c1d2e3f4a5b"
down_revision: str | Sequence[str] | None = "0b1c2d3e4f5a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE vehicle_document_records
            SET source_record_type = 'legacy_structured'
            WHERE source_record_type = 'structured'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE vehicle_document_records
            SET source_record_type = 'legacy_archive_pending'
            WHERE source_record_type = 'archive_pending'
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE vehicle_document_records
            SET source_record_type = 'structured'
            WHERE source_record_type = 'legacy_structured'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE vehicle_document_records
            SET source_record_type = 'archive_pending'
            WHERE source_record_type = 'legacy_archive_pending'
            """
        )
    )
