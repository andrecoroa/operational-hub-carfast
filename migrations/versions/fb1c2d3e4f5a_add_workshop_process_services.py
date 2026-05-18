"""add workshop process services

Revision ID: fb1c2d3e4f5a
Revises: fa0b1c2d3e4f
Create Date: 2026-05-19 09:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "fb1c2d3e4f5a"
down_revision = "fa0b1c2d3e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "workshop_process_services" in tables:
        return

    op.create_table(
        "workshop_process_services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("service_family", sa.String(length=80), nullable=False),
        sa.Column("service_detail", sa.String(length=120), nullable=True),
        sa.Column("service_axis", sa.String(length=80), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_workshop_process_services_created_by_id_users")),
        sa.ForeignKeyConstraint(["process_id"], ["workshop_processes.id"], name=op.f("fk_workshop_process_services_process_id_workshop_processes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], name=op.f("fk_workshop_process_services_vehicle_id_vehicles"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workshop_process_services")),
    )
    for column in ["process_id", "vehicle_id", "service_family", "service_detail", "service_axis", "status"]:
        op.create_index(op.f(f"ix_workshop_process_services_{column}"), "workshop_process_services", [column], unique=False)


def downgrade() -> None:
    for column in ["status", "service_axis", "service_detail", "service_family", "vehicle_id", "process_id"]:
        op.drop_index(op.f(f"ix_workshop_process_services_{column}"), table_name="workshop_process_services")
    op.drop_table("workshop_process_services")
