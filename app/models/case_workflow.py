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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin
from app.models.tasks import TaskCase

OperationalCase = TaskCase


class ProcessPhaseInstance(TimestampMixin, Base):
    __tablename__ = "process_phase_instances"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','active','blocked','awaiting_validation','completed','skipped')",
            name="ck_process_phase_instances_status",
        ),
        CheckConstraint(
            "execution_mode IN ('direct','task')",
            name="ck_process_phase_instances_execution_mode",
        ),
        UniqueConstraint("process_instance_id", "phase_key", name="uq_process_phase_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    process_instance_id: Mapped[int] = mapped_column(
        ForeignKey("process_instances.id", ondelete="CASCADE"), index=True
    )
    phase_key: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(200))
    sort_order: Mapped[int] = mapped_column(Integer)
    definition_snapshot_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    execution_mode: Mapped[str] = mapped_column(String(24), default="direct", index=True)
    sensitive_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    validated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ProcessPhaseExecution(TimestampMixin, Base):
    __tablename__ = "process_phase_executions"
    __table_args__ = (
        CheckConstraint("kind IN ('direct','task')", name="ck_process_phase_execution_kind"),
        CheckConstraint(
            "status IN ('pending','active','completed','cancelled')",
            name="ck_process_phase_execution_status",
        ),
        UniqueConstraint("idempotency_key", name="uq_process_phase_execution_idempotency"),
        Index(
            "uq_process_phase_active_execution",
            "phase_instance_id",
            unique=True,
            postgresql_where=text("active = true"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    phase_instance_id: Mapped[int] = mapped_column(
        ForeignKey("process_phase_instances.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(160))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ProcessProposalAcceptance(Base):
    __tablename__ = "process_proposal_acceptances"
    __table_args__ = (
        UniqueConstraint(
            "process_instance_id", "proposal_version", name="uq_process_proposal_acceptance"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    process_instance_id: Mapped[int] = mapped_column(
        ForeignKey("process_instances.id", ondelete="CASCADE"), index=True
    )
    proposal_version: Mapped[int] = mapped_column(Integer)
    accepted_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source_reference: Mapped[str | None] = mapped_column(String(255))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowAuditEvent(Base):
    __tablename__ = "workflow_audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), index=True)
    aggregate_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revision: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkflowOutboxEvent(Base):
    __tablename__ = "workflow_outbox_events"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_workflow_outbox_idempotency"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), index=True)
    aggregate_id: Mapped[int] = mapped_column(Integer, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    payload_json: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class _CaseLinkMixin(TimestampMixin):
    __abstract__ = True
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("task_cases.id", ondelete="RESTRICT"), index=True
    )
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class CaseVehicleLink(_CaseLinkMixin, Base):
    __tablename__ = "case_vehicle_links"
    __table_args__ = (UniqueConstraint("case_id", "vehicle_id", name="uq_case_vehicle_link"),)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True
    )


class CaseDocumentLink(_CaseLinkMixin, Base):
    __tablename__ = "case_document_links"
    __table_args__ = (UniqueConstraint("case_id", "document_id", name="uq_case_document_link"),)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="RESTRICT"), index=True
    )


class CaseEmailLink(_CaseLinkMixin, Base):
    __tablename__ = "case_email_links"
    __table_args__ = (UniqueConstraint("case_id", "email_intake_id", name="uq_case_email_link"),)
    email_intake_id: Mapped[int] = mapped_column(
        ForeignKey("email_intakes.id", ondelete="RESTRICT"), index=True
    )


class CaseWorkshopLink(_CaseLinkMixin, Base):
    __tablename__ = "case_workshop_links"
    __table_args__ = (
        UniqueConstraint("case_id", "workshop_process_id", name="uq_case_workshop_link"),
    )
    workshop_process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_processes.id", ondelete="RESTRICT"), index=True
    )
