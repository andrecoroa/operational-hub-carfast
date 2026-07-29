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


class WorkshopPhasedProcess(TimestampMixin, Base):
    __tablename__ = "workshop_phased_processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    public_reference: Mapped[str | None] = mapped_column(String(20), unique=True, index=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
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
    template_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_template_versions.id", ondelete="SET NULL")
    )
    template_snapshot_json: Mapped[dict | None] = mapped_column(JSON)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict | None] = mapped_column(JSON)


class WorkshopPublicCounter(Base):
    """Transactional yearly counter used by public workshop references."""

    __tablename__ = "workshop_public_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class WorkshopTemplate(TimestampMixin, Base):
    __tablename__ = "workshop_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    entry_reason_code: Mapped[str | None] = mapped_column(String(80), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class WorkshopTemplateVersion(TimestampMixin, Base):
    __tablename__ = "workshop_template_versions"
    __table_args__ = (UniqueConstraint("template_id", "version_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_templates.id", ondelete="CASCADE"),
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="published", index=True)
    change_note: Mapped[str | None] = mapped_column(Text)
    config_json: Mapped[dict] = mapped_column(JSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    stock_template_code: Mapped[str | None] = mapped_column(String(120))
    stock_template_version: Mapped[str | None] = mapped_column(String(80))


class WorkshopDiagnosticCatalogItem(TimestampMixin, Base):
    __tablename__ = "workshop_diagnostic_catalog_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    family: Mapped[str] = mapped_column(String(120), index=True)
    equipment: Mapped[str | None] = mapped_column(String(160))
    applicability_json: Mapped[dict | None] = mapped_column(JSON)
    phase_code: Mapped[str] = mapped_column(String(120), default="diagnostico", index=True)
    requirement: Mapped[str] = mapped_column(String(40), default="recommended", index=True)
    validity_days: Mapped[int | None] = mapped_column(Integer)
    history_rules_json: Mapped[dict | None] = mapped_column(JSON)
    expected_document_type: Mapped[str | None] = mapped_column(String(120))
    extraction_fields_json: Mapped[list | dict | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class WorkshopDiagnosticSuggestion(TimestampMixin, Base):
    __tablename__ = "workshop_diagnostic_suggestions"
    __table_args__ = (UniqueConstraint("process_id", "catalog_item_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE"),
        index=True,
    )
    catalog_item_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_diagnostic_catalog_items.id", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(40), default="suggested", index=True)
    origin: Mapped[str] = mapped_column(String(80), default="rules_engine", index=True)
    explanation: Mapped[str] = mapped_column(Text)
    rule_context_json: Mapped[dict | None] = mapped_column(JSON)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkshopMaterialNeed(TimestampMixin, Base):
    """Workshop-side material request; inventory and movements remain owned by Stock."""

    __tablename__ = "workshop_material_needs"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE"),
        index=True,
    )
    phase_code: Mapped[str] = mapped_column(String(120), index=True)
    origin: Mapped[str] = mapped_column(String(40), index=True)
    operation_code: Mapped[str] = mapped_column(String(120), index=True)
    operation_label: Mapped[str] = mapped_column(String(180))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    vehicle_variant: Mapped[str | None] = mapped_column(String(180))
    technician_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    location_id: Mapped[int | None] = mapped_column(ForeignKey("organizational_units.id"))
    material_code: Mapped[str | None] = mapped_column(String(120), index=True)
    material_description: Mapped[str] = mapped_column(String(240))
    requested_quantity: Mapped[str | None] = mapped_column(String(80))
    stock_status: Mapped[str] = mapped_column(
        String(40),
        default="unavailable",
        index=True,
    )
    stock_request_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    applied_confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    applied_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail_json: Mapped[dict | None] = mapped_column(JSON)


class WorkshopPhasedProcessService(TimestampMixin, Base):
    __tablename__ = "workshop_phased_process_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE")
    )
    service_code: Mapped[str] = mapped_column(String(120), index=True)
    service_label: Mapped[str] = mapped_column(String(160))
    detail: Mapped[str | None] = mapped_column(Text)
    zone: Mapped[str | None] = mapped_column(String(120), index=True)
    short_observation: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkshopPhasedProcessPhase(TimestampMixin, Base):
    __tablename__ = "workshop_phased_process_phases"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE")
    )
    phase_code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(80), index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    data_json: Mapped[dict | None] = mapped_column(JSON)


class WorkshopPhasedProcessAlert(TimestampMixin, Base):
    __tablename__ = "workshop_phased_process_alerts"

    def __init__(self, **kwargs):
        kwargs.setdefault("status", "open")
        super().__init__(**kwargs)

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE")
    )
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_process_phases.id", ondelete="CASCADE")
    )
    code: Mapped[str] = mapped_column(String(120), index=True)
    message: Mapped[str] = mapped_column(String(240))
    severity: Mapped[str] = mapped_column(String(40), default="warning", index=True)
    status: Mapped[str] = mapped_column(String(40), default="open", server_default="open", index=True)
    source: Mapped[str | None] = mapped_column(String(120), index=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class WorkshopPhasedTechnicalReport(TimestampMixin, Base):
    __tablename__ = "workshop_phased_technical_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE")
    )
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_process_phases.id", ondelete="CASCADE")
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


class WorkshopPhasedTechnicalCheck(TimestampMixin, Base):
    __tablename__ = "workshop_phased_technical_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE")
    )
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_process_phases.id", ondelete="CASCADE")
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


class WorkshopPhasedTechnicalIncident(Base):
    __tablename__ = "workshop_phased_technical_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE")
    )
    phase_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_process_phases.id", ondelete="CASCADE")
    )
    report_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_technical_reports.id", ondelete="SET NULL")
    )
    check_id: Mapped[int | None] = mapped_column(
        ForeignKey("workshop_phased_technical_checks.id", ondelete="SET NULL")
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


class WorkshopPhasedClosureCheck(TimestampMixin, Base):
    __tablename__ = "workshop_phased_closure_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("workshop_phased_processes.id", ondelete="CASCADE")
    )
    check_code: Mapped[str] = mapped_column(String(120), index=True)
    label: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(80), default="pending_review", index=True)
    justification: Mapped[str | None] = mapped_column(Text)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
