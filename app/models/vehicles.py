from datetime import datetime

from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class Vehicle(TimestampMixin, Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str | None] = mapped_column(String(40), unique=True, index=True)
    vin: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    rentway_unit_nr: Mapped[str | None] = mapped_column(String(80), unique=True, index=True)
    brand: Mapped[str | None] = mapped_column(String(120), index=True)
    model: Mapped[str | None] = mapped_column(String(160), index=True)
    version: Mapped[str | None] = mapped_column(String(160))
    year: Mapped[int | None] = mapped_column(Integer)
    lifecycle_status: Mapped[str | None] = mapped_column(String(80), index=True)
    operational_status: Mapped[str | None] = mapped_column(String(80), index=True)
    current_location_id: Mapped[int | None] = mapped_column(ForeignKey("organizational_units.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)


class VehicleIdentifier(TimestampMixin, Base):
    __tablename__ = "vehicle_identifiers"
    __table_args__ = (UniqueConstraint("identifier_type", "identifier_value"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    identifier_type: Mapped[str] = mapped_column(String(40), index=True)
    identifier_value: Mapped[str] = mapped_column(String(160), index=True)
    source_system: Mapped[str | None] = mapped_column(String(80), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class VehicleLifecycleEvent(Base):
    __tablename__ = "vehicle_lifecycle_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(80), index=True)
    occurred_on: Mapped[Date | None] = mapped_column(Date)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VehicleOperationalStatusEvent(Base):
    __tablename__ = "vehicle_operational_status_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(80), index=True)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VehicleManualField(TimestampMixin, Base):
    __tablename__ = "vehicle_manual_fields"
    __table_args__ = (UniqueConstraint("vehicle_id", "field_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    field_code: Mapped[str] = mapped_column(String(120), index=True)
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class VehicleExternalSnapshot(TimestampMixin, Base):
    __tablename__ = "vehicle_external_snapshots"
    __table_args__ = (UniqueConstraint("vehicle_id", "source_system"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"))
    source_system: Mapped[str] = mapped_column(String(80), index=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    data_json: Mapped[dict] = mapped_column(JSON)
    data_hash: Mapped[str | None] = mapped_column(String(80), index=True)


class VehicleFinancialPlan(TimestampMixin, Base):
    __tablename__ = "vehicle_financial_plans"
    __table_args__ = (
        UniqueConstraint("finance_entity", "contract_number", "vehicle_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    import_batch_id: Mapped[int | None] = mapped_column(ForeignKey("import_batches.id"))
    finance_entity: Mapped[str] = mapped_column(String(160), index=True)
    contract_number: Mapped[str] = mapped_column(String(160), index=True)
    association_status: Mapped[str | None] = mapped_column(String(80), index=True)
    association_confidence: Mapped[str | None] = mapped_column(String(40))
    association_method: Mapped[str | None] = mapped_column(String(40))
    plan_status: Mapped[str | None] = mapped_column(String(80), index=True)
    start_date: Mapped[Date | None] = mapped_column(Date)
    end_date: Mapped[Date | None] = mapped_column(Date)
    term_months: Mapped[int | None] = mapped_column(Integer)
    initial_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outstanding_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    amount_reference_date: Mapped[Date | None] = mapped_column(Date)
    installment_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    installment_with_vat: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    residual_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    source_definition: Mapped[str | None] = mapped_column(Text)
    source_references: Mapped[str | None] = mapped_column(Text)
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    human_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VehicleFinancialPlanInstallment(TimestampMixin, Base):
    __tablename__ = "vehicle_financial_plan_installments"
    __table_args__ = (
        UniqueConstraint("financial_plan_id", "period_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    financial_plan_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_financial_plans.id", ondelete="CASCADE"),
        index=True,
    )
    period_number: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[Date | None] = mapped_column(Date)
    period_end: Mapped[Date] = mapped_column(Date)
    amortization_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    interest_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    installment_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outstanding_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    outstanding_with_vat: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    source_label: Mapped[str | None] = mapped_column(String(255))
    raw_json: Mapped[dict] = mapped_column(JSON, default=dict)
