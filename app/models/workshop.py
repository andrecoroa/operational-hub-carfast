from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
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
