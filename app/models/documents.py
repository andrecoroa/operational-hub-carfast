from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200), index=True)
    document_type: Mapped[str | None] = mapped_column(String(80), index=True)
    classification: Mapped[str | None] = mapped_column(String(120), index=True)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(Integer)
    storage_provider: Mapped[str] = mapped_column(String(40), default="local")
    storage_path: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(Text)
    folder_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="received", index=True)
    confidentiality_level: Mapped[str | None] = mapped_column(String(40), index=True)
    retention_policy: Mapped[str | None] = mapped_column(String(80))
    file_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    workshop_process_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_processes.id"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), index=True)
    reservation_number: Mapped[str | None] = mapped_column(String(120), index=True)
    contract_number: Mapped[str | None] = mapped_column(String(120), index=True)
    document_date: Mapped[date | None] = mapped_column(Date, index=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    archived_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class DocumentLink(TimestampMixin, Base):
    __tablename__ = "document_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str | None] = mapped_column(String(120), index=True)


class DocumentEvent(Base):
    __tablename__ = "document_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
