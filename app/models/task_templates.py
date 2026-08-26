from datetime import datetime

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class TaskTemplate(TimestampMixin, Base):
    __tablename__ = "task_templates"
    __table_args__ = (UniqueConstraint("code", name="uq_task_templates_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class TaskTemplateVersion(TimestampMixin, Base):
    __tablename__ = "task_template_versions"
    __table_args__ = (
        UniqueConstraint("template_id", "version", name="uq_task_template_version"),
        CheckConstraint("status IN ('draft','published','retired')", name="ck_task_template_version_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("task_templates.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    definition_json: Mapped[dict] = mapped_column(JSON)
    definition_digest: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class TaskTemplateUsage(Base):
    __tablename__ = "task_template_usages"
    __table_args__ = (UniqueConstraint("template_id", "user_id", name="uq_task_template_usage"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("task_templates.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ProcessModel(TimestampMixin, Base):
    __tablename__ = "process_models"
    __table_args__ = (UniqueConstraint("code", name="uq_process_models_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(200))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProcessModelVersion(TimestampMixin, Base):
    __tablename__ = "process_model_versions"
    __table_args__ = (
        UniqueConstraint("model_id", "version", name="uq_process_model_version"),
        CheckConstraint("status IN ('draft','published','retired')", name="ck_process_model_version_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(ForeignKey("process_models.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    definition_json: Mapped[dict] = mapped_column(JSON)
    definition_digest: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProcessInstance(TimestampMixin, Base):
    __tablename__ = "process_instances"
    __table_args__ = (
        CheckConstraint("status IN ('active','blocked','completed','cancelled')", name="ck_process_instance_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("process_model_versions.id", ondelete="RESTRICT"), index=True)
    model_snapshot_json: Mapped[dict] = mapped_column(JSON)
    model_snapshot_digest: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(24), default="active", index=True)
    source: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    organizational_unit_code: Mapped[str | None] = mapped_column(String(80), index=True)
    manager_exception_justification: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)


class ProcessInstanceEvent(Base):
    __tablename__ = "process_instance_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_instance_id: Mapped[int] = mapped_column(ForeignKey("process_instances.id", ondelete="CASCADE"), index=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    details_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
