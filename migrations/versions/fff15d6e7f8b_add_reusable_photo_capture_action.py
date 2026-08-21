"""Add reusable, versioned take-photo action.

Revision ID: fff15d6e7f8b
Revises: ffd05e6f7a8b
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff15d6e7f8b"
down_revision: str | Sequence[str] | None = "ffd05e6f7a8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "photo_action_definitions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["published_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", "version_number", name="uq_photo_action_definition_version"),
    )
    op.create_index("ix_photo_action_definitions_code", "photo_action_definitions", ["code"])
    op.create_index("ix_photo_action_definitions_status", "photo_action_definitions", ["status"])

    op.create_table(
        "photo_media",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("thumbnail_storage_path", sa.Text(), nullable=False),
        sa.Column("thumbnail_content_type", sa.String(length=120), nullable=False),
        sa.Column("thumbnail_size", sa.Integer(), nullable=False),
        sa.Column("metadata_policy", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index("ix_photo_media_document_id", "photo_media", ["document_id"], unique=True)
    op.create_index("ix_photo_media_sha256", "photo_media", ["sha256"], unique=True)

    op.create_table(
        "photo_capture_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("definition_id", sa.Integer(), nullable=True),
        sa.Column("definition_code", sa.String(length=120), nullable=True),
        sa.Column("definition_version", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("config_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("task_flow_step_id", sa.Integer(), nullable=True),
        sa.Column("workshop_process_id", sa.Integer(), nullable=True),
        sa.Column("phased_process_id", sa.Integer(), nullable=True),
        sa.Column("phase_id", sa.Integer(), nullable=True),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sa.String(length=120), nullable=True),
        sa.Column("entity_id", sa.String(length=120), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("repeats_session_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("submitted_by_id", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["definition_id"], ["photo_action_definitions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["phase_id"], ["workshop_phased_process_phases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["phased_process_id"], ["workshop_phased_processes.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["repeats_session_id"], ["photo_capture_sessions.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["task_flow_step_id"], ["task_guided_flow_step_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["workshop_process_id"], ["workshop_processes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "definition_id",
        "definition_code",
        "status",
        "required",
        "task_id",
        "task_flow_step_id",
        "workshop_process_id",
        "phased_process_id",
        "phase_id",
        "vehicle_id",
        "entity_type",
        "entity_id",
        "repeats_session_id",
    ):
        op.create_index(f"ix_photo_capture_sessions_{column}", "photo_capture_sessions", [column])

    op.create_table(
        "photo_capture_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("photo_media_id", sa.Integer(), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("capture_source", sa.String(length=40), nullable=False),
        sa.Column("is_new_capture", sa.Boolean(), nullable=False),
        sa.Column("captured_by_id", sa.Integer(), nullable=True),
        sa.Column("client_captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("location_latitude", sa.Float(), nullable=True),
        sa.Column("location_longitude", sa.Float(), nullable=True),
        sa.Column("location_accuracy_m", sa.Float(), nullable=True),
        sa.Column("location_consented_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaces_item_id", sa.Integer(), nullable=True),
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("removed_by_id", sa.Integer(), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["captured_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["photo_media_id"], ["photo_media.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["removed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["replaces_item_id"], ["photo_capture_items.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["session_id"], ["photo_capture_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "photo_media_id", name="uq_photo_capture_item_media"),
    )
    for column in (
        "session_id",
        "photo_media_id",
        "category",
        "status",
        "capture_source",
        "captured_at",
    ):
        op.create_index(f"ix_photo_capture_items_{column}", "photo_capture_items", [column])


def downgrade() -> None:
    op.drop_table("photo_capture_items")
    op.drop_table("photo_capture_sessions")
    op.drop_table("photo_media")
    op.drop_table("photo_action_definitions")
