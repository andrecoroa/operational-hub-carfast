"""Implement the approved final Stock reorganization.

Revision ID: f4b5c6d7e8f9
Revises: f3a4b5c6d7e8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUANTITY = sa.Numeric(14, 3)
MONEY = sa.Numeric(14, 4)

PERMISSIONS = {
    "stock.orders.manage": "Gerir encomendas de Stock",
    "stock.inventory.count": "Executar contagens cegas de Stock",
    "stock.inventory.confirm": "Confirmar diferenças e acertos de inventário",
    "stock.compatibility.manage": "Gerir compatibilidades artigo-viatura",
    "stock.conference": "Conferir documentos de Stock",
}

ROLE_PERMISSIONS = {
    "functional_admin": {"stock.compatibility.manage"},
    "manager": set(PERMISSIONS),
    "operator": {"stock.inventory.count", "stock.conference"},
    "admin": set(PERMISSIONS),
}


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _drop_movement_triggers(connection) -> None:
    if connection.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_update ON stock_movements")
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_delete ON stock_movements")
    elif connection.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_update")
        op.execute("DROP TRIGGER IF EXISTS stock_movements_no_delete")


def _create_movement_triggers(connection) -> None:
    if connection.dialect.name == "postgresql":
        op.execute(
            "CREATE TRIGGER stock_movements_no_update BEFORE UPDATE ON stock_movements "
            "FOR EACH ROW EXECUTE FUNCTION prevent_stock_movement_mutation()"
        )
        op.execute(
            "CREATE TRIGGER stock_movements_no_delete BEFORE DELETE ON stock_movements "
            "FOR EACH ROW EXECUTE FUNCTION prevent_stock_movement_mutation()"
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


def upgrade() -> None:
    connection = op.get_bind()

    op.create_table(
        "stock_article_vehicle_compatibilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("brand", sa.String(120), nullable=False),
        sa.Column("model", sa.String(160), nullable=False),
        sa.Column("version", sa.String(160)),
        sa.Column("engine", sa.String(160)),
        sa.Column("generation_period", sa.String(160)),
        sa.Column("status", sa.String(40), nullable=False, server_default="suggested"),
        sa.Column("evidence_type", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("evidence_reference", sa.String(200)),
        sa.Column("evidence_notes", sa.Text()),
        sa.Column("workshop_process_reference", sa.String(120)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_stock_compatibility_vehicle",
        "stock_article_vehicle_compatibilities",
        ["brand", "model", "version", "engine"],
    )
    for column in ("article_id", "brand", "model", "status", "evidence_type", "evidence_reference"):
        op.create_index(
            f"ix_stock_article_vehicle_compatibilities_{column}",
            "stock_article_vehicle_compatibilities",
            [column],
        )
    op.create_index(
        "ix_stock_compat_workshop_ref",
        "stock_article_vehicle_compatibilities",
        ["workshop_process_reference"],
    )

    op.create_table(
        "stock_inventory_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("stock_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column(
            "effective_date", sa.Date(), nullable=False, server_default=sa.func.current_date()
        ),
        sa.Column("idempotency_key", sa.String(120), unique=True),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "snapshot_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("confirmed_at", sa.DateTime(timezone=True)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("closed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("confirmed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("location_id", "status", "effective_date", "idempotency_key"):
        op.create_index(
            f"ix_stock_inventory_sessions_{column}", "stock_inventory_sessions", [column]
        )

    op.create_table(
        "stock_purchase_orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_number", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("stock_suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("commercial_status", sa.String(40), nullable=False, server_default="draft"),
        sa.Column("receiving_status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column(
            "effective_date", sa.Date(), nullable=False, server_default=sa.func.current_date()
        ),
        sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "order_number", "version", name="uq_stock_purchase_order_number_version"
        ),
    )
    for column in (
        "order_number",
        "supplier_id",
        "commercial_status",
        "receiving_status",
        "effective_date",
    ):
        op.create_index(f"ix_stock_purchase_orders_{column}", "stock_purchase_orders", [column])

    op.create_table(
        "stock_purchase_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "purchase_order_id",
            sa.Integer(),
            sa.ForeignKey("stock_purchase_orders.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("supplier_ref", sa.String(160)),
        sa.Column("ordered_quantity", QUANTITY, nullable=False),
        sa.Column("received_quantity", QUANTITY, nullable=False, server_default="0"),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("unit_price", MONEY, nullable=False),
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("stock_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("purchase_order_id", "article_id", "supplier_ref", "location_id"):
        op.create_index(
            f"ix_stock_purchase_order_lines_{column}", "stock_purchase_order_lines", [column]
        )

    with op.batch_alter_table("stock_articles") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(40), nullable=False, server_default="active")
        )
        batch_op.create_index("ix_stock_articles_status", ["status"])
    connection.execute(
        sa.text(
            "UPDATE stock_articles SET status = CASE WHEN active THEN 'active' ELSE 'inactive' END"
        )
    )

    with op.batch_alter_table("stock_invoice_imports") as batch_op:
        batch_op.add_column(
            sa.Column("conference_status", sa.String(40), nullable=False, server_default="pending")
        )
        batch_op.add_column(sa.Column("conference_notes", sa.Text()))
        batch_op.add_column(
            sa.Column("conference_tolerance", MONEY, nullable=False, server_default="0.01")
        )
        batch_op.create_index("ix_stock_invoice_imports_conference_status", ["conference_status"])
    connection.execute(
        sa.text(
            "UPDATE stock_invoice_imports SET conference_status = CASE "
            "WHEN status = 'validated' THEN 'conferred' ELSE 'pending' END"
        )
    )

    with op.batch_alter_table("stock_receipts") as batch_op:
        batch_op.add_column(sa.Column("manual_reason", sa.Text()))
        batch_op.add_column(sa.Column("effective_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("purchase_order_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_stock_receipts_purchase_order",
            "stock_purchase_orders",
            ["purchase_order_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index("ix_stock_receipts_effective_date", ["effective_date"])
        batch_op.create_index("ix_stock_receipts_purchase_order_id", ["purchase_order_id"])
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                "UPDATE stock_receipts SET effective_date = "
                "COALESCE(confirmed_at::date, created_at::date, CURRENT_DATE)"
            )
        )
    else:
        connection.execute(
            sa.text(
                "UPDATE stock_receipts SET effective_date = "
                "COALESCE(DATE(confirmed_at), DATE(created_at), CURRENT_DATE)"
            )
        )
    with op.batch_alter_table("stock_receipts") as batch_op:
        batch_op.alter_column("effective_date", existing_type=sa.Date(), nullable=False)

    with op.batch_alter_table("stock_receipt_lines") as batch_op:
        batch_op.add_column(sa.Column("purchase_order_line_id", sa.Integer()))
        batch_op.create_foreign_key(
            "fk_stock_receipt_lines_purchase_order_line",
            "stock_purchase_order_lines",
            ["purchase_order_line_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_stock_receipt_lines_purchase_order_line_id", ["purchase_order_line_id"]
        )

    _drop_movement_triggers(connection)
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.add_column(sa.Column("effective_date", sa.Date(), nullable=True))
        batch_op.create_index("ix_stock_movements_effective_date", ["effective_date"])
    if connection.dialect.name == "postgresql":
        connection.execute(
            sa.text(
                "UPDATE stock_movements SET effective_date = "
                "COALESCE(occurred_at::date, CURRENT_DATE)"
            )
        )
    else:
        connection.execute(
            sa.text(
                "UPDATE stock_movements SET effective_date = "
                "COALESCE(DATE(occurred_at), CURRENT_DATE)"
            )
        )
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.alter_column("effective_date", existing_type=sa.Date(), nullable=False)
    _create_movement_triggers(connection)

    op.create_table(
        "stock_inventory_counts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("stock_inventory_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("expected_snapshot", QUANTITY, nullable=False),
        sa.Column("counted_quantity", QUANTITY),
        sa.Column("justification", sa.Text()),
        sa.Column(
            "adjustment_movement_id",
            sa.Integer(),
            sa.ForeignKey("stock_movements.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "session_id", "article_id", name="uq_stock_inventory_count_session_article"
        ),
    )
    for column in ("session_id", "article_id", "adjustment_movement_id"):
        op.create_index(f"ix_stock_inventory_counts_{column}", "stock_inventory_counts", [column])

    op.create_table(
        "stock_delivery_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "supplier_id",
            sa.Integer(),
            sa.ForeignKey("stock_suppliers.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("document_id", sa.Integer(), sa.ForeignKey("documents.id", ondelete="SET NULL")),
        sa.Column("document_type", sa.String(40), nullable=False),
        sa.Column("reference", sa.String(160), nullable=False),
        sa.Column("effective_date", sa.Date()),
        sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
        sa.Column(
            "receipt_id", sa.Integer(), sa.ForeignKey("stock_receipts.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "supplier_id", "document_type", "reference", name="uq_stock_delivery_document"
        ),
    )
    for column in (
        "supplier_id",
        "document_id",
        "document_type",
        "reference",
        "effective_date",
        "status",
        "receipt_id",
    ):
        op.create_index(
            f"ix_stock_delivery_documents_{column}", "stock_delivery_documents", [column]
        )

    op.create_table(
        "stock_discrepancies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "article_id",
            sa.Integer(),
            sa.ForeignKey("stock_articles.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Integer(),
            sa.ForeignKey("stock_locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(40), nullable=False),
        sa.Column("source_id", sa.String(120), nullable=False),
        sa.Column("expected_quantity", QUANTITY),
        sa.Column("actual_quantity", QUANTITY),
        sa.Column("difference_quantity", QUANTITY, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False, server_default="open"),
        sa.Column(
            "adjustment_movement_id",
            sa.Integer(),
            sa.ForeignKey("stock_movements.id", ondelete="RESTRICT"),
            unique=True,
        ),
        sa.Column("regularized_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("regularized_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in (
        "article_id",
        "location_id",
        "source_type",
        "source_id",
        "status",
        "adjustment_movement_id",
    ):
        op.create_index(f"ix_stock_discrepancies_{column}", "stock_discrepancies", [column])

    for code, name in PERMISSIONS.items():
        code_sql = _literal(code)
        name_sql = _literal(name)
        op.execute(
            "INSERT INTO permissions (code, name, description) "
            f"SELECT {code_sql}, {name_sql}, NULL WHERE NOT EXISTS "
            f"(SELECT 1 FROM permissions WHERE code = {code_sql})"
        )
    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        for permission_code in permission_codes:
            role_sql = _literal(role_code)
            permission_sql = _literal(permission_code)
            op.execute(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT roles.id, permissions.id FROM roles, permissions "
                f"WHERE roles.code = {role_sql} AND permissions.code = {permission_sql} "
                "AND NOT EXISTS (SELECT 1 FROM role_permissions existing "
                "WHERE existing.role_id = roles.id "
                "AND existing.permission_id = permissions.id)"
            )


def downgrade() -> None:
    connection = op.get_bind()
    for code in PERMISSIONS:
        code_sql = _literal(code)
        op.execute(
            "DELETE FROM role_permissions WHERE permission_id IN "
            f"(SELECT id FROM permissions WHERE code = {code_sql})"
        )
        op.execute(f"DELETE FROM permissions WHERE code = {code_sql}")

    op.drop_table("stock_discrepancies")
    op.drop_table("stock_delivery_documents")
    op.drop_table("stock_inventory_counts")
    op.drop_table("stock_inventory_sessions")

    with op.batch_alter_table("stock_receipt_lines") as batch_op:
        batch_op.drop_index("ix_stock_receipt_lines_purchase_order_line_id")
        batch_op.drop_constraint("fk_stock_receipt_lines_purchase_order_line", type_="foreignkey")
        batch_op.drop_column("purchase_order_line_id")
    with op.batch_alter_table("stock_receipts") as batch_op:
        batch_op.drop_index("ix_stock_receipts_purchase_order_id")
        batch_op.drop_index("ix_stock_receipts_effective_date")
        batch_op.drop_constraint("fk_stock_receipts_purchase_order", type_="foreignkey")
        batch_op.drop_column("purchase_order_id")
        batch_op.drop_column("effective_date")
        batch_op.drop_column("manual_reason")
    op.drop_table("stock_purchase_order_lines")
    op.drop_table("stock_purchase_orders")

    _drop_movement_triggers(connection)
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_index("ix_stock_movements_effective_date")
        batch_op.drop_column("effective_date")
    _create_movement_triggers(connection)

    with op.batch_alter_table("stock_invoice_imports") as batch_op:
        batch_op.drop_index("ix_stock_invoice_imports_conference_status")
        batch_op.drop_column("conference_tolerance")
        batch_op.drop_column("conference_notes")
        batch_op.drop_column("conference_status")
    with op.batch_alter_table("stock_articles") as batch_op:
        batch_op.drop_index("ix_stock_articles_status")
        batch_op.drop_column("status")
    op.drop_table("stock_article_vehicle_compatibilities")
