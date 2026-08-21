from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin
from app.models.stock import StockSupplier


# Canonical transversal name.  The legacy class/table name remains available so
# every Stock foreign key and existing integration continues to work unchanged.
Supplier = StockSupplier


class SupplierType(TimestampMixin, Base):
    __tablename__ = "supplier_types"
    __table_args__ = (UniqueConstraint("code", name="uq_supplier_type_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    module_code: Mapped[str] = mapped_column(String(80), index=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("supplier_types.id", ondelete="RESTRICT"), index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SupplierTypeAssignment(TimestampMixin, Base):
    __tablename__ = "supplier_type_assignments"
    __table_args__ = (
        UniqueConstraint(
            "supplier_id", "supplier_type_id", name="uq_supplier_type_assignment"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("stock_suppliers.id", ondelete="CASCADE"), index=True
    )
    supplier_type_id: Mapped[int] = mapped_column(
        ForeignKey("supplier_types.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SupplierContact(TimestampMixin, Base):
    __tablename__ = "supplier_contacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("stock_suppliers.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(80))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class SupplierAddress(TimestampMixin, Base):
    __tablename__ = "supplier_addresses"

    id: Mapped[int] = mapped_column(primary_key=True)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("stock_suppliers.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(120), default="Principal")
    address_line1: Mapped[str] = mapped_column(String(240))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    postal_code: Mapped[str | None] = mapped_column(String(40), index=True)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    country_code: Mapped[str] = mapped_column(String(2), default="PT", index=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
