from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class PhotoActionDefinition(TimestampMixin, Base):
    """Published, immutable configuration understood by the future flow builder."""

    __tablename__ = "photo_action_definitions"
    __table_args__ = (
        UniqueConstraint("code", "version_number", name="uq_photo_action_definition_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(40), default="published", index=True)
    config_json: Mapped[dict] = mapped_column(JSON)
    change_note: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class PhotoMedia(TimestampMixin, Base):
    """Image-specific metadata for one physical object stored as a Document."""

    __tablename__ = "photo_media"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), unique=True, index=True
    )
    sha256: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    thumbnail_storage_path: Mapped[str] = mapped_column(Text)
    thumbnail_content_type: Mapped[str] = mapped_column(String(120), default="image/jpeg")
    thumbnail_size: Mapped[int] = mapped_column(Integer)
    metadata_policy: Mapped[str] = mapped_column(String(40), default="strip_exif")


class PhotoCaptureSession(TimestampMixin, Base):
    """Execution of a take-photo step, linked to operational contexts by reference."""

    __tablename__ = "photo_capture_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int | None] = mapped_column(
        ForeignKey("photo_action_definitions.id", ondelete="SET NULL"), index=True
    )
    definition_code: Mapped[str | None] = mapped_column(String(120), index=True)
    definition_version: Mapped[int | None] = mapped_column(Integer)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    instructions: Mapped[str | None] = mapped_column(Text)
    config_snapshot_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    required: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    task_flow_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_guided_flow_step_runs.id", ondelete="CASCADE"), index=True
    )
    workshop_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_processes.id", ondelete="CASCADE"), index=True
    )
    phased_process_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE"), index=True
    )
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_process_phases.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    attempt_number: Mapped[int] = mapped_column(Integer, default=1)
    repeats_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("photo_capture_sessions.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)


class PhotoCaptureItem(TimestampMixin, Base):
    __tablename__ = "photo_capture_items"
    __table_args__ = (
        UniqueConstraint("session_id", "photo_media_id", name="uq_photo_capture_item_media"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("photo_capture_sessions.id", ondelete="CASCADE"), index=True
    )
    photo_media_id: Mapped[int] = mapped_column(
        ForeignKey("photo_media.id", ondelete="RESTRICT"), index=True
    )
    category: Mapped[str] = mapped_column(String(40), default="other", index=True)
    observation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="captured", index=True)
    capture_source: Mapped[str] = mapped_column(String(40), index=True)
    is_new_capture: Mapped[bool] = mapped_column(Boolean, default=True)
    captured_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    client_captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    location_latitude: Mapped[float | None] = mapped_column(Float)
    location_longitude: Mapped[float | None] = mapped_column(Float)
    location_accuracy_m: Mapped[float | None] = mapped_column(Float)
    location_consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replaces_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("photo_capture_items.id", ondelete="SET NULL")
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
