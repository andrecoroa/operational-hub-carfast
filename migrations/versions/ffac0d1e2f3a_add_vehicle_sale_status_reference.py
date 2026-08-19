"""Add proposal lot reference to vehicle sale status."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffac0d1e2f3a"
down_revision: str | Sequence[str] | None = "ec0c1d2e3f4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "vehicle_sale_profiles",
        sa.Column("status_reference", sa.String(length=120), nullable=True),
    )
    op.create_index(
        op.f("ix_vehicle_sale_profiles_status_reference"),
        "vehicle_sale_profiles",
        ["status_reference"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_vehicle_sale_profiles_status_reference"),
        table_name="vehicle_sale_profiles",
    )
    op.drop_column("vehicle_sale_profiles", "status_reference")
