"""add transversal provisional classification proposals

Revision ID: ffd05e6f7a8b
Revises: ffcf2a3b4c5d
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffd05e6f7a8b"
down_revision: str | Sequence[str] | None = "ffe04c5d6e7f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "classification.active.use": "Usar classificações ativas",
    "classification.propose": "Propor nova categoria ou subcategoria",
    "classification.provisional.use": "Usar classificações provisórias",
    "classification.validate": "Validar propostas de classificação",
    "classification.merge_reclassify": "Fundir propostas e reclassificar utilizações",
    "classification.catalog.manage": "Administrar catálogo de classificações",
}


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    op.create_table(
        "classification_sequences",
        sa.Column("scope", sa.String(80), primary_key=True),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_table(
        "classification_proposals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("provisional_code", sa.String(40), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("proposed_name", sa.String(160), nullable=False),
        sa.Column("normalized_name", sa.String(160), nullable=False),
        sa.Column("hierarchy_key", sa.String(80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("work_departments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("work_categories.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "parent_proposal_id",
            sa.Integer(),
            sa.ForeignKey("classification_proposals.id", ondelete="RESTRICT"),
        ),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("proposed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("origin_module", sa.String(80), nullable=False),
        sa.Column("origin_url", sa.String(500)),
        sa.Column("origin_reference", sa.String(160)),
        sa.Column(
            "evolution_record_id",
            sa.Integer(),
            sa.ForeignKey("evolution_records.id", ondelete="SET NULL"),
        ),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("decision_notes", sa.Text()),
        sa.Column(
            "definitive_category_id",
            sa.Integer(),
            sa.ForeignKey("work_categories.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "definitive_subcategory_id",
            sa.Integer(),
            sa.ForeignKey("work_subcategories.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "merged_into_proposal_id",
            sa.Integer(),
            sa.ForeignKey("classification_proposals.id", ondelete="RESTRICT"),
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "kind IN ('category', 'subcategory')", name="ck_classification_proposals_kind"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'observation', 'approved', 'linked', 'merged', "
            "'rejected', 'archived')",
            name="ck_classification_proposals_status",
        ),
        sa.CheckConstraint(
            "(kind = 'category' AND department_id IS NOT NULL AND category_id IS NULL) OR "
            "(kind = 'subcategory' AND department_id IS NOT NULL AND "
            "(category_id IS NOT NULL OR parent_proposal_id IS NOT NULL))",
            name="ck_classification_proposals_hierarchy",
        ),
        sa.UniqueConstraint("provisional_code", name="uq_classification_proposals_code"),
        sa.UniqueConstraint("evolution_record_id", name="uq_classification_proposals_evolution"),
    )
    for column in (
        "provisional_code",
        "kind",
        "proposed_name",
        "normalized_name",
        "hierarchy_key",
        "department_id",
        "category_id",
        "parent_proposal_id",
        "status",
        "active",
        "proposed_by_id",
        "origin_module",
        "origin_reference",
        "evolution_record_id",
        "usage_count",
        "last_used_at",
        "reviewed_by_id",
        "reviewed_at",
        "definitive_category_id",
        "definitive_subcategory_id",
        "merged_into_proposal_id",
    ):
        op.create_index(
            f"ix_classification_proposals_{column}", "classification_proposals", [column]
        )
    op.create_index(
        "uq_classification_proposals_open_normalized_hierarchy",
        "classification_proposals",
        ["kind", "hierarchy_key", "normalized_name"],
        unique=True,
        postgresql_where=sa.text("active"),
        sqlite_where=sa.text("active = 1"),
    )
    op.create_table(
        "classification_proposal_usages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("classification_proposals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("module", sa.String(80), nullable=False),
        sa.Column("origin_url", sa.String(500)),
        sa.Column("first_used_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("last_used_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resolved_action", sa.String(40)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.CheckConstraint(
            "entity_type IN ('task', 'email_thread')",
            name="ck_classification_proposal_usages_entity_type",
        ),
        sa.UniqueConstraint(
            "proposal_id",
            "entity_type",
            "entity_id",
            name="uq_classification_proposal_usage",
        ),
    )
    for column in (
        "proposal_id",
        "entity_type",
        "entity_id",
        "module",
        "first_used_by_id",
        "last_used_by_id",
        "active",
        "resolved_action",
        "resolved_at",
    ):
        op.create_index(
            f"ix_classification_proposal_usages_{column}",
            "classification_proposal_usages",
            [column],
        )
    op.create_table(
        "classification_proposal_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("classification_proposals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("details", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("proposal_id", "actor_user_id", "action", "created_at"):
        op.create_index(
            f"ix_classification_proposal_audits_{column}",
            "classification_proposal_audits",
            [column],
        )

    for table in ("tasks", "email_threads"):
        op.add_column(
            table,
            sa.Column(
                "provisional_category_id",
                sa.Integer(),
                sa.ForeignKey("classification_proposals.id", ondelete="RESTRICT"),
            ),
        )
        op.add_column(
            table,
            sa.Column(
                "provisional_subcategory_id",
                sa.Integer(),
                sa.ForeignKey("classification_proposals.id", ondelete="RESTRICT"),
            ),
        )
        op.create_index(f"ix_{table}_provisional_category_id", table, ["provisional_category_id"])
        op.create_index(
            f"ix_{table}_provisional_subcategory_id", table, ["provisional_subcategory_id"]
        )
    op.add_column(
        "email_threads",
        sa.Column(
            "classification_updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
    )
    op.add_column(
        "email_threads", sa.Column("classification_updated_at", sa.DateTime(timezone=True))
    )

    for code, name in PERMISSIONS.items():
        escaped_code = code.replace("'", "''")
        escaped_name = name.replace("'", "''")
        op.execute(
            "INSERT INTO permissions (code, name, description) "
            f"VALUES ('{escaped_code}', '{escaped_name}', NULL) ON CONFLICT (code) DO NOTHING"
        )
    all_codes = "', '".join(PERMISSIONS)
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.code = 'admin' "
        f"AND permissions.code IN ('{all_codes}') "
        "ON CONFLICT (role_id, permission_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT DISTINCT rp.role_id, p_new.id FROM role_permissions rp "
        "JOIN permissions p_old ON p_old.id = rp.permission_id "
        "JOIN permissions p_new ON p_new.code = 'classification.active.use' "
        "WHERE p_old.code IN ('tasks.write', 'tasks.operational.write', "
        "'service_desk.create', 'service_desk.update', 'email.triage') "
        "ON CONFLICT (role_id, permission_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.code IN ('functional_admin', 'manager', 'operator') "
        "AND permissions.code IN ('classification.propose', 'classification.provisional.use') "
        "ON CONFLICT (role_id, permission_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.code = 'functional_admin' "
        "AND permissions.code IN ('classification.validate', "
        "'classification.merge_reclassify', 'classification.catalog.manage') "
        "ON CONFLICT (role_id, permission_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code LIKE 'classification.%')"
    )
    op.execute("DELETE FROM permissions WHERE code LIKE 'classification.%'")
    op.drop_column("email_threads", "classification_updated_at")
    op.drop_column("email_threads", "classification_updated_by_id")
    for table in ("email_threads", "tasks"):
        op.drop_index(f"ix_{table}_provisional_subcategory_id", table_name=table)
        op.drop_index(f"ix_{table}_provisional_category_id", table_name=table)
        op.drop_column(table, "provisional_subcategory_id")
        op.drop_column(table, "provisional_category_id")
    op.drop_table("classification_proposal_audits")
    op.drop_table("classification_proposal_usages")
    op.drop_table("classification_proposals")
    op.drop_table("classification_sequences")
