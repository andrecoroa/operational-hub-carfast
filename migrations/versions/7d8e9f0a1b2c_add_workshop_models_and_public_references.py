"""Add Workshop Clean references, templates, diagnostics and Stock contract.

Revision ID: 7d8e9f0a1b2c
Revises: 6c7d8e9f0a1b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7d8e9f0a1b2c"
down_revision: str | Sequence[str] | None = "6c7d8e9f0a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workshop_public_counters",
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("year"),
    )
    op.create_table(
        "workshop_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entry_reason_code", sa.String(length=80), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workshop_templates_code", "workshop_templates", ["code"], unique=True)
    op.create_index(
        "ix_workshop_templates_entry_reason_code",
        "workshop_templates",
        ["entry_reason_code"],
    )
    op.create_index("ix_workshop_templates_active", "workshop_templates", ["active"])

    op.create_table(
        "workshop_template_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="published"),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by_id", sa.Integer(), nullable=True),
        sa.Column("stock_template_code", sa.String(length=120), nullable=True),
        sa.Column("stock_template_version", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["published_by_id"],
            ["users.id"],
            name="fk_workshop_template_versions_published_by",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["workshop_templates.id"],
            name="fk_workshop_template_versions_template",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "version_number", name="uq_workshop_template_version"),
    )
    op.create_index(
        "ix_workshop_template_versions_template_id",
        "workshop_template_versions",
        ["template_id"],
    )
    op.create_index(
        "ix_workshop_template_versions_status",
        "workshop_template_versions",
        ["status"],
    )

    with op.batch_alter_table("workshop_phased_processes") as batch_op:
        batch_op.add_column(sa.Column("public_reference", sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("template_version_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("template_snapshot_json", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "fk_workshop_process_template_version",
            "workshop_template_versions",
            ["template_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_workshop_phased_processes_public_reference",
            ["public_reference"],
            unique=True,
        )
        batch_op.create_index("ix_workshop_phased_processes_opened_at", ["opened_at"])

    op.create_table(
        "workshop_diagnostic_catalog_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column("family", sa.String(length=120), nullable=False),
        sa.Column("equipment", sa.String(length=160), nullable=True),
        sa.Column("applicability_json", sa.JSON(), nullable=True),
        sa.Column(
            "phase_code", sa.String(length=120), nullable=False, server_default="diagnostico"
        ),
        sa.Column(
            "requirement", sa.String(length=40), nullable=False, server_default="recommended"
        ),
        sa.Column("validity_days", sa.Integer(), nullable=True),
        sa.Column("history_rules_json", sa.JSON(), nullable=True),
        sa.Column("expected_document_type", sa.String(length=120), nullable=True),
        sa.Column("extraction_fields_json", sa.JSON(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_workshop_diagnostic_catalog_items_code",
        "workshop_diagnostic_catalog_items",
        ["code"],
        unique=True,
    )
    op.create_index(
        "ix_workshop_diagnostic_catalog_items_family",
        "workshop_diagnostic_catalog_items",
        ["family"],
    )
    op.create_index(
        "ix_workshop_diagnostic_catalog_items_phase_code",
        "workshop_diagnostic_catalog_items",
        ["phase_code"],
    )
    op.create_index(
        "ix_workshop_diagnostic_catalog_items_requirement",
        "workshop_diagnostic_catalog_items",
        ["requirement"],
    )
    op.create_index(
        "ix_workshop_diagnostic_catalog_items_active",
        "workshop_diagnostic_catalog_items",
        ["active"],
    )

    op.create_table(
        "workshop_diagnostic_suggestions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("catalog_item_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="suggested"),
        sa.Column("origin", sa.String(length=80), nullable=False, server_default="rules_engine"),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("rule_context_json", sa.JSON(), nullable=True),
        sa.Column("confirmed_by_id", sa.Integer(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["workshop_diagnostic_catalog_items.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["confirmed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_phased_processes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "process_id",
            "catalog_item_id",
            name="uq_workshop_diagnostic_suggestion",
        ),
    )
    op.create_index(
        "ix_workshop_diagnostic_suggestions_process_id",
        "workshop_diagnostic_suggestions",
        ["process_id"],
    )
    op.create_index(
        "ix_workshop_diagnostic_suggestions_catalog_item_id",
        "workshop_diagnostic_suggestions",
        ["catalog_item_id"],
    )
    op.create_index(
        "ix_workshop_diagnostic_suggestions_status",
        "workshop_diagnostic_suggestions",
        ["status"],
    )
    op.create_index(
        "ix_workshop_diagnostic_suggestions_origin",
        "workshop_diagnostic_suggestions",
        ["origin"],
    )

    op.create_table(
        "workshop_material_needs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("phase_code", sa.String(length=120), nullable=False),
        sa.Column("origin", sa.String(length=40), nullable=False),
        sa.Column("operation_code", sa.String(length=120), nullable=False),
        sa.Column("operation_label", sa.String(length=180), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=True),
        sa.Column("vehicle_variant", sa.String(length=180), nullable=True),
        sa.Column("technician_user_id", sa.Integer(), nullable=True),
        sa.Column("location_id", sa.Integer(), nullable=True),
        sa.Column("material_code", sa.String(length=120), nullable=True),
        sa.Column("material_description", sa.String(length=240), nullable=False),
        sa.Column("requested_quantity", sa.String(length=80), nullable=True),
        sa.Column(
            "stock_status", sa.String(length=40), nullable=False, server_default="unavailable"
        ),
        sa.Column("stock_request_reference", sa.String(length=120), nullable=True),
        sa.Column("applied_confirmed_by_id", sa.Integer(), nullable=True),
        sa.Column("applied_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["applied_confirmed_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["location_id"], ["organizational_units.id"]),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_phased_processes.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["technician_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "process_id",
        "phase_code",
        "origin",
        "operation_code",
        "material_code",
        "stock_status",
        "stock_request_reference",
    ):
        op.create_index(
            f"ix_workshop_material_needs_{column}",
            "workshop_material_needs",
            [column],
        )


def downgrade() -> None:
    op.drop_table("workshop_material_needs")
    op.drop_table("workshop_diagnostic_suggestions")
    op.drop_table("workshop_diagnostic_catalog_items")
    with op.batch_alter_table("workshop_phased_processes") as batch_op:
        batch_op.drop_index("ix_workshop_phased_processes_opened_at")
        batch_op.drop_index("ix_workshop_phased_processes_public_reference")
        batch_op.drop_constraint("fk_workshop_process_template_version", type_="foreignkey")
        batch_op.drop_column("template_snapshot_json")
        batch_op.drop_column("template_version_id")
        batch_op.drop_column("opened_at")
        batch_op.drop_column("public_reference")
    op.drop_table("workshop_template_versions")
    op.drop_table("workshop_templates")
    op.drop_table("workshop_public_counters")
