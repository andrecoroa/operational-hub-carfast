"""Add workshop technical reading correction fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "ff2a3b4c5d6e"
down_revision: str | Sequence[str] | None = "fe2f3a4b5c6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workshop_technical_readings",
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
    )
    op.add_column("workshop_technical_readings", sa.Column("replaced_by_id", sa.Integer(), nullable=True))
    op.add_column("workshop_technical_readings", sa.Column("void_reason", sa.Text(), nullable=True))
    op.add_column("workshop_technical_readings", sa.Column("updated_by_id", sa.Integer(), nullable=True))
    op.add_column("workshop_technical_readings", sa.Column("voided_by_id", sa.Integer(), nullable=True))
    op.add_column(
        "workshop_technical_readings",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_workshop_technical_readings_status"),
        "workshop_technical_readings",
        ["status"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_workshop_technical_readings_replaced_by_id_workshop_technical_readings"),
        "workshop_technical_readings",
        "workshop_technical_readings",
        ["replaced_by_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_workshop_technical_readings_updated_by_id_users"),
        "workshop_technical_readings",
        "users",
        ["updated_by_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("fk_workshop_technical_readings_voided_by_id_users"),
        "workshop_technical_readings",
        "users",
        ["voided_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_workshop_technical_readings_voided_by_id_users"),
        "workshop_technical_readings",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_workshop_technical_readings_updated_by_id_users"),
        "workshop_technical_readings",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_workshop_technical_readings_replaced_by_id_workshop_technical_readings"),
        "workshop_technical_readings",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_workshop_technical_readings_status"), table_name="workshop_technical_readings")
    op.drop_column("workshop_technical_readings", "voided_at")
    op.drop_column("workshop_technical_readings", "voided_by_id")
    op.drop_column("workshop_technical_readings", "updated_by_id")
    op.drop_column("workshop_technical_readings", "void_reason")
    op.drop_column("workshop_technical_readings", "replaced_by_id")
    op.drop_column("workshop_technical_readings", "status")
