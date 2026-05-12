"""add workshop evidences

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-05-12 10:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c2d3e4f5a6b7"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workshop_process_evidences",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("phase", sa.String(length=80), nullable=False),
        sa.Column("evidence_type", sa.String(length=80), nullable=False),
        sa.Column("anomaly_category", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("storage_provider", sa.String(length=80), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_processes.id"], name=op.f("fk_workshop_process_evidences_process_id_workshop_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workshop_process_evidences_user_id_users")),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name=op.f("fk_workshop_process_evidences_vehicle_id_vehicles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_process_evidences")),
    )
    op.create_index(op.f("ix_workshop_process_evidences_anomaly_category"), "workshop_process_evidences", ["anomaly_category"], unique=False)
    op.create_index(op.f("ix_workshop_process_evidences_evidence_type"), "workshop_process_evidences", ["evidence_type"], unique=False)
    op.create_index(op.f("ix_workshop_process_evidences_phase"), "workshop_process_evidences", ["phase"], unique=False)
    op.create_index(op.f("ix_workshop_process_evidences_process_id"), "workshop_process_evidences", ["process_id"], unique=False)
    op.create_index(op.f("ix_workshop_process_evidences_status"), "workshop_process_evidences", ["status"], unique=False)
    op.create_index(op.f("ix_workshop_process_evidences_vehicle_id"), "workshop_process_evidences", ["vehicle_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workshop_process_evidences_vehicle_id"), table_name="workshop_process_evidences")
    op.drop_index(op.f("ix_workshop_process_evidences_status"), table_name="workshop_process_evidences")
    op.drop_index(op.f("ix_workshop_process_evidences_process_id"), table_name="workshop_process_evidences")
    op.drop_index(op.f("ix_workshop_process_evidences_phase"), table_name="workshop_process_evidences")
    op.drop_index(op.f("ix_workshop_process_evidences_evidence_type"), table_name="workshop_process_evidences")
    op.drop_index(op.f("ix_workshop_process_evidences_anomaly_category"), table_name="workshop_process_evidences")
    op.drop_table("workshop_process_evidences")
