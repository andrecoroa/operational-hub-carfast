"""Add invoice-derived vehicle service history.

Revision ID: fffd128c9e0f
Revises: fffc017b8d9e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fffd128c9e0f"
down_revision: str | Sequence[str] | None = "fffc017b8d9e"
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
        "invoice_service_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("file_hash", sa.String(128), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("source", sa.String(120), nullable=False, index=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="dry_run", index=True),
        sa.Column("author_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True)),
        sa.Column("summary_json", sa.JSON()),
        sa.Column("differences_json", sa.JSON()),
        *timestamps(),
        sa.UniqueConstraint("file_hash", "version", name="uq_invoice_service_batch_hash_version"),
    )
    op.create_table(
        "invoice_service_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(120), nullable=False, index=True),
        sa.Column("stable_key", sa.String(200), nullable=False, index=True),
        sa.Column(
            "vehicle_id",
            sa.Integer(),
            sa.ForeignKey("vehicles.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workshop_process_id",
            sa.Integer(),
            sa.ForeignKey("workshop_processes.id", ondelete="SET NULL"),
            index=True,
        ),
        sa.Column("service_date", sa.Date(), index=True),
        sa.Column("odometer_km", sa.Integer(), index=True),
        sa.Column("service_code", sa.String(120), nullable=False, index=True),
        sa.Column("service_label", sa.String(200), nullable=False),
        sa.Column("classification", sa.String(120), index=True),
        sa.Column("axle", sa.String(40), index=True),
        sa.Column("position", sa.String(80), index=True),
        sa.Column("supplier_name", sa.String(200), index=True),
        sa.Column("work_order_reference", sa.String(120), index=True),
        sa.Column("work_order_confidence", sa.Numeric(5, 4)),
        sa.Column("amount", sa.Numeric(12, 2)),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column(
            "status", sa.String(40), nullable=False, server_default="auto_extracted", index=True
        ),
        sa.Column("evidence_text", sa.Text()),
        sa.Column("evidence_json", sa.JSON()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true(), index=True),
        sa.Column("validated_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "last_batch_id", sa.Integer(), sa.ForeignKey("invoice_service_import_batches.id")
        ),
        *timestamps(),
        sa.UniqueConstraint("source", "stable_key", name="uq_invoice_service_event_source_key"),
    )
    op.create_table(
        "invoice_service_event_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "event_id",
            sa.Integer(),
            sa.ForeignKey("invoice_service_events.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "batch_id", sa.Integer(), sa.ForeignKey("invoice_service_import_batches.id"), index=True
        ),
        sa.Column("action", sa.String(40), nullable=False, index=True),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("invoice_service_event_revisions")
    op.drop_table("invoice_service_events")
    op.drop_table("invoice_service_import_batches")
