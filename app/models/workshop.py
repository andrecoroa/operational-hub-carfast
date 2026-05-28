from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class WorkshopProcess(TimestampMixin, Base):
    __tablename__ = "workshop_processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    opening_type: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(80), default="opening", index=True)
    priority: Mapped[str | None] = mapped_column(String(80), index=True)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    opened_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    opened_on: Mapped[date | None] = mapped_column(Date)
    expected_exit_on: Mapped[date | None] = mapped_column(Date)
    km_entry: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str | None] = mapped_column(String(80), index=True)
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    document_folder_path: Mapped[str | None] = mapped_column(Text)
    document_folder_url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)


class WorkshopProcessNote(Base):
    __tablename__ = "workshop_process_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkshopProcessEvidence(Base):
    __tablename__ = "workshop_process_evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    phase: Mapped[str] = mapped_column(String(80), index=True)
    evidence_type: Mapped[str] = mapped_column(String(80), index=True)
    anomaly_category: Mapped[str] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(80), default="registered", index=True)
    description: Mapped[str] = mapped_column(Text)
    storage_provider: Mapped[str | None] = mapped_column(String(80))
    external_url: Mapped[str | None] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkshopProcessService(TimestampMixin, Base):
    __tablename__ = "workshop_process_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    service_family: Mapped[str] = mapped_column(String(80), index=True)
    service_detail: Mapped[str | None] = mapped_column(String(120), index=True)
    service_axis: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(80), default="to_assess", index=True)
    note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class WorkshopTechnicalReading(TimestampMixin, Base):
    __tablename__ = "workshop_technical_readings"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_processes.id", ondelete="SET NULL"),
        index=True,
    )
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reading_type: Mapped[str] = mapped_column(String(80), default="technical", index=True)
    reading_date: Mapped[date | None] = mapped_column(Date, index=True)
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    data_json: Mapped[dict | None] = mapped_column(JSON)
    differences_json: Mapped[dict | None] = mapped_column(JSON)
    storage_provider: Mapped[str | None] = mapped_column(String(80))
    external_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    replaced_by_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_technical_readings.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    voided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
