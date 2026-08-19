from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
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


class EmailChannel(TimestampMixin, Base):
    __tablename__ = "email_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    inbound_hash: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_task_mode: Mapped[str] = mapped_column(String(40), default="none", index=True)
    default_queue_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_queues.id", ondelete="SET NULL"), index=True
    )
    default_department_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_departments.id", ondelete="SET NULL"), index=True
    )
    default_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), index=True
    )
    default_subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_subcategories.id", ondelete="SET NULL"), index=True
    )
    default_document_type: Mapped[str | None] = mapped_column(String(80), index=True)
    default_assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    default_due_days: Mapped[int | None] = mapped_column(Integer)
    default_wait_days: Mapped[int | None] = mapped_column(Integer)


class EmailThread(TimestampMixin, Base):
    __tablename__ = "email_threads"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("email_channels.id"), index=True)
    subject: Mapped[str] = mapped_column(String(500), index=True)
    status: Mapped[str] = mapped_column(String(60), default="triage", index=True)
    content_type: Mapped[str | None] = mapped_column(String(60), index=True)
    nature: Mapped[str | None] = mapped_column(String(60), index=True)
    document_type: Mapped[str | None] = mapped_column(String(80), index=True)
    triage_notes: Mapped[str | None] = mapped_column(Text)
    sender_email: Mapped[str | None] = mapped_column(String(255), index=True)
    sender_name: Mapped[str | None] = mapped_column(String(255))
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    assigned_to_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    work_queue_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_queues.id", ondelete="SET NULL"), index=True
    )
    work_department_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_departments.id", ondelete="SET NULL"), index=True
    )
    work_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), index=True
    )
    work_subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_subcategories.id", ondelete="SET NULL"), index=True
    )
    classification_status: Mapped[str] = mapped_column(
        String(40), default="unclassified", index=True
    )
    classification_other_text: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    waiting_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    external_conversation_id: Mapped[str | None] = mapped_column(String(255), index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailMessage(TimestampMixin, Base):
    __tablename__ = "email_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("email_threads.id", ondelete="CASCADE"), index=True
    )
    external_message_id: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(20), index=True)
    state: Mapped[str] = mapped_column(String(40), default="received", index=True)
    sender: Mapped[str] = mapped_column(String(255))
    recipients_json: Mapped[list | None] = mapped_column(JSON)
    cc_json: Mapped[list | None] = mapped_column(JSON)
    subject: Mapped[str] = mapped_column(String(500))
    text_body: Mapped[str | None] = mapped_column(Text)
    html_body: Mapped[str | None] = mapped_column(Text)
    headers_json: Mapped[list | dict | None] = mapped_column(JSON)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    postmark_error: Mapped[str | None] = mapped_column(Text)


class EmailAttachment(TimestampMixin, Base):
    __tablename__ = "email_attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("email_messages.id", ondelete="CASCADE"), index=True
    )
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(160))
    content_id: Mapped[str | None] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    document_type: Mapped[str | None] = mapped_column(String(80), index=True)
    nature: Mapped[str | None] = mapped_column(String(60), index=True)
    destination: Mapped[str | None] = mapped_column(String(60), index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class EmailWebhookEvent(TimestampMixin, Base):
    __tablename__ = "email_webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)


class EmailAuditEvent(Base):
    __tablename__ = "email_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(
        ForeignKey("email_threads.id", ondelete="CASCADE"), index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_messages.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(80), index=True)
    details_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EmailChannelUser(Base):
    __tablename__ = "email_channel_users"
    __table_args__ = (UniqueConstraint("channel_id", "user_id", name="uq_email_channel_user"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailChannelRole(Base):
    __tablename__ = "email_channel_roles"
    __table_args__ = (UniqueConstraint("channel_id", "role_id", name="uq_email_channel_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    can_send_direct: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)


class EmailTemplate(TimestampMixin, Base):
    __tablename__ = "email_templates"
    __table_args__ = (UniqueConstraint("code", name="uq_email_template_code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(160))
    subject_template: Mapped[str | None] = mapped_column(String(500))
    body_template: Mapped[str] = mapped_column(Text)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_channels.id", ondelete="SET NULL"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), index=True
    )
    subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_subcategories.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
