"""Normalize vehicle gearbox to Manual or Automática.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c6d7e8f9a0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


AUTOMATIC_GROUPS = (
    "B3", "C2", "C4", "C5", "D2", "D4", "E2", "G2", "G3", "I2", "J1", "J2", "J3", "L2",
)


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE vehicles SET rentway_gearbox = CASE "
            "WHEN UPPER(rentway_gearbox) LIKE '%MANUAL%' "
            "OR UPPER(rentway_gearbox) LIKE '%CVM%' "
            "OR UPPER(rentway_gearbox) LIKE '%BVM%' THEN 'Manual' "
            "WHEN UPPER(rentway_gearbox) LIKE '%AUTO%' "
            "OR UPPER(rentway_gearbox) LIKE '%EAT%' "
            "OR UPPER(rentway_gearbox) LIKE '%DSG%' "
            "OR UPPER(rentway_gearbox) LIKE '%DCT%' "
            "OR UPPER(rentway_gearbox) LIKE '%CVT%' "
            "OR UPPER(rentway_gearbox) LIKE '%EDC%' THEN 'Automática' "
            "ELSE NULL END"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE vehicles SET rentway_gearbox='Automática' "
            "WHERE rentway_gearbox IS NULL AND UPPER(TRIM(rentway_group)) IN :groups"
        ).bindparams(sa.bindparam("groups", expanding=True)),
        {"groups": AUTOMATIC_GROUPS},
    )


def downgrade() -> None:
    pass
