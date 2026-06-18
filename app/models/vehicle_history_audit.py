from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class VehicleHistoryAudit(TimestampMixin, Base):
    __tablename__ = "vehicle_history_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    management_process_id: Mapped[int | None] = mapped_column(ForeignKey("management_processes.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    plate: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(80), default="open", index=True)
    phase: Mapped[str] = mapped_column(String(120), default="document_collection", index=True)
    responsible_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    priority: Mapped[str] = mapped_column(String(80), default="normal", index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    summary: Mapped[str | None] = mapped_column(Text)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class VehicleHistoryAuditDocument(TimestampMixin, Base):
    __tablename__ = "vehicle_history_audit_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("vehicle_history_audits.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    plate: Mapped[str] = mapped_column(String(40), index=True)
    document_type: Mapped[str] = mapped_column(String(80), index=True)
    source: Mapped[str] = mapped_column(String(80), default="history_audit", index=True)
    moment: Mapped[str] = mapped_column(String(80), default="unknown", index=True)
    link: Mapped[str | None] = mapped_column(Text)
    extraction_status: Mapped[str] = mapped_column(String(80), default="pending", index=True)
    confidence_level: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class VehicleHistoryAuditService(TimestampMixin, Base):
    __tablename__ = "vehicle_history_audit_services"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("vehicle_history_audits.id", ondelete="CASCADE"), index=True)
    service_date: Mapped[date | None] = mapped_column(Date, index=True)
    km: Mapped[int | None] = mapped_column(Integer, index=True)
    supplier: Mapped[str | None] = mapped_column(String(200), index=True)
    family: Mapped[str] = mapped_column(String(80), index=True)
    subtype: Mapped[str | None] = mapped_column(String(160), index=True)
    quantity: Mapped[str | None] = mapped_column(String(80))
    axle: Mapped[str | None] = mapped_column(String(80))
    side: Mapped[str | None] = mapped_column(String(80))
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"))
    confidence_level: Mapped[str] = mapped_column(String(40), default="medium", index=True)
    notes: Mapped[str | None] = mapped_column(Text)


class VehicleHistoryAuditIssue(TimestampMixin, Base):
    __tablename__ = "vehicle_history_audit_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("vehicle_history_audits.id", ondelete="CASCADE"), index=True)
    issue_type: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str] = mapped_column(Text)
    administrative_source: Mapped[str | None] = mapped_column(Text)
    technical_source: Mapped[str | None] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(80), default="medium", index=True)
    status: Mapped[str] = mapped_column(String(80), default="new", index=True)
    evidence: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    decision: Mapped[str | None] = mapped_column(Text)


class VehicleHistoryAuditTruth(TimestampMixin, Base):
    __tablename__ = "vehicle_history_audit_truths"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("vehicle_history_audits.id", ondelete="CASCADE"), unique=True)
    assumed_start_date: Mapped[date | None] = mapped_column(Date)
    last_reliable_km: Mapped[int | None] = mapped_column(Integer)
    last_valid_maintenance: Mapped[str | None] = mapped_column(Text)
    estimated_maintenance_count: Mapped[int | None] = mapped_column(Integer)
    bsi_status: Mapped[str | None] = mapped_column(String(160))
    telecharge_status: Mapped[str | None] = mapped_column(String(160))
    assumed_version: Mapped[str | None] = mapped_column(String(200))
    plan_to_follow: Mapped[str | None] = mapped_column(Text)
    pending_items: Mapped[str | None] = mapped_column(Text)
    confidence_level: Mapped[str] = mapped_column(String(40), default="medium", index=True)


class VehicleHistoryAuditRule(TimestampMixin, Base):
    __tablename__ = "vehicle_history_audit_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("vehicle_history_audits.id", ondelete="CASCADE"), index=True)
    rule_type: Mapped[str] = mapped_column(String(80), index=True)
    rule: Mapped[str] = mapped_column(Text)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    applies_when: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(80), default="active", index=True)
    observation: Mapped[str | None] = mapped_column(Text)
