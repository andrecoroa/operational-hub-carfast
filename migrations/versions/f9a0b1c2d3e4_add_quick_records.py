"""add quick records

Revision ID: f9a0b1c2d3e4
Revises: f8a9b0c1d2e3
Create Date: 2026-05-18 10:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f9a0b1c2d3e4"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "quick_records" in tables:
        return

    op.create_table(
        "quick_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace", sa.String(length=80), nullable=False),
        sa.Column("record_type", sa.String(length=80), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("priority", sa.String(length=80), nullable=True),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("customer_contact", sa.String(length=200), nullable=True),
        sa.Column("customer_email", sa.String(length=255), nullable=True),
        sa.Column("customer_phone", sa.String(length=80), nullable=True),
        sa.Column("plate", sa.String(length=40), nullable=True),
        sa.Column("station", sa.String(length=120), nullable=True),
        sa.Column("entity_type", sa.String(length=120), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("assigned_to_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("converted_task_id", sa.Integer(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to_id"], ["users.id"], name=op.f("fk_quick_records_assigned_to_id_users")),
        sa.ForeignKeyConstraint(["converted_task_id"], ["tasks.id"], name=op.f("fk_quick_records_converted_task_id_tasks")),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], name=op.f("fk_quick_records_created_by_id_users")),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name=op.f("fk_quick_records_team_id_teams")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quick_records")),
    )
    for column in [
        "workspace",
        "record_type",
        "status",
        "priority",
        "source",
        "customer_name",
        "customer_email",
        "customer_phone",
        "plate",
        "station",
        "entity_type",
        "entity_id",
    ]:
        op.create_index(op.f(f"ix_quick_records_{column}"), "quick_records", [column], unique=False)


def downgrade() -> None:
    op.drop_table("quick_records")
