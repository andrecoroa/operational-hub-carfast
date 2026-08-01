"""Add the isolated Stock MVP domain, permissions and immutable ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "stock.read": "Consultar Stock",
    "stock.operate": "Gerir artigos, receções e movimentos operacionais de Stock",
    "stock.manage": "Gerir fornecedores, mínimos, acertos e configuração de Stock",
}

ROLE_PERMISSIONS = {
    "viewer": {"stock.read"},
    "auditor": {"stock.read"},
    "operator": {"stock.read", "stock.operate"},
    "manager": {"stock.read", "stock.operate", "stock.manage"},
    "functional_admin": {"stock.read", "stock.manage"},
    "admin": set(PERMISSIONS),
}


def _id_for(connection, table: str, code: str) -> int | None:
    return connection.execute(
        sa.text(f"SELECT id FROM {table} WHERE code = :code"), {"code": code}
    ).scalar()


def _grant(connection, role_id: int, permission_id: int) -> None:
    exists = connection.execute(
        sa.text(
            "SELECT id FROM role_permissions "
            "WHERE role_id = :role_id AND permission_id = :permission_id"
        ),
        {"role_id": role_id, "permission_id": permission_id},
    ).scalar()
    if not exists:
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "VALUES (:role_id, :permission_id)"
            ),
            {"role_id": role_id, "permission_id": permission_id},
        )


def upgrade() -> None:
    op.create_table(
        "stock_locations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("code", name="uq_stock_locations_code"),
    )
    op.create_index("ix_stock_locations_code", "stock_locations", ["code"])

    op.create_table(
        "stock_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "parent_id", sa.Integer(), sa.ForeignKey("stock_categories.id", ondelete="SET NULL")
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("code", name="uq_stock_categories_code"),
    )

    op.create_table(
        "stock_suppliers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tax_id", sa.String(40)),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(255)),
        sa.Column("phone", sa.String(80)),
        sa.Column("address", sa.Text()),
        sa.Column("payment_terms", sa.String(160)),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tax_id", name="uq_stock_suppliers_tax_id"),
    )
    op.create_index("ix_stock_suppliers_name", "stock_suppliers", ["name"])

    op.create_table(
        "stock_articles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("internal_ref", sa.String(120), nullable=False),
        sa.Column("name", sa.String(240), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("unit", sa.String(30), nullable=False, server_default="un."),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("stock_categories.id", ondelete="SET NULL")
        ),
        sa.Column("classification", sa.String(120)),
        sa.Column(
            "primary_supplier_id",
            sa.Integer(),
            sa.ForeignKey("stock_suppliers.id", ondelete="SET NULL"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("average_cost", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("last_cost", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("internal_ref", name="uq_stock_articles_internal_ref"),
    )
    op.create_index("ix_stock_articles_name", "stock_articles", ["name"])

    op.create_table(
        "stock_article_supplier_refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("stock_suppliers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("supplier_ref", sa.String(160), nullable=False),
        sa.Column("supplier_description", sa.Text()),
        sa.Column("last_cost", sa.Numeric(14, 4)),
        sa.Column("last_purchase_at", sa.DateTime(timezone=True)),
        sa.Column("preferred", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "supplier_id", "supplier_ref", name="uq_stock_article_supplier_ref_supplier_reference"
        ),
    )

    op.create_table(
        "stock_minimums",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("stock_locations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("minimum_quantity", sa.Numeric(14, 3), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("article_id", "location_id", name="uq_stock_minimum_article_location"),
    )

    op.create_table(
        "stock_invoice_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "supplier_id", sa.Integer(), sa.ForeignKey("stock_suppliers.id", ondelete="RESTRICT")
        ),
        sa.Column("invoice_number", sa.String(120)),
        sa.Column("invoice_date", sa.Date()),
        sa.Column("due_date", sa.Date()),
        sa.Column("net_total", sa.Numeric(14, 4)),
        sa.Column("tax_total", sa.Numeric(14, 4)),
        sa.Column("gross_total", sa.Numeric(14, 4)),
        sa.Column("status", sa.String(40), nullable=False, server_default="needs_review"),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("extractor_name", sa.String(120)),
        sa.Column("extractor_version", sa.String(40)),
        sa.Column("raw_extraction_json", sa.JSON()),
        sa.Column("error_details", sa.Text()),
        sa.Column("validated_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("document_id", name="uq_stock_invoice_import_document"),
        sa.UniqueConstraint(
            "supplier_id", "invoice_number", name="uq_stock_invoice_import_supplier_number"
        ),
    )
    op.create_index(
        "ix_stock_invoice_import_content_hash", "stock_invoice_imports", ["content_hash"]
    )

    op.create_table(
        "stock_invoice_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "invoice_import_id",
            sa.Integer(),
            sa.ForeignKey("stock_invoice_imports.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column(
            "article_id", sa.Integer(), sa.ForeignKey("stock_articles.id", ondelete="RESTRICT")
        ),
        sa.Column("supplier_ref", sa.String(160)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("unit_cost", sa.Numeric(14, 4), nullable=False),
        sa.Column("discount", sa.Numeric(7, 4), nullable=False, server_default="0"),
        sa.Column("eco_value", sa.Numeric(14, 4), nullable=False, server_default="0"),
        sa.Column("tax_rate", sa.Numeric(7, 4), nullable=False, server_default="0"),
        sa.Column("line_total", sa.Numeric(14, 4), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "invoice_import_id", "line_number", name="uq_stock_invoice_line_import_number"
        ),
    )

    op.create_table(
        "stock_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "invoice_import_id",
            sa.Integer(),
            sa.ForeignKey("stock_invoice_imports.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "location_id", sa.Integer(), sa.ForeignKey("stock_locations.id", ondelete="RESTRICT")
        ),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column("confirmed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("responsible_name", sa.String(160)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "stock_receipt_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "receipt_id",
            sa.Integer(),
            sa.ForeignKey("stock_receipts.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "invoice_line_id",
            sa.Integer(),
            sa.ForeignKey("stock_invoice_lines.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("invoiced_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("previously_received_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("received_quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(14, 4), nullable=False),
        sa.Column("lot", sa.String(120)),
        sa.Column("divergence_reason", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("movement_type", sa.String(40), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("unit_cost", sa.Numeric(14, 4)),
        sa.Column(
            "from_location_id",
            sa.Integer(),
            sa.ForeignKey("stock_locations.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "to_location_id", sa.Integer(), sa.ForeignKey("stock_locations.id", ondelete="RESTRICT")
        ),
        sa.Column(
            "receipt_line_id",
            sa.Integer(),
            sa.ForeignKey("stock_receipt_lines.id", ondelete="RESTRICT"),
        ),
        sa.Column("external_reference_type", sa.String(80)),
        sa.Column("external_reference_id", sa.String(120)),
        sa.Column("performed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "reverses_movement_id",
            sa.Integer(),
            sa.ForeignKey("stock_movements.id", ondelete="RESTRICT"),
        ),
        sa.UniqueConstraint("reverses_movement_id", name="uq_stock_movements_reverses_movement_id"),
    )
    op.create_index(
        "ix_stock_movements_article_occurred", "stock_movements", ["article_id", "occurred_at"]
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO stock_locations (code, name, active) VALUES "
            "('WORKSHOP', 'Oficina', true), ('AIRPORT', 'Aeroporto', true)"
        )
    )
    for code, name in (
        ("PARTS", "Peças"),
        ("TYRES", "Pneus"),
        ("LUBRICANTS", "Lubrificantes"),
        ("FILTERS", "Filtros"),
        ("CONSUMABLES", "Consumíveis"),
    ):
        connection.execute(
            sa.text(
                "INSERT INTO stock_categories (code, name, active) VALUES (:code, :name, true)"
            ),
            {"code": code, "name": name},
        )

    for code, name in PERMISSIONS.items():
        if _id_for(connection, "permissions", code) is None:
            connection.execute(
                sa.text(
                    "INSERT INTO permissions (code, name, description) VALUES (:code, :name, NULL)"
                ),
                {"code": code, "name": name},
            )
    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        role_id = _id_for(connection, "roles", role_code)
        if role_id is None:
            continue
        for permission_code in permission_codes:
            permission_id = _id_for(connection, "permissions", permission_code)
            if permission_id is not None:
                _grant(connection, role_id, permission_id)

    if connection.dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_stock_movement_mutation() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'stock_movements are immutable; create an adjustment or reversal';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER stock_movements_no_update
              BEFORE UPDATE ON stock_movements FOR EACH ROW
              EXECUTE FUNCTION prevent_stock_movement_mutation();
            """
        )
        op.execute(
            """
            CREATE TRIGGER stock_movements_no_delete
              BEFORE DELETE ON stock_movements FOR EACH ROW
              EXECUTE FUNCTION prevent_stock_movement_mutation();
            """
        )
    elif connection.dialect.name == "sqlite":
        op.execute(
            "CREATE TRIGGER stock_movements_no_update BEFORE UPDATE ON stock_movements "
            "BEGIN SELECT RAISE(ABORT, 'stock_movements are immutable'); END"
        )
        op.execute(
            "CREATE TRIGGER stock_movements_no_delete BEFORE DELETE ON stock_movements "
            "BEGIN SELECT RAISE(ABORT, 'stock_movements are immutable'); END"
        )


def downgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_update ON stock_movements")
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_delete ON stock_movements")
        op.execute("DROP FUNCTION IF EXISTS prevent_stock_movement_mutation()")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_update")
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_delete")

    for table in (
        "stock_movements",
        "stock_receipt_lines",
        "stock_receipts",
        "stock_invoice_lines",
        "stock_invoice_imports",
        "stock_minimums",
        "stock_article_supplier_refs",
        "stock_articles",
        "stock_suppliers",
        "stock_categories",
        "stock_locations",
    ):
        op.drop_table(table)

    permission_ids = [
        permission_id
        for code in PERMISSIONS
        if (permission_id := _id_for(connection, "permissions", code)) is not None
    ]
    for permission_id in permission_ids:
        connection.execute(
            sa.text("DELETE FROM role_permissions WHERE permission_id = :permission_id"),
            {"permission_id": permission_id},
        )
        connection.execute(
            sa.text("DELETE FROM permissions WHERE id = :permission_id"),
            {"permission_id": permission_id},
        )
