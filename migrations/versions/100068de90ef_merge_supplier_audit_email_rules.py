"""Merge the independent supplier-audit and inbox-rule migrations.

Both revisions extend 100056bc78de and change disjoint tables. This merge
preserves both upgrade paths without replaying either migration.
"""

from typing import Sequence

revision: str = "100068de90ef"
down_revision: str | Sequence[str] | None = ("100057bc89ef", "100067cd89ef")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
