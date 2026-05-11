"""add workshop processes

Revision ID: 8b7f0c3d2a1e
Revises: 4eaddbe5f0a7
Create Date: 2026-05-11 23:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "8b7f0c3d2a1e"
down_revision = "4eaddbe5f0a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "workshop_processes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("opened_by_id", sa.Integer(), nullable=True),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("expected_exit_on", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["opened_by_id"], ["users.id"], name=op.f("fk_workshop_processes_opened_by_id_users")),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name=op.f("fk_workshop_processes_vehicle_id_vehicles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_processes")),
    )
    op.create_index(op.f("ix_workshop_processes_priority"), "workshop_processes", ["priority"], unique=False)
    op.create_index(op.f("ix_workshop_processes_source"), "workshop_processes", ["source"], unique=False)
    op.create_index(op.f("ix_workshop_processes_status"), "workshop_processes", ["status"], unique=False)
    op.create_index(op.f("ix_workshop_processes_vehicle_id"), "workshop_processes", ["vehicle_id"], unique=False)

    op.create_table(
        "workshop_process_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_processes.id"], name=op.f("fk_workshop_process_notes_process_id_workshop_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workshop_process_notes_user_id_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_process_notes")),
    )


def downgrade() -> None:
    op.drop_table("workshop_process_notes")
    op.drop_index(op.f("ix_workshop_processes_vehicle_id"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_status"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_source"), table_name="workshop_processes")
    op.drop_index(op.f("ix_workshop_processes_priority"), table_name="workshop_processes")
    op.drop_table("workshop_processes")
