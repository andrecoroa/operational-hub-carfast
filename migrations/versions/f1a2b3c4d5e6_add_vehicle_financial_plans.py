"""Add structured financial plans associated with vehicles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_financial_plans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("import_batch_id", sa.Integer(), sa.ForeignKey("import_batches.id"), nullable=True),
        sa.Column("finance_entity", sa.String(length=160), nullable=False),
        sa.Column("contract_number", sa.String(length=160), nullable=False),
        sa.Column("association_status", sa.String(length=80), nullable=True),
        sa.Column("association_confidence", sa.String(length=40), nullable=True),
        sa.Column("association_method", sa.String(length=40), nullable=True),
        sa.Column("plan_status", sa.String(length=80), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("term_months", sa.Integer(), nullable=True),
        sa.Column("initial_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("outstanding_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("amount_reference_date", sa.Date(), nullable=True),
        sa.Column("installment_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("installment_with_vat", sa.Numeric(14, 2), nullable=True),
        sa.Column("residual_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("source_definition", sa.Text(), nullable=True),
        sa.Column("source_references", sa.Text(), nullable=True),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("human_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confirmed_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("finance_entity", "contract_number", "vehicle_id"),
    )
    op.create_index("ix_vehicle_financial_plans_vehicle_id", "vehicle_financial_plans", ["vehicle_id"])
    op.create_index("ix_vehicle_financial_plans_finance_entity", "vehicle_financial_plans", ["finance_entity"])
    op.create_index("ix_vehicle_financial_plans_contract_number", "vehicle_financial_plans", ["contract_number"])
    op.create_index("ix_vehicle_financial_plans_association_status", "vehicle_financial_plans", ["association_status"])
    op.create_index("ix_vehicle_financial_plans_plan_status", "vehicle_financial_plans", ["plan_status"])
    op.create_index("ix_vehicle_financial_plans_active", "vehicle_financial_plans", ["active"])


def downgrade() -> None:
    op.drop_table("vehicle_financial_plans")
