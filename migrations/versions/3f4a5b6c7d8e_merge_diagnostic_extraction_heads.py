"""Merge the diagnostic extraction and report timestamp heads."""

from collections.abc import Sequence


revision: str = "3f4a5b6c7d8e"
down_revision: str | Sequence[str] | None = (
    "2e3f4a5b6c7d",
    "ffa0b1c2d3e4",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
