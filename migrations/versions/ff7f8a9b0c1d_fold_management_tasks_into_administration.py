"""Fold management task center into administration."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ff7f8a9b0c1d"
down_revision: str | Sequence[str] | None = "ff6e7f8a9b0c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE tasks
            SET task_type = 'administration_task'
            WHERE task_type = 'management_task'
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE quick_records
            SET workspace = 'administration'
            WHERE workspace = 'management'
            """
        )
    )


def downgrade() -> None:
    # Intentional no-op: after moving into Administration there is no reliable
    # marker to distinguish former management tasks from native admin tasks.
    pass
