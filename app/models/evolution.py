from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class EvolutionRecord(TimestampMixin, Base):
    __tablename__ = "evolution_records"
    __table_args__ = (
        CheckConstraint(
            "record_type IN ('improvement', 'question', 'problem', 'feature')",
            name="ck_evolution_records_type",
        ),
        CheckConstraint(
            "status IN ('registered', 'analysis', 'approved', 'deferred', 'rejected', "
            "'implementation', 'completed')",
            name="ck_evolution_records_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_evolution_records_priority",
        ),
        CheckConstraint(
            "NOT (analysis_user_id IS NOT NULL AND analysis_team_id IS NOT NULL)",
            name="ck_evolution_records_single_responsible",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_type: Mapped[str] = mapped_column(String(40), index=True)
    module: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str] = mapped_column(Text)
    origin: Mapped[str | None] = mapped_column(String(160), index=True)
    priority: Mapped[str] = mapped_column(String(40), default="normal", index=True)
    status: Mapped[str] = mapped_column(String(40), default="registered", index=True)
    decision: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    analysis_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    analysis_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    reference_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    reference_chat: Mapped[str | None] = mapped_column(String(255))
    reference_branch: Mapped[str | None] = mapped_column(String(255))
    reference_commit: Mapped[str | None] = mapped_column(String(80))
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


class EvolutionRecordComment(Base):
    __tablename__ = "evolution_record_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("evolution_records.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvolutionRecordHistory(Base):
    __tablename__ = "evolution_record_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("evolution_records.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    field_name: Mapped[str] = mapped_column(String(80), index=True)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EvolutionRecordDocument(Base):
    __tablename__ = "evolution_record_documents"
    __table_args__ = (
        UniqueConstraint("record_id", "document_id", name="uq_evolution_record_document"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("evolution_records.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    linked_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
