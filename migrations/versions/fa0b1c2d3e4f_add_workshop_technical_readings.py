"""add workshop technical readings

Revision ID: fa0b1c2d3e4f
Revises: f9a0b1c2d3e4
Create Date: 2026-05-18 14:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "fa0b1c2d3e4f"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "workshop_technical_readings" in tables:
        return

    op.create_table(
        "workshop_technical_readings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("reading_type", sa.String(length=80), nullable=False),
        sa.Column("reading_date", sa.Date(), nullable=True),
        sa.Column("odometer_km", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("data_json", sa.JSON(), nullable=True),
        sa.Column("differences_json", sa.JSON(), nullable=True),
        sa.Column("storage_provider", sa.String(length=80), nullable=True),
        sa.Column("external_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_processes.id"], name=op.f("fk_workshop_technical_readings_process_id_workshop_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workshop_technical_readings_user_id_users")),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name=op.f("fk_workshop_technical_readings_vehicle_id_vehicles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_technical_readings")),
    )
    op.create_index(op.f("ix_workshop_technical_readings_process_id"), "workshop_technical_readings", ["process_id"], unique=False)
    op.create_index(op.f("ix_workshop_technical_readings_vehicle_id"), "workshop_technical_readings", ["vehicle_id"], unique=False)
    op.create_index(op.f("ix_workshop_technical_readings_reading_type"), "workshop_technical_readings", ["reading_type"], unique=False)
    op.create_index(op.f("ix_workshop_technical_readings_reading_date"), "workshop_technical_readings", ["reading_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workshop_technical_readings_reading_date"), table_name="workshop_technical_readings")
    op.drop_index(op.f("ix_workshop_technical_readings_reading_type"), table_name="workshop_technical_readings")
    op.drop_index(op.f("ix_workshop_technical_readings_vehicle_id"), table_name="workshop_technical_readings")
    op.drop_index(op.f("ix_workshop_technical_readings_process_id"), table_name="workshop_technical_readings")
    op.drop_table("workshop_technical_readings")
