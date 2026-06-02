"""extend task operational fields

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-05-12 12:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("source", sa.String(length=80), nullable=True))
    op.add_column("tasks", sa.Column("subcategory", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("customer_name", sa.String(length=200), nullable=True))
    op.add_column("tasks", sa.Column("customer_contact", sa.String(length=200), nullable=True))
    op.add_column("tasks", sa.Column("customer_email", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("customer_phone", sa.String(length=80), nullable=True))
    op.add_column("tasks", sa.Column("plate", sa.String(length=40), nullable=True))
    op.add_column("tasks", sa.Column("reservation_number", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("contract_number", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("station", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("department", sa.String(length=120), nullable=True))
    op.add_column("tasks", sa.Column("external_source_id", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("parent_task_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("first_response_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(op.f("fk_tasks_parent_task_id_tasks"), "tasks", "tasks", ["parent_task_id"], ["id"])
    op.create_index(op.f("ix_tasks_contract_number"), "tasks", ["contract_number"], unique=False)
    op.create_index(op.f("ix_tasks_customer_email"), "tasks", ["customer_email"], unique=False)
    op.create_index(op.f("ix_tasks_customer_name"), "tasks", ["customer_name"], unique=False)
    op.create_index(op.f("ix_tasks_customer_phone"), "tasks", ["customer_phone"], unique=False)
    op.create_index(op.f("ix_tasks_department"), "tasks", ["department"], unique=False)
    op.create_index(op.f("ix_tasks_external_source_id"), "tasks", ["external_source_id"], unique=False)
    op.create_index(op.f("ix_tasks_plate"), "tasks", ["plate"], unique=False)
    op.create_index(op.f("ix_tasks_reservation_number"), "tasks", ["reservation_number"], unique=False)
    op.create_index(op.f("ix_tasks_source"), "tasks", ["source"], unique=False)
    op.create_index(op.f("ix_tasks_station"), "tasks", ["station"], unique=False)
    op.create_index(op.f("ix_tasks_subcategory"), "tasks", ["subcategory"], unique=False)
    op.execute("UPDATE tasks SET source = 'manual' WHERE source IS NULL")
    op.execute("UPDATE tasks SET status = 'closed' WHERE status = 'done'")
    op.execute("UPDATE tasks SET status = 'in_treatment' WHERE status = 'in_progress'")


def downgrade() -> None:
    op.execute("UPDATE tasks SET status = 'done' WHERE status = 'closed'")
    op.execute("UPDATE tasks SET status = 'in_progress' WHERE status = 'in_treatment'")
    op.drop_index(op.f("ix_tasks_subcategory"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_station"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_source"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_reservation_number"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_plate"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_external_source_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_department"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_customer_phone"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_customer_name"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_customer_email"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_contract_number"), table_name="tasks")
    op.drop_constraint(op.f("fk_tasks_parent_task_id_tasks"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "resolved_at")
    op.drop_column("tasks", "first_response_at")
    op.drop_column("tasks", "parent_task_id")
    op.drop_column("tasks", "external_source_id")
    op.drop_column("tasks", "department")
    op.drop_column("tasks", "station")
    op.drop_column("tasks", "contract_number")
    op.drop_column("tasks", "reservation_number")
    op.drop_column("tasks", "plate")
    op.drop_column("tasks", "customer_phone")
    op.drop_column("tasks", "customer_email")
    op.drop_column("tasks", "customer_contact")
    op.drop_column("tasks", "customer_name")
    op.drop_column("tasks", "subcategory")
    op.drop_column("tasks", "source")
