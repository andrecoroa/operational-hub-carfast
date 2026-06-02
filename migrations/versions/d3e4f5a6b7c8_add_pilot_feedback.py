"""add pilot feedback

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-05-12 11:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pilot_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("source_area", sa.String(length=80), nullable=True),
        sa.Column("entity_type", sa.String(length=120), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("subject", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("current_url", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_pilot_feedback_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pilot_feedback")),
    )
    op.create_index(op.f("ix_pilot_feedback_entity_id"), "pilot_feedback", ["entity_id"], unique=False)
    op.create_index(op.f("ix_pilot_feedback_entity_type"), "pilot_feedback", ["entity_type"], unique=False)
    op.create_index(op.f("ix_pilot_feedback_kind"), "pilot_feedback", ["kind"], unique=False)
    op.create_index(op.f("ix_pilot_feedback_source_area"), "pilot_feedback", ["source_area"], unique=False)
    op.create_index(op.f("ix_pilot_feedback_status"), "pilot_feedback", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pilot_feedback_status"), table_name="pilot_feedback")
    op.drop_index(op.f("ix_pilot_feedback_source_area"), table_name="pilot_feedback")
    op.drop_index(op.f("ix_pilot_feedback_kind"), table_name="pilot_feedback")
    op.drop_index(op.f("ix_pilot_feedback_entity_type"), table_name="pilot_feedback")
    op.drop_index(op.f("ix_pilot_feedback_entity_id"), table_name="pilot_feedback")
    op.drop_table("pilot_feedback")
