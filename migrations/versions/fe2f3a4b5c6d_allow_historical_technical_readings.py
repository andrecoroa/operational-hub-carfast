"""Allow historical technical readings without workshop process."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "fe2f3a4b5c6d"
down_revision: str | Sequence[str] | None = "fd1e2f3a4b5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    foreign_keys = inspector.get_foreign_keys("workshop_technical_readings")

    for foreign_key in foreign_keys:
        if (
            foreign_key.get("constrained_columns") == ["process_id"]
            and foreign_key.get("referred_table") == "workshop_processes"
        ):
            op.drop_constraint(foreign_key["name"], "workshop_technical_readings", type_="foreignkey")
            break

    op.alter_column("workshop_technical_readings", "process_id", existing_type=sa.Integer(), nullable=True)
    op.create_foreign_key(
        op.f("fk_workshop_technical_readings_process_id_workshop_processes"),
        "workshop_technical_readings",
        "workshop_processes",
        ["process_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_workshop_technical_readings_process_id_workshop_processes"),
        "workshop_technical_readings",
        type_="foreignkey",
    )
    op.alter_column("workshop_technical_readings", "process_id", existing_type=sa.Integer(), nullable=False)
    op.create_foreign_key(
        op.f("fk_workshop_technical_readings_process_id_workshop_processes"),
        "workshop_technical_readings",
        "workshop_processes",
        ["process_id"],
        ["id"],
        ondelete="CASCADE",
    )
