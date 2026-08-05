"""Backfill automatic gearbox from Rentway groups.

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c6d7e8f9a0b1"
down_revision: str | Sequence[str] | None = "b5c6d7e8f9a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AUTOMATIC_GROUPS = (
    "B3", "C2", "C4", "C5", "D2", "D4", "E2", "G2", "G3", "I2", "J1", "J2", "J3", "L2",
)


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE vehicles SET rentway_gearbox='Automática' "
            "WHERE (rentway_gearbox IS NULL OR TRIM(rentway_gearbox)='') "
            "AND UPPER(TRIM(rentway_group)) IN :groups"
        ).bindparams(sa.bindparam("groups", expanding=True)),
        {"groups": AUTOMATIC_GROUPS},
    )


def downgrade() -> None:
    # The inferred value is valid business data and cannot be distinguished
    # safely from a user-confirmed automatic gearbox during downgrade.
    pass
