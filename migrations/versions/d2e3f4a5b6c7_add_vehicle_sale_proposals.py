"""Add versioned vehicle sale proposals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_sale_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("previous_version_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("recipient", sa.String(length=200), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["previous_version_id"], ["vehicle_sale_proposals.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reference"),
    )
    op.create_index("ix_vehicle_sale_proposals_reference", "vehicle_sale_proposals", ["reference"], unique=True)
    op.create_index("ix_vehicle_sale_proposals_status", "vehicle_sale_proposals", ["status"])

    op.create_table(
        "vehicle_sale_proposal_lines",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("proposal_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("base_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("proposed_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("included", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["proposal_id"], ["vehicle_sale_proposals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("proposal_id", "vehicle_id"),
    )
    op.create_index("ix_vehicle_sale_proposal_lines_proposal_id", "vehicle_sale_proposal_lines", ["proposal_id"])
    op.create_index("ix_vehicle_sale_proposal_lines_vehicle_id", "vehicle_sale_proposal_lines", ["vehicle_id"])


def downgrade() -> None:
    op.drop_index("ix_vehicle_sale_proposal_lines_vehicle_id", table_name="vehicle_sale_proposal_lines")
    op.drop_index("ix_vehicle_sale_proposal_lines_proposal_id", table_name="vehicle_sale_proposal_lines")
    op.drop_table("vehicle_sale_proposal_lines")
    op.drop_index("ix_vehicle_sale_proposals_status", table_name="vehicle_sale_proposals")
    op.drop_index("ix_vehicle_sale_proposals_reference", table_name="vehicle_sale_proposals")
    op.drop_table("vehicle_sale_proposals")
