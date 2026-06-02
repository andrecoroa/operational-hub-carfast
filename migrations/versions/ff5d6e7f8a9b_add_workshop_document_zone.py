"""Add workshop document zone fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ff5d6e7f8a9b"
down_revision: str | Sequence[str] | None = "ff4c5d6e7f8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workshop_processes", sa.Column("document_folder_path", sa.Text(), nullable=True))
    op.add_column("workshop_processes", sa.Column("document_folder_url", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("workshop_processes", "document_folder_url")
    op.drop_column("workshop_processes", "document_folder_path")
