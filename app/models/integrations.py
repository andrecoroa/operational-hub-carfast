from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class EmailIntake(TimestampMixin, Base):
    __tablename__ = "email_intakes"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_mailbox: Mapped[str] = mapped_column(String(255), index=True)
    sender: Mapped[str | None] = mapped_column(String(255), index=True)
    subject: Mapped[str | None] = mapped_column(String(255), index=True)
    body_preview: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    email_url: Mapped[str | None] = mapped_column(Text)
    attachments_url: Mapped[str | None] = mapped_column(Text)
    list_item_id: Mapped[str | None] = mapped_column(String(255), index=True)
    list_item_url: Mapped[str | None] = mapped_column(Text)
    external_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(60), default="received", index=True)
    target_entity_type: Mapped[str | None] = mapped_column(String(80), index=True)
    target_entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    target_url: Mapped[str | None] = mapped_column(Text)
    routing_note: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    payload_json: Mapped[dict | None] = mapped_column(JSON)


class EmailIntakeAttachment(TimestampMixin, Base):
    __tablename__ = "email_intake_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_intake_id: Mapped[int] = mapped_column(ForeignKey("email_intakes.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(160))
    size: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    archive_url: Mapped[str | None] = mapped_column(Text)
    archive_folder_path: Mapped[str | None] = mapped_column(Text)
    decision_note: Mapped[str | None] = mapped_column(Text)
