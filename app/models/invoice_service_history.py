from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class InvoiceServiceImportBatch(TimestampMixin, Base):
    __tablename__ = "invoice_service_import_batches"
    __table_args__ = (
        UniqueConstraint("file_hash", "version", name="uq_invoice_service_batch_hash_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(80))
    file_hash: Mapped[str] = mapped_column(String(128), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(40), default="dry_run", index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    summary_json: Mapped[dict | None] = mapped_column(JSON)
    differences_json: Mapped[list | dict | None] = mapped_column(JSON)


class InvoiceServiceEvent(TimestampMixin, Base):
    __tablename__ = "invoice_service_events"
    __table_args__ = (
        UniqueConstraint("source", "stable_key", name="uq_invoice_service_event_source_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(120), index=True)
    stable_key: Mapped[str] = mapped_column(String(200), index=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    workshop_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_processes.id", ondelete="SET NULL"), index=True
    )
    service_date: Mapped[date | None] = mapped_column(Date, index=True)
    odometer_km: Mapped[int | None] = mapped_column(Integer, index=True)
    service_code: Mapped[str] = mapped_column(String(120), index=True)
    service_label: Mapped[str] = mapped_column(String(200))
    classification: Mapped[str | None] = mapped_column(String(120), index=True)
    axle: Mapped[str | None] = mapped_column(String(40), index=True)
    position: Mapped[str | None] = mapped_column(String(80), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), index=True)
    work_order_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    work_order_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="EUR")
    status: Mapped[str] = mapped_column(String(40), default="auto_extracted", index=True)
    evidence_text: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[dict | list | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    validated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice_service_import_batches.id")
    )


class InvoiceServiceEventRevision(Base):
    __tablename__ = "invoice_service_event_revisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("invoice_service_events.id", ondelete="CASCADE"), index=True
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoice_service_import_batches.id"), index=True
    )
    action: Mapped[str] = mapped_column(String(40), index=True)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
