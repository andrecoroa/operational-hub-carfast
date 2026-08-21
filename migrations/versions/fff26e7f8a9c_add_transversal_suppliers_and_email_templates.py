"""Add transversal supplier records and simple supplier email templates.

Revision ID: fff26e7f8a9c
Revises: fff15d6e7f8b
Create Date: 2026-08-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff26e7f8a9c"
down_revision: str | Sequence[str] | None = "fff15d6e7f8b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
    )


def upgrade() -> None:
    for name, column in (
        ("address_line2", sa.Column("address_line2", sa.String(200), nullable=True)),
        ("postal_code", sa.Column("postal_code", sa.String(40), nullable=True)),
        ("city", sa.Column("city", sa.String(120), nullable=True)),
        ("country_code", sa.Column("country_code", sa.String(2), nullable=True)),
        ("legal_name", sa.Column("legal_name", sa.String(240), nullable=True)),
        ("registration_number", sa.Column("registration_number", sa.String(80), nullable=True)),
        ("website", sa.Column("website", sa.String(500), nullable=True)),
        ("contact_name", sa.Column("contact_name", sa.String(160), nullable=True)),
        ("secondary_email", sa.Column("secondary_email", sa.String(255), nullable=True)),
        ("secondary_phone", sa.Column("secondary_phone", sa.String(80), nullable=True)),
        ("notes", sa.Column("notes", sa.Text(), nullable=True)),
        ("created_by_id", sa.Column("created_by_id", sa.Integer(), nullable=True)),
        ("updated_by_id", sa.Column("updated_by_id", sa.Integer(), nullable=True)),
    ):
        op.add_column("stock_suppliers", column)
    op.create_foreign_key(
        "fk_stock_suppliers_created_by_id_users",
        "stock_suppliers",
        "users",
        ["created_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stock_suppliers_updated_by_id_users",
        "stock_suppliers",
        "users",
        ["updated_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    for column in (
        "postal_code",
        "city",
        "country_code",
        "legal_name",
        "registration_number",
        "created_by_id",
        "updated_by_id",
    ):
        op.create_index(f"ix_stock_suppliers_{column}", "stock_suppliers", [column])

    op.create_table(
        "supplier_types",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("module_code", sa.String(80), nullable=False),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="100", nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["supplier_types.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_supplier_type_code"),
    )
    for column in ("code", "name", "module_code", "parent_id", "active", "sort_order"):
        op.create_index(f"ix_supplier_types_{column}", "supplier_types", [column])

    op.create_table(
        "supplier_type_assignments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("supplier_type_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["supplier_id"], ["stock_suppliers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supplier_type_id"], ["supplier_types.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supplier_id", "supplier_type_id", name="uq_supplier_type_assignment"),
    )
    op.create_index("ix_supplier_type_assignments_supplier_id", "supplier_type_assignments", ["supplier_id"])
    op.create_index("ix_supplier_type_assignments_supplier_type_id", "supplier_type_assignments", ["supplier_type_id"])

    op.create_table(
        "supplier_contacts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("role", sa.String(120), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(80), nullable=True),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["supplier_id"], ["stock_suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("supplier_id", "email", "is_primary", "active"):
        op.create_index(f"ix_supplier_contacts_{column}", "supplier_contacts", [column])

    op.create_table(
        "supplier_addresses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(120), nullable=False),
        sa.Column("address_line1", sa.String(240), nullable=False),
        sa.Column("address_line2", sa.String(200), nullable=True),
        sa.Column("postal_code", sa.String(40), nullable=True),
        sa.Column("city", sa.String(120), nullable=True),
        sa.Column("country_code", sa.String(2), server_default="PT", nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.true(), nullable=False),
        *timestamp_columns(),
        sa.ForeignKeyConstraint(["supplier_id"], ["stock_suppliers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("supplier_id", "postal_code", "city", "country_code", "is_primary", "active"):
        op.create_index(f"ix_supplier_addresses_{column}", "supplier_addresses", [column])

    for table in ("email_templates", "email_messages"):
        op.add_column(table, sa.Column("supplier_id", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("supplier_type_id", sa.Integer(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_supplier_id_stock_suppliers", table, "stock_suppliers", ["supplier_id"], ["id"], ondelete="SET NULL"
        )
        op.create_foreign_key(
            f"fk_{table}_supplier_type_id_supplier_types", table, "supplier_types", ["supplier_type_id"], ["id"], ondelete="SET NULL"
        )
        op.create_index(f"ix_{table}_supplier_id", table, ["supplier_id"])
        op.create_index(f"ix_{table}_supplier_type_id", table, ["supplier_type_id"])
    op.add_column("email_templates", sa.Column("module_code", sa.String(80), nullable=True))
    op.add_column("email_templates", sa.Column("context_code", sa.String(120), nullable=True))
    op.add_column("email_messages", sa.Column("context_module", sa.String(80), nullable=True))
    op.add_column("email_messages", sa.Column("context_code", sa.String(120), nullable=True))
    op.create_index("ix_email_templates_module_code", "email_templates", ["module_code"])
    op.create_index("ix_email_templates_context_code", "email_templates", ["context_code"])
    op.create_index("ix_email_messages_context_module", "email_messages", ["context_module"])
    op.create_index("ix_email_messages_context_code", "email_messages", ["context_code"])

    supplier_types = sa.table(
        "supplier_types",
        sa.column("code", sa.String), sa.column("name", sa.String),
        sa.column("module_code", sa.String), sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(supplier_types, [
        {"code": "stock", "name": "Stock", "module_code": "stock", "sort_order": 10},
        {"code": "workshop", "name": "Oficina", "module_code": "workshop", "sort_order": 20},
        {"code": "fleet", "name": "Frota", "module_code": "fleet", "sort_order": 30},
        {"code": "finance", "name": "Financeiro", "module_code": "finance", "sort_order": 40},
        {"code": "general_services", "name": "Serviços gerais", "module_code": "general", "sort_order": 50},
        {"code": "other", "name": "Outros", "module_code": "general", "sort_order": 90},
    ])
    op.execute(sa.text(
        "INSERT INTO supplier_type_assignments (supplier_id, supplier_type_id, created_at, updated_at) "
        "SELECT s.id, t.id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM stock_suppliers s "
        "JOIN supplier_types t ON t.code = 'stock'"
    ))

    for code, name in (
        ("suppliers.read", "Consultar fornecedores"),
        ("suppliers.write", "Editar fornecedores"),
        ("suppliers.configuration.manage", "Gerir tipos e modelos de fornecedores"),
    ):
        op.execute(sa.text(
            "INSERT INTO permissions (code, name, created_at, updated_at) "
            "SELECT :code, :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE code = :code)"
        ).bindparams(code=code, name=name))
    op.execute(sa.text(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT r.id, p.id FROM roles r CROSS JOIN permissions p "
        "WHERE r.code = 'admin' AND p.code IN ('suppliers.read','suppliers.write','suppliers.configuration.manage') "
        "AND NOT EXISTS (SELECT 1 FROM role_permissions rp WHERE rp.role_id = r.id AND rp.permission_id = p.id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code IN ('suppliers.read','suppliers.write','suppliers.configuration.manage'))"))
    op.execute(sa.text("DELETE FROM permissions WHERE code IN ('suppliers.read','suppliers.write','suppliers.configuration.manage')"))
    op.drop_index("ix_email_messages_context_module", table_name="email_messages")
    op.drop_index("ix_email_messages_context_code", table_name="email_messages")
    op.drop_column("email_messages", "context_code")
    op.drop_column("email_messages", "context_module")
    op.drop_index("ix_email_templates_context_code", table_name="email_templates")
    op.drop_index("ix_email_templates_module_code", table_name="email_templates")
    op.drop_column("email_templates", "context_code")
    op.drop_column("email_templates", "module_code")
    for table in ("email_messages", "email_templates"):
        op.drop_index(f"ix_{table}_supplier_type_id", table_name=table)
        op.drop_index(f"ix_{table}_supplier_id", table_name=table)
        op.drop_constraint(f"fk_{table}_supplier_type_id_supplier_types", table, type_="foreignkey")
        op.drop_constraint(f"fk_{table}_supplier_id_stock_suppliers", table, type_="foreignkey")
        op.drop_column(table, "supplier_type_id")
        op.drop_column(table, "supplier_id")
    op.drop_table("supplier_addresses")
    op.drop_table("supplier_contacts")
    op.drop_table("supplier_type_assignments")
    op.drop_table("supplier_types")
    for column in (
        "updated_by_id", "created_by_id", "registration_number", "legal_name",
        "country_code", "city", "postal_code",
    ):
        op.drop_index(f"ix_stock_suppliers_{column}", table_name="stock_suppliers")
    op.drop_constraint("fk_stock_suppliers_updated_by_id_users", "stock_suppliers", type_="foreignkey")
    op.drop_constraint("fk_stock_suppliers_created_by_id_users", "stock_suppliers", type_="foreignkey")
    for column in (
        "updated_by_id", "created_by_id", "notes", "secondary_phone", "secondary_email",
        "contact_name", "website", "registration_number", "legal_name", "country_code",
        "city", "postal_code", "address_line2",
    ):
        op.drop_column("stock_suppliers", column)
