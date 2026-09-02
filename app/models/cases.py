from datetime import datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


def opaque_id() -> str:
    return str(uuid4())


class ProcessDefinition(TimestampMixin, Base):
    __tablename__ = "process_definitions"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ProcessDefinitionVersion(TimestampMixin, Base):
    __tablename__ = "process_definition_versions"
    __table_args__ = (
        UniqueConstraint("definition_id", "version", name="uq_process_definition_version"),
        CheckConstraint(
            "status IN ('draft','published','retired')", name="definition_version_status"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("process_definitions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    change_note: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PhaseDefinition(TimestampMixin, Base):
    __tablename__ = "phase_definitions"
    __table_args__ = (
        UniqueConstraint("definition_version_id", "key", name="uq_phase_definition_version_key"),
        UniqueConstraint(
            "definition_version_id", "sort_order", name="uq_phase_definition_version_order"
        ),
        UniqueConstraint("id", "definition_version_id", name="uq_phase_definition_id_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    definition_version_id: Mapped[int] = mapped_column(
        ForeignKey("process_definition_versions.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(180))
    sort_order: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(80), default="consultation", index=True)
    instructions: Mapped[str | None] = mapped_column(Text)
    execution_policy: Mapped[str] = mapped_column(String(40), default="direct_or_task")
    sensitive_validation: Mapped[bool] = mapped_column(Boolean, default=False)


def _persisted_status(version: ProcessDefinitionVersion) -> str:
    history = inspect(version).attrs.status.history
    return history.deleted[0] if history.deleted else version.status


@event.listens_for(Session, "before_flush")
def protect_published_process_definitions(session: Session, *_: object) -> None:
    """Prevent ORM writes from mutating a snapshot after it has been published."""
    for item in session.dirty | session.deleted:
        if isinstance(item, ProcessDefinitionVersion):
            original_status = _persisted_status(item)
            if original_status != "draft":
                allowed_retirement = (
                    item in session.dirty
                    and original_status == "published"
                    and item.status == "retired"
                    and {attr.key for attr in inspect(item).attrs if attr.history.has_changes()}
                    <= {"status", "retired_at", "updated_at"}
                )
                if not allowed_retirement:
                    raise ValueError("Published or retired process versions are immutable")
        elif isinstance(item, PhaseDefinition):
            version = session.get(ProcessDefinitionVersion, item.definition_version_id)
            if version and _persisted_status(version) != "draft":
                raise ValueError("Phases of published or retired versions are immutable")
    for item in session.new:
        if isinstance(item, PhaseDefinition):
            version = session.get(ProcessDefinitionVersion, item.definition_version_id)
            if version and _persisted_status(version) != "draft":
                raise ValueError("Phases of published or retired versions are immutable")


class OperationalCase(TimestampMixin, Base):
    __tablename__ = "operational_cases"
    __table_args__ = (
        CheckConstraint("status IN ('open','suspended','closed')", name="operational_case_status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), default=opaque_id, unique=True)
    human_code: Mapped[str | None] = mapped_column(String(80), unique=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    organizational_unit_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizational_units.id"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ProcessInstance(TimestampMixin, Base):
    __tablename__ = "process_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','active','blocked','completed','cancelled')",
            name="process_instance_status",
        ),
        UniqueConstraint("operation_key", name="uq_process_instance_operation_key"),
        UniqueConstraint("id", "definition_version_id", name="uq_process_instance_id_version"),
        Index(
            "uq_process_instance_active_sale",
            "proposal_logical_id",
            "vehicle_id",
            "process_kind",
            unique=True,
            sqlite_where=text("deleted_at IS NULL AND status IN ('draft','active','blocked')"),
            postgresql_where=text("deleted_at IS NULL AND status IN ('draft','active','blocked')"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), default=opaque_id, unique=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("operational_cases.id", ondelete="RESTRICT"), index=True
    )
    definition_version_id: Mapped[int] = mapped_column(
        ForeignKey("process_definition_versions.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(220))
    status: Mapped[str] = mapped_column(String(40), default="draft", index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), index=True)
    proposal_logical_id: Mapped[str | None] = mapped_column(String(160), index=True)
    process_kind: Mapped[str] = mapped_column(String(80), default="generic", index=True)
    accepted_proposal_version: Mapped[int | None] = mapped_column(Integer)
    operation_key: Mapped[str] = mapped_column(String(320))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    blocked_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ProcessProposalAcceptance(TimestampMixin, Base):
    __tablename__ = "process_proposal_acceptances"
    __table_args__ = (
        UniqueConstraint("process_id", "proposal_version", name="uq_process_proposal_version"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("process_instances.id", ondelete="RESTRICT"), index=True
    )
    proposal_version: Mapped[int] = mapped_column(Integer)
    source_reference: Mapped[str | None] = mapped_column(String(240))
    accepted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PhaseInstance(TimestampMixin, Base):
    __tablename__ = "phase_instances"
    __table_args__ = (
        UniqueConstraint("process_id", "definition_phase_id", name="uq_phase_instance_definition"),
        ForeignKeyConstraint(
            ["process_id", "definition_version_id"],
            ["process_instances.id", "process_instances.definition_version_id"],
            name="fk_phase_instance_process_version",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["definition_phase_id", "definition_version_id"],
            ["phase_definitions.id", "phase_definitions.definition_version_id"],
            name="fk_phase_instance_definition_version",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            "status IN ('pending','active','delegated','awaiting_validation',"
            "'blocked','completed','skipped')",
            name="phase_instance_status",
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(36), default=opaque_id, unique=True)
    process_id: Mapped[int] = mapped_column(Integer, index=True)
    definition_phase_id: Mapped[int] = mapped_column(Integer, index=True)
    definition_version_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    execution_mode: Mapped[str | None] = mapped_column(String(40), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    validated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class PhaseExecution(TimestampMixin, Base):
    __tablename__ = "phase_executions"
    __table_args__ = (
        CheckConstraint("kind IN ('direct','task','subprocess')", name="phase_execution_kind"),
        CheckConstraint(
            "status IN ('pending','active','completed','terminated')", name="phase_execution_status"
        ),
        CheckConstraint(
            "(kind = 'task' AND (status = 'pending' OR task_id IS NOT NULL)) OR kind <> 'task'",
            name="task_execution_has_task",
        ),
        CheckConstraint(
            "(active AND status IN ('pending','active')) OR "
            "(NOT active AND status IN ('completed','terminated'))",
            name="execution_active_status",
        ),
        Index(
            "uq_phase_executions_one_active",
            "phase_id",
            unique=True,
            sqlite_where=text("active = 1"),
            postgresql_where=text("active IS TRUE"),
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    phase_id: Mapped[int] = mapped_column(
        ForeignKey("phase_instances.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="RESTRICT"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(320), unique=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseVehicleLink(TimestampMixin, Base):
    __tablename__ = "case_vehicle_links"
    __table_args__ = (UniqueConstraint("case_id", "vehicle_id", name="uq_case_vehicle_link"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("operational_cases.id", ondelete="RESTRICT"), index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CaseDocumentLink(TimestampMixin, Base):
    __tablename__ = "case_document_links"
    __table_args__ = (UniqueConstraint("case_id", "document_id", name="uq_case_document_link"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("operational_cases.id", ondelete="RESTRICT"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CaseTaskLink(TimestampMixin, Base):
    __tablename__ = "case_task_links"
    __table_args__ = (UniqueConstraint("case_id", "task_id", name="uq_case_task_link"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("operational_cases.id", ondelete="RESTRICT"), index=True
    )
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="RESTRICT"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CaseEmailLink(TimestampMixin, Base):
    __tablename__ = "case_email_links"
    __table_args__ = (UniqueConstraint("case_id", "email_intake_id", name="uq_case_email_link"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("operational_cases.id", ondelete="RESTRICT"), index=True
    )
    email_intake_id: Mapped[int] = mapped_column(
        ForeignKey("email_intakes.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CaseWorkshopLink(TimestampMixin, Base):
    __tablename__ = "case_workshop_links"
    __table_args__ = (
        UniqueConstraint("case_id", "workshop_process_id", name="uq_case_workshop_link"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("operational_cases.id", ondelete="RESTRICT"), index=True
    )
    workshop_process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_processes.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class WorkflowAuditEvent(Base):
    __tablename__ = "workflow_audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(120), index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    revision: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    idempotency_key: Mapped[str | None] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowOutboxEvent(Base):
    __tablename__ = "workflow_outbox_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(320), unique=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), index=True)
    aggregate_id: Mapped[str] = mapped_column(String(120), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
