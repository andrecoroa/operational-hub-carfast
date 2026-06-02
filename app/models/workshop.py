from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class WorkshopProcess(TimestampMixin, Base):
    __tablename__ = "workshop_processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(240), index=True)
    creation_mode: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(80), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    plate_snapshot: Mapped[str | None] = mapped_column(String(40), index=True)
    current_phase_code: Mapped[str | None] = mapped_column(String(120), index=True)
    priority: Mapped[str] = mapped_column(String(80), default="normal", index=True)
    origin: Mapped[str | None] = mapped_column(String(120), index=True)
    origin_detail: Mapped[str | None] = mapped_column(Text)
    initial_km: Mapped[int | None] = mapped_column(Integer)
    initial_observation: Mapped[str | None] = mapped_column(Text)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)


class WorkshopProcessService(TimestampMixin, Base):
    __tablename__ = "workshop_process_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    service_code: Mapped[str] = mapped_column(String(120), index=True)
    service_label: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str | None] = mapped_column(Text)
    zone: Mapped[str | None] = mapped_column(String(120), index=True)
    short_observation: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkshopProcessPhase(TimestampMixin, Base):
    __tablename__ = "workshop_process_phases"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    phase_code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(80), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    data_json: Mapped[dict | None] = mapped_column(JSON)


class WorkshopProcessAlert(TimestampMixin, Base):
    __tablename__ = "workshop_process_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_process_phases.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(120), index=True)
    message: Mapped[str] = mapped_column(String(240))
    severity: Mapped[str] = mapped_column(String(40), default="warning", index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    source: Mapped[str | None] = mapped_column(String(120), index=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class WorkshopTechnicalReport(TimestampMixin, Base):
    __tablename__ = "workshop_technical_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_process_phases.id", ondelete="CASCADE")
    )
    report_code: Mapped[str] = mapped_column(String(120), index=True)
    report_name: Mapped[str] = mapped_column(String(180))
    reading_origin: Mapped[str] = mapped_column(String(80), index=True)
    reading_origin_detail: Mapped[str | None] = mapped_column(Text)
    report_moment: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(80), index=True)
    original_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    original_link: Mapped[str | None] = mapped_column(Text)
    raw_values_json: Mapped[dict | list | None] = mapped_column(JSON)
    extracted_values_json: Mapped[dict | list | None] = mapped_column(JSON)
    validated_values_json: Mapped[dict | list | None] = mapped_column(JSON)
    correction_json: Mapped[dict | None] = mapped_column(JSON)
    added_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    validated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observations: Mapped[str | None] = mapped_column(Text)


class WorkshopTechnicalCheck(TimestampMixin, Base):
    __tablename__ = "workshop_technical_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_process_phases.id", ondelete="CASCADE")
    )
    check_code: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(80), default="pending_review", index=True)
    observation: Mapped[str | None] = mapped_column(Text)
    evidence_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    evidence_link: Mapped[str | None] = mapped_column(Text)
    creates_task: Mapped[bool] = mapped_column(Boolean, default=False)
    potential_customer_charge: Mapped[bool] = mapped_column(Boolean, default=False)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    incident_id: Mapped[int | None] = mapped_column(Integer)
    detail_json: Mapped[dict | None] = mapped_column(JSON)


class WorkshopTechnicalIncident(Base):
    __tablename__ = "workshop_technical_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_process_phases.id", ondelete="CASCADE")
    )
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_technical_reports.id", ondelete="SET NULL")
    )
    check_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_technical_checks.id", ondelete="SET NULL")
    )
    related_field: Mapped[str | None] = mapped_column(String(160), index=True)
    incident_type: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(40), index=True)
    recommended_action: Mapped[str | None] = mapped_column(String(160), index=True)
    vehicle_can_circulate: Mapped[str | None] = mapped_column(String(80), index=True)
    evidence_document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"))
    evidence_link: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WorkshopClosureCheck(TimestampMixin, Base):
    __tablename__ = "workshop_closure_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("workshop_processes.id", ondelete="CASCADE"))
    check_code: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(80), default="pending_review", index=True)
    justification: Mapped[str | None] = mapped_column(Text)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
