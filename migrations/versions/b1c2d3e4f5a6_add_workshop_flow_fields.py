"""add workshop flow fields

Revision ID: b1c2d3e4f5a6
Revises: 8b7f0c3d2a1e
Create Date: 2026-05-12 00:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b1c2d3e4f5a6"
down_revision = "8b7f0c3d2a1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workshop_processes", sa.Column("opening_type", sa.String(length=80), nullable=True))
    op.add_column("workshop_processes", sa.Column("km_entry", sa.Integer(), nullable=True))
    op.add_column("workshop_processes", sa.Column("decision", sa.String(length=80), nullable=True))
    op.add_column("workshop_processes", sa.Column("decision_note", sa.Text(), nullable=True))
    op.add_column("workshop_processes", sa.Column("decided_by_id", sa.Integer(), nullable=True))
    op.add_column("workshop_processes", sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_workshop_processes_opening_type"), "workshop_processes", ["opening_type"], unique=False)
    op.create_index(op.f("ix_workshop_processes_decision"), "workshop_processes", ["decision"], unique=False)
    op.execute("UPDATE workshop_processes SET status = 'opening' WHERE status = 'open'")


def downgrade() -> None:
    op.execute("UPDATE workshop_processes SET status = 'open' WHERE status = 'opening'")
    op.drop_index(op.f("ix_workshop_processes_decision"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_opening_type"), table_name="workshop_processes")
    op.drop_column("workshop_processes", "decided_at")
    op.drop_column("workshop_processes", "decided_by_id")
    op.drop_column("workshop_processes", "decision_note")
    op.drop_column("workshop_processes", "decision")
    op.drop_column("workshop_processes", "km_entry")
    op.drop_column("workshop_processes", "opening_type")
