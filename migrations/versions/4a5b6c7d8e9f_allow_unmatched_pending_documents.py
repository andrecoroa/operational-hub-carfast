"""Allow pending document records before vehicle association."""

from collections.abc import Sequence

from alembic import op


revision: str = "4a5b6c7d8e9f"
down_revision: str | Sequence[str] | None = "3f4a5b6c7d8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("vehicle_document_records", "vehicle_id", nullable=True)


def downgrade() -> None:
    op.alter_column("vehicle_document_records", "vehicle_id", nullable=False)
