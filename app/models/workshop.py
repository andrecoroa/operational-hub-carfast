from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class WorkshopProcess(TimestampMixin, Base):
    __tablename__ = "workshop_processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(80), default="open", index=True)
    priority: Mapped[str | None] = mapped_column(String(80), index=True)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    opened_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    opened_on: Mapped[date | None] = mapped_column(Date)
    expected_exit_on: Mapped[date | None] = mapped_column(Date)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)


class WorkshopProcessNote(Base):
    __tablename__ = "workshop_process_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
