from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin

QUANTITY = Numeric(14, 3)
MONEY = Numeric(14, 4)
RATE = Numeric(7, 4)


class StockLocation(TimestampMixin, Base):
    __tablename__ = "stock_locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class StockCategory(TimestampMixin, Base):
    __tablename__ = "stock_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_categories.id", ondelete="SET NULL")
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class StockSupplier(TimestampMixin, Base):
    __tablename__ = "stock_suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    tax_id: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(80))
    address: Mapped[str | None] = mapped_column(Text)
    payment_terms: Mapped[str | None] = mapped_column(String(160))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class StockArticle(TimestampMixin, Base):
    __tablename__ = "stock_articles"

    id: Mapped[int] = mapped_column(primary_key=True)
    internal_ref: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(240), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(30), default="un.")
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_categories.id", ondelete="SET NULL"), index=True
    )
    classification: Mapped[str | None] = mapped_column(String(120), index=True)
    primary_supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_suppliers.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    average_cost: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    last_cost: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))


class StockArticleSupplierRef(TimestampMixin, Base):
    __tablename__ = "stock_article_supplier_refs"
    __table_args__ = (
        UniqueConstraint(
            "supplier_id",
            "supplier_ref",
            name="uq_stock_article_supplier_ref_supplier_reference",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("stock_articles.id", ondelete="CASCADE"), index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("stock_suppliers.id", ondelete="CASCADE"), index=True
    )
    supplier_ref: Mapped[str] = mapped_column(String(160), index=True)
    supplier_description: Mapped[str | None] = mapped_column(Text)
    last_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    last_purchase_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    preferred: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class StockMinimum(TimestampMixin, Base):
    __tablename__ = "stock_minimums"
    __table_args__ = (
        UniqueConstraint("article_id", "location_id", name="uq_stock_minimum_article_location"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("stock_articles.id", ondelete="CASCADE"), index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="CASCADE"), index=True
    )
    minimum_quantity: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0"))


class StockInvoiceImport(TimestampMixin, Base):
    __tablename__ = "stock_invoice_imports"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_stock_invoice_import_document"),
        UniqueConstraint(
            "supplier_id",
            "invoice_number",
            name="uq_stock_invoice_import_supplier_number",
        ),
        Index("ix_stock_invoice_import_content_hash", "content_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_suppliers.id", ondelete="RESTRICT"), index=True
    )
    invoice_number: Mapped[str | None] = mapped_column(String(120), index=True)
    invoice_date: Mapped[date | None] = mapped_column(Date)
    due_date: Mapped[date | None] = mapped_column(Date)
    net_total: Mapped[Decimal | None] = mapped_column(MONEY)
    tax_total: Mapped[Decimal | None] = mapped_column(MONEY)
    gross_total: Mapped[Decimal | None] = mapped_column(MONEY)
    status: Mapped[str] = mapped_column(String(40), default="needs_review", index=True)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    extractor_name: Mapped[str | None] = mapped_column(String(120))
    extractor_version: Mapped[str | None] = mapped_column(String(40))
    raw_extraction_json: Mapped[dict | list | None] = mapped_column(JSON)
    error_details: Mapped[str | None] = mapped_column(Text)
    validated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StockInvoiceLine(TimestampMixin, Base):
    __tablename__ = "stock_invoice_lines"
    __table_args__ = (
        UniqueConstraint(
            "invoice_import_id",
            "line_number",
            name="uq_stock_invoice_line_import_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_import_id: Mapped[int] = mapped_column(
        ForeignKey("stock_invoice_imports.id", ondelete="CASCADE"), index=True
    )
    line_number: Mapped[int] = mapped_column()
    article_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_articles.id", ondelete="RESTRICT"), index=True
    )
    supplier_ref: Mapped[str | None] = mapped_column(String(160), index=True)
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    unit: Mapped[str] = mapped_column(String(30))
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    discount: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"))
    eco_value: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"))
    tax_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"))
    line_total: Mapped[Decimal] = mapped_column(MONEY)


class StockReceipt(TimestampMixin, Base):
    __tablename__ = "stock_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_suppliers.id", ondelete="RESTRICT"), index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    source_type: Mapped[str] = mapped_column(String(40), index=True)
    source_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="completed", index=True)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    responsible_name: Mapped[str | None] = mapped_column(String(160))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class StockReceiptInvoiceLink(Base):
    __tablename__ = "stock_receipt_invoice_links"
    __table_args__ = (
        UniqueConstraint("receipt_id", "invoice_import_id", name="uq_stock_receipt_invoice_link"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("stock_receipts.id", ondelete="CASCADE"), index=True
    )
    invoice_import_id: Mapped[int] = mapped_column(
        ForeignKey("stock_invoice_imports.id", ondelete="CASCADE"), index=True
    )
    linked_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockReceiptLine(Base):
    __tablename__ = "stock_receipt_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(
        ForeignKey("stock_receipts.id", ondelete="RESTRICT"), index=True
    )
    article_id: Mapped[int] = mapped_column(
        ForeignKey("stock_articles.id", ondelete="RESTRICT"), index=True
    )
    supplier_ref: Mapped[str | None] = mapped_column(String(160), index=True)
    accepted_quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    unit_cost: Mapped[Decimal] = mapped_column(MONEY)
    lot: Mapped[str | None] = mapped_column(String(120), index=True)
    divergence_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("stock_articles.id", ondelete="RESTRICT"), index=True
    )
    movement_type: Mapped[str] = mapped_column(String(40), index=True)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY)
    unit: Mapped[str] = mapped_column(String(30))
    unit_cost: Mapped[Decimal | None] = mapped_column(MONEY)
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="RESTRICT"), index=True
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="RESTRICT"), index=True
    )
    receipt_line_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_receipt_lines.id", ondelete="RESTRICT"), index=True
    )
    external_reference_type: Mapped[str | None] = mapped_column(String(80), index=True)
    external_reference_id: Mapped[str | None] = mapped_column(String(120), index=True)
    performed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    reason: Mapped[str | None] = mapped_column(Text)
    reverses_movement_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_movements.id", ondelete="RESTRICT"), unique=True, index=True
    )


def _reject_stock_movement_mutation(*_args, **_kwargs) -> None:
    raise ValueError("Movimentos de Stock confirmados são imutáveis; crie um acerto ou reversão.")


event.listen(StockMovement, "before_update", _reject_stock_movement_mutation)
event.listen(StockMovement, "before_delete", _reject_stock_movement_mutation)
