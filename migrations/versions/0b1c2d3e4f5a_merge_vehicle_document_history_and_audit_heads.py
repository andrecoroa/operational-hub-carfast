"""Merge vehicle document history and audit heads."""

from collections.abc import Sequence


revision: str = "0b1c2d3e4f5a"
down_revision: str | Sequence[str] | None = ("0a1b2c3d4e5f", "ffab0c1d2e3f")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
