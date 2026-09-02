from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
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


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
            name="ck_tasks_assignment_mode",
        ),
        CheckConstraint(
            "assignment_state IN "
            "('assigned_user', 'assigned_team', 'team_unclaimed', 'waiting_assignment')",
            name="ck_tasks_assignment_state",
        ),
        CheckConstraint(
            "(sla_first_response_minutes IS NULL OR sla_first_response_minutes >= 0) AND "
            "(sla_resolution_minutes IS NULL OR sla_resolution_minutes >= 0) AND "
            "sla_warning_minutes >= 0 AND sla_total_paused_seconds >= 0",
            name="ck_tasks_sla_minutes",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_cases.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    task_type: Mapped[str] = mapped_column(String(80), default="task", index=True)
    ticket_type_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_desk_ticket_types.id", ondelete="SET NULL"), index=True
    )
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
    invoice_number: Mapped[str | None] = mapped_column(String(120), index=True)
    station: Mapped[str | None] = mapped_column(String(120), index=True)
    department: Mapped[str | None] = mapped_column(String(120), index=True)
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
    provisional_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_proposals.id", ondelete="RESTRICT"), index=True
    )
    provisional_subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_proposals.id", ondelete="RESTRICT"), index=True
    )
    classification_status: Mapped[str] = mapped_column(
        String(40), default="unclassified", index=True
    )
    classification_other_text: Mapped[str | None] = mapped_column(Text)
    legacy_classification: Mapped[str | None] = mapped_column(Text)
    classification_updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    classification_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_source_id: Mapped[str | None] = mapped_column(String(255), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    parent_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    supervisor_user_id: Mapped[int | None] = mapped_column(
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
    delegated_to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    delegated_to_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    waiting_for_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    waiting_for_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    waiting_reason: Mapped[str | None] = mapped_column(String(80), index=True)
    waiting_reason_detail: Mapped[str | None] = mapped_column(Text)
    waiting_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    due_on: Mapped[date | None] = mapped_column(Date)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_response_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    resolution_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    sla_first_response_minutes: Mapped[int | None] = mapped_column(Integer)
    sla_resolution_minutes: Mapped[int | None] = mapped_column(Integer)
    sla_warning_minutes: Mapped[int] = mapped_column(Integer, default=60)
    sla_pause_on_waiting: Mapped[bool] = mapped_column(Boolean, default=True)
    sla_timezone: Mapped[str] = mapped_column(String(80), default="Europe/Lisbon")
    sla_paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_total_paused_seconds: Mapped[int] = mapped_column(Integer, default=0)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_for: Mapped[date | None] = mapped_column(Date, index=True)
    guided_flow_code: Mapped[str | None] = mapped_column(String(120), index=True)
    recurrence_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(80), index=True)
    recurrence_interval: Mapped[int | None] = mapped_column(Integer)
    recurrence_next_on: Mapped[date | None] = mapped_column(Date, index=True)
    recurrence_created_from_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    task_template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("task_template_versions.id", ondelete="RESTRICT"), index=True
    )
    task_template_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    task_template_snapshot_digest: Mapped[str | None] = mapped_column(String(64))
    process_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("process_instances.id", ondelete="SET NULL"), index=True
    )
    process_step_code: Mapped[str | None] = mapped_column(String(120), index=True)


class TaskCase(TimestampMixin, Base):
    """One-level work container. The case itself is never a counted task."""

    __tablename__ = "task_cases"
    __table_args__ = (
        CheckConstraint(
            "workspace IN ('tasks_support', 'administration')",
            name="ck_task_cases_workspace",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    workspace: Mapped[str] = mapped_column(String(40), index=True)
    work_queue_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_queues.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )


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


class TaskAssignmentEvent(Base):
    __tablename__ = "task_assignment_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(60), index=True)
    from_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    from_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    to_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    details_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskSlaEvent(Base):
    __tablename__ = "task_sla_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(60), index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    details_json: Mapped[dict | None] = mapped_column(JSON)


class TaskParticipant(Base):
    __tablename__ = "task_participants"
    __table_args__ = (UniqueConstraint("task_id", "user_id", "role", name="uq_task_participant_role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(40), default="participant", index=True)
    status: Mapped[str] = mapped_column(String(40), default="active", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskEmailOrigin(Base):
    __tablename__ = "task_email_origins"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), unique=True, index=True)
    message_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    sender: Mapped[str | None] = mapped_column(String(255), index=True)
    recipients_json: Mapped[list | None] = mapped_column(JSON)
    subject: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    mailbox: Mapped[str | None] = mapped_column(String(255), index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
    rule_code: Mapped[str | None] = mapped_column(String(120), index=True)


class TaskHelpRequest(Base):
    __tablename__ = "task_help_requests"
    __table_args__ = (
        CheckConstraint(
            "(requested_user_id IS NOT NULL AND requested_team_id IS NULL) OR "
            "(requested_user_id IS NULL AND requested_team_id IS NOT NULL)",
            name="ck_task_help_requests_single_target",
        ),
        CheckConstraint(
            "status IN ('pending', 'accepted', 'completed', 'cancelled')",
            name="ck_task_help_requests_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    requested_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    requested_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    requested_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    message: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    previous_task_status: Mapped[str] = mapped_column(String(80), default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskNotification(Base):
    __tablename__ = "task_notifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class TaskGuidedFlowRun(TimestampMixin, Base):
    __tablename__ = "task_guided_flow_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    flow_code: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(80), default="active", index=True)
    started_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskGuidedFlowStepRun(TimestampMixin, Base):
    __tablename__ = "task_guided_flow_step_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    flow_run_id: Mapped[int] = mapped_column(ForeignKey("task_guided_flow_runs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    step_code: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(80), default="pending", index=True)
    data_json: Mapped[dict | None] = mapped_column(JSON)
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    generated_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))


class TaskRecurrenceTemplate(TimestampMixin, Base):
    __tablename__ = "task_recurrence_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Lisbon")
    frequency: Mapped[str] = mapped_column(String(40), index=True)
    interval: Mapped[int] = mapped_column(Integer, default=1)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    workspace: Mapped[str] = mapped_column(String(40), index=True)
    task_type: Mapped[str] = mapped_column(String(80), index=True)
    task_title: Mapped[str] = mapped_column(String(200))
    task_description: Mapped[str | None] = mapped_column(Text)
    task_priority: Mapped[str] = mapped_column(String(40), default="normal")
    task_category: Mapped[str | None] = mapped_column(String(80))
    task_subcategory: Mapped[str | None] = mapped_column(String(120))
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
    due_offset_days: Mapped[int] = mapped_column(Integer, default=0)
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class TaskRecurrenceOccurrence(Base):
    __tablename__ = "task_recurrence_occurrences"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "scheduled_for",
            name="uq_task_recurrence_occurrence_schedule",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("task_recurrence_templates.id", ondelete="CASCADE"), index=True
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(40), default="created", index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class QuickRecord(TimestampMixin, Base):
    __tablename__ = "quick_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace: Mapped[str] = mapped_column(String(80), default="operational", index=True)
    record_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(80), default="new", index=True)
    priority: Mapped[str | None] = mapped_column(String(80), index=True)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    customer_contact: Mapped[str | None] = mapped_column(String(200))
    customer_email: Mapped[str | None] = mapped_column(String(255), index=True)
    customer_phone: Mapped[str | None] = mapped_column(String(80), index=True)
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    station: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"))
    assigned_to_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    converted_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
