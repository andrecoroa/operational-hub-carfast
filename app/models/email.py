from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
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
    __table_args__ = (
        CheckConstraint(
            "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
            name="ck_email_channels_assignment_mode",
        ),
        CheckConstraint(
            "(first_response_minutes IS NULL OR first_response_minutes >= 0) AND "
            "(resolution_minutes IS NULL OR resolution_minutes >= 0) AND "
            "warning_minutes >= 0",
            name="ck_email_channels_sla_minutes",
        ),
        Index("ux_email_channels_inbound_forward_address", "inbound_forward_address", unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    address: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    inbound_hash: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    inbound_forward_address: Mapped[str | None] = mapped_column(
        String(255), index=True
    )
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
    default_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    supervisor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assignment_mode: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    first_response_minutes: Mapped[int | None] = mapped_column(Integer)
    resolution_minutes: Mapped[int | None] = mapped_column(Integer)
    warning_minutes: Mapped[int] = mapped_column(Integer, default=60)
    pause_on_waiting: Mapped[bool] = mapped_column(Boolean, default=True)
    default_due_days: Mapped[int | None] = mapped_column(Integer)
    default_wait_days: Mapped[int | None] = mapped_column(Integer)


class EmailInboxRule(TimestampMixin, Base):
    __tablename__ = "email_inbox_rules"
    __table_args__ = (
        CheckConstraint(
            "assignment_mode IS NULL OR "
            "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
            name="ck_email_inbox_rules_assignment_mode",
        ),
        CheckConstraint(
            "(first_response_minutes IS NULL OR first_response_minutes >= 0) AND "
            "(resolution_minutes IS NULL OR resolution_minutes >= 0) AND "
            "(warning_minutes IS NULL OR warning_minutes >= 0)",
            name="ck_email_inbox_rules_sla_minutes",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(160))
    subject_match: Mapped[str] = mapped_column(String(500))
    match_type: Mapped[str] = mapped_column(String(20), default="contains", index=True)
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
    default_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    supervisor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assignment_mode: Mapped[str | None] = mapped_column(String(40), index=True)
    first_response_minutes: Mapped[int | None] = mapped_column(Integer)
    resolution_minutes: Mapped[int | None] = mapped_column(Integer)
    warning_minutes: Mapped[int | None] = mapped_column(Integer)
    pause_on_waiting: Mapped[bool | None] = mapped_column(Boolean)
    default_due_days: Mapped[int | None] = mapped_column(Integer)
    default_wait_days: Mapped[int | None] = mapped_column(Integer)
    auto_task_mode: Mapped[str | None] = mapped_column(String(40), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class EmailThread(TimestampMixin, Base):
    __tablename__ = "email_threads"
    __table_args__ = (
        CheckConstraint(
            "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
            name="ck_email_threads_assignment_mode",
        ),
        CheckConstraint(
            "assignment_state IN "
            "('assigned_user', 'assigned_team', 'team_unclaimed', 'waiting_assignment')",
            name="ck_email_threads_assignment_state",
        ),
        CheckConstraint(
            "(sla_first_response_minutes IS NULL OR sla_first_response_minutes >= 0) AND "
            "(sla_resolution_minutes IS NULL OR sla_resolution_minutes >= 0) AND "
            "sla_warning_minutes >= 0 AND sla_total_paused_seconds >= 0",
            name="ck_email_threads_sla_minutes",
        ),
    )

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
    executor_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    supervisor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assignment_mode: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    assignment_state: Mapped[str] = mapped_column(
        String(40), default="waiting_assignment", index=True
    )
    assigned_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claimed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    first_response_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    resolution_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_first_response_minutes: Mapped[int | None] = mapped_column(Integer)
    sla_resolution_minutes: Mapped[int | None] = mapped_column(Integer)
    sla_warning_minutes: Mapped[int] = mapped_column(Integer, default=60)
    sla_pause_on_waiting: Mapped[bool] = mapped_column(Boolean, default=True)
    sla_timezone: Mapped[str] = mapped_column(String(80), default="Europe/Lisbon")
    sla_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_total_paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
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


class EmailMessageDelivery(TimestampMixin, Base):
    __tablename__ = "email_message_deliveries"
    __table_args__ = (
        UniqueConstraint("webhook_event_id", name="uq_email_message_delivery_event"),
        UniqueConstraint(
            "channel_id",
            "logical_key",
            "canonical_marker",
            name="uq_email_message_delivery_canonical",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(
        ForeignKey("email_messages.id", ondelete="CASCADE"), index=True
    )
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("email_channels.id", ondelete="RESTRICT"), index=True
    )
    webhook_event_id: Mapped[int] = mapped_column(
        ForeignKey("email_webhook_events.id", ondelete="RESTRICT"), index=True
    )
    logical_key: Mapped[str] = mapped_column(String(128), index=True)
    canonical_marker: Mapped[str | None] = mapped_column(String(20))
    postmark_message_id: Mapped[str | None] = mapped_column(String(255), index=True)
    original_recipient: Mapped[str | None] = mapped_column(String(500))
    technical_recipient: Mapped[str | None] = mapped_column(String(500))
    inbound_address: Mapped[str | None] = mapped_column(String(500))
    mailbox_hash: Mapped[str | None] = mapped_column(String(255), index=True)
    to_json: Mapped[list | None] = mapped_column(JSON)
    cc_json: Mapped[list | None] = mapped_column(JSON)
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


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
    __table_args__ = (
        UniqueConstraint("channel_id", "user_id", name="uq_email_channel_user"),
        CheckConstraint(
            "visibility_mode IN ('scope_all', 'direct_only', 'consult')",
            name="ck_email_channel_users_visibility_mode",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    can_assume: Mapped[bool] = mapped_column(Boolean, default=False)
    can_assign: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_sla: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility_mode: Mapped[str] = mapped_column(String(40), default="scope_all")


class EmailChannelRole(Base):
    __tablename__ = "email_channel_roles"
    __table_args__ = (
        UniqueConstraint("channel_id", "role_id", name="uq_email_channel_role"),
        CheckConstraint(
            "visibility_mode IN ('scope_all', 'direct_only', 'consult')",
            name="ck_email_channel_roles_visibility_mode",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), index=True
    )
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"), index=True)
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_reply: Mapped[bool] = mapped_column(Boolean, default=False)
    can_send_direct: Mapped[bool] = mapped_column(Boolean, default=False)
    can_approve: Mapped[bool] = mapped_column(Boolean, default=False)
    can_assume: Mapped[bool] = mapped_column(Boolean, default=False)
    can_assign: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_sla: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility_mode: Mapped[str] = mapped_column(String(40), default="scope_all")


class EmailExecutorEligibility(TimestampMixin, Base):
    __tablename__ = "email_executor_eligibilities"
    __table_args__ = (
        UniqueConstraint(
            "channel_id", "category_id", "user_id", "team_id", name="uq_email_executor_eligibility"
        ),
        CheckConstraint(
            "(user_id IS NOT NULL AND team_id IS NULL) OR "
            "(user_id IS NULL AND team_id IS NOT NULL)",
            name="ck_email_executor_eligibility_target",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(
        ForeignKey("email_channels.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


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
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
