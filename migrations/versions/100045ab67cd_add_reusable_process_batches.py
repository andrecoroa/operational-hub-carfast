"""Add resumable spreadsheet batches to reusable process cases.

Revision ID: 100045ab67cd
Revises: ffff34ae102b
"""

import sqlalchemy as sa
from alembic import op

revision = "100045ab67cd"
down_revision = "ffff34ae102b"
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "process_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("task_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "process_instance_id",
            sa.Integer(),
            sa.ForeignKey("process_instances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "import_file_id", sa.Integer(), sa.ForeignKey("import_files.id", ondelete="RESTRICT")
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('draft','mapped','validated','in_progress','completed','cancelled')",
            name="ck_process_batches_status",
        ),
    )
    for column in ("case_id", "process_instance_id", "import_file_id", "status"):
        op.create_index(f"ix_process_batches_{column}", "process_batches", [column])

    op.create_table(
        "process_batch_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_id",
            sa.Integer(),
            sa.ForeignKey("process_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("row_key", sa.String(160)),
        sa.Column("source_json", sa.JSON(), nullable=False),
        sa.Column("treatment_json", sa.JSON(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        *timestamps(),
        sa.UniqueConstraint("batch_id", "row_number", name="uq_process_batch_row_number"),
        sa.CheckConstraint(
            "status IN ('pending','ready','in_progress','completed','excluded','error')",
            name="ck_process_batch_rows_status",
        ),
    )
    for column in ("batch_id", "row_key", "status"):
        op.create_index(f"ix_process_batch_rows_{column}", "process_batch_rows", [column])

    op.create_table(
        "process_batch_task_rows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "batch_row_id",
            sa.Integer(),
            sa.ForeignKey("process_batch_rows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("linked_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *timestamps(),
        sa.UniqueConstraint("batch_row_id", name="uq_process_batch_task_row_assignment"),
        sa.UniqueConstraint("task_id", "batch_row_id", name="uq_process_batch_task_row"),
    )
    op.create_index("ix_process_batch_task_rows_task_id", "process_batch_task_rows", ["task_id"])
    op.create_index(
        "ix_process_batch_task_rows_batch_row_id", "process_batch_task_rows", ["batch_row_id"]
    )

    op.create_table(
        "process_batch_row_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "batch_row_id",
            sa.Integer(),
            sa.ForeignKey("process_batch_rows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_process_batch_row_comments_batch_row_id", "process_batch_row_comments", ["batch_row_id"]
    )
    op.create_index(
        "ix_process_batch_row_comments_task_id", "process_batch_row_comments", ["task_id"]
    )


def downgrade() -> None:
    op.drop_table("process_batch_row_comments")
    op.drop_table("process_batch_task_rows")
    op.drop_table("process_batch_rows")
    op.drop_table("process_batches")
