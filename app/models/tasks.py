from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(80), default="task", index=True)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    category: Mapped[str | None] = mapped_column(String(80), index=True)
    subcategory: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str] = mapped_column(String(80), index=True)
    priority: Mapped[str | None] = mapped_column(String(80), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    customer_contact: Mapped[str | None] = mapped_column(String(200))
    customer_email: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_phone: Mapped[str | None] = mapped_column(String(80), index=True)
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    reservation_number: Mapped[str | None] = mapped_column(String(120), index=True)
    contract_number: Mapped[str | None] = mapped_column(String(120), index=True)
    station: Mapped[str | None] = mapped_column(String(120), index=True)
    department: Mapped[str | None] = mapped_column(String(120), index=True)
    external_source_id: Mapped[str | None] = mapped_column(String(255), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    due_on: Mapped[date | None] = mapped_column(Date)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskComment(Base):
    __tablename__ = "task_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskDocument(Base):
    __tablename__ = "task_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    category: Mapped[str | None] = mapped_column(String(120), index=True)


class TaskHistory(Base):
    __tablename__ = "task_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    field_name: Mapped[str] = mapped_column(String(120), index=True)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
