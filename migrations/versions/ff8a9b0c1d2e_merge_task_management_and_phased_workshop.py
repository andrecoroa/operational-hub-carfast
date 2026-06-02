"""Merge task management remap and phased workshop branches."""

from collections.abc import Sequence


revision: str = "ff8a9b0c1d2e"
down_revision: str | Sequence[str] | None = ("8c9b5f3a1d2e", "ff7f8a9b0c1d")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
