"""add customer counteroffer to proposal lines

Revision ID: e9f0a1b2c3d4
Revises: e8f9a0b1c2d3
"""

from alembic import op
import sqlalchemy as sa


revision = "e9f0a1b2c3d4"
down_revision = "e8f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vehicle_sale_proposal_lines",
        sa.Column("customer_counteroffer", sa.Numeric(14, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vehicle_sale_proposal_lines", "customer_counteroffer")
