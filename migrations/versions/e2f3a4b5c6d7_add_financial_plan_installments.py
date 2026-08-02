"""Add monthly installments to vehicle financial plans."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_financial_plan_installments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "financial_plan_id",
            sa.Integer(),
            sa.ForeignKey("vehicle_financial_plans.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("period_number", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("amortization_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("interest_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("installment_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("outstanding_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("outstanding_with_vat", sa.Numeric(14, 2), nullable=True),
        sa.Column("source_label", sa.String(255), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("financial_plan_id", "period_number"),
    )
    op.create_index(
        "ix_vehicle_financial_plan_installments_financial_plan_id",
        "vehicle_financial_plan_installments",
        ["financial_plan_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vehicle_financial_plan_installments_financial_plan_id",
        table_name="vehicle_financial_plan_installments",
    )
    op.drop_table("vehicle_financial_plan_installments")
