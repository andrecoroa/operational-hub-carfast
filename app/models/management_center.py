from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class ManagementProcessType(TimestampMixin, Base):
    __tablename__ = "management_process_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ManagementProcess(TimestampMixin, Base):
    __tablename__ = "management_processes"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_type_id: Mapped[int] = mapped_column(ForeignKey("management_process_types.id"))
    internal_reference: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(240))
    status: Mapped[str] = mapped_column(String(80), default="open", index=True)
    phase: Mapped[str] = mapped_column(String(120), default="information_request", index=True)
    priority: Mapped[str] = mapped_column(String(80), default="normal", index=True)
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    document_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    driver_name: Mapped[str | None] = mapped_column(String(200), index=True)
    pending_reason: Mapped[str | None] = mapped_column(String(160), index=True)
    pending_detail: Mapped[str | None] = mapped_column(Text)
    total_claim_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    total_cost_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    opened_on: Mapped[date | None] = mapped_column(Date, index=True)
    sla_due_on: Mapped[date | None] = mapped_column(Date, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    raw_summary_json: Mapped[dict | None] = mapped_column(JSON)


class ClaimIncident(TimestampMixin, Base):
    __tablename__ = "claim_incidents"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("management_processes.id", ondelete="CASCADE"), unique=True)
    sin_reference: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    accident_date: Mapped[date | None] = mapped_column(Date, index=True)
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    operational_status: Mapped[str] = mapped_column(String(80), default="information_request", index=True)
    rentway_status: Mapped[str | None] = mapped_column(String(120), index=True)
    has_missing_ar: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    has_missing_minimum_data: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    components_json: Mapped[dict | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)


class ClaimRentwayAR(TimestampMixin, Base):
    __tablename__ = "claim_rentway_ars"

    id: Mapped[int] = mapped_column(primary_key=True)
    ar_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    status: Mapped[str | None] = mapped_column(String(120), index=True)
    raw_state: Mapped[str | None] = mapped_column(String(120), index=True)
    request_date: Mapped[date | None] = mapped_column(Date, index=True)
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    vehicle_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    driver_name: Mapped[str | None] = mapped_column(String(200), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    ra_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    impro_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    daaa_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    insurance_policy: Mapped[str | None] = mapped_column(String(160), index=True)
    rental_station_out: Mapped[str | None] = mapped_column(String(160), index=True)
    created_by_rental_station: Mapped[str | None] = mapped_column(String(160), index=True)
    source_file: Mapped[str | None] = mapped_column(String(255), index=True)
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[dict | None] = mapped_column(JSON)


class ClaimRefstroLine(TimestampMixin, Base):
    __tablename__ = "claim_refstro_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    refstro_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    document_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    accident_date: Mapped[date | None] = mapped_column(Date, index=True)
    component: Mapped[str | None] = mapped_column(String(120), index=True)
    status: Mapped[str | None] = mapped_column(String(120), index=True)
    close_date: Mapped[date | None] = mapped_column(Date, index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    driver_name: Mapped[str | None] = mapped_column(String(200), index=True)
    claim_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    cost_value: Mapped[float | None] = mapped_column(Numeric(12, 2))
    source_file: Mapped[str | None] = mapped_column(String(255), index=True)
    source_row_number: Mapped[int | None] = mapped_column(Integer)
    raw_json: Mapped[dict | None] = mapped_column(JSON)


class ManagementProcessAssociation(TimestampMixin, Base):
    __tablename__ = "management_process_associations"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("management_processes.id", ondelete="CASCADE"), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    association_role: Mapped[str] = mapped_column(String(80), default="source", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ended_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ManagementRule(TimestampMixin, Base):
    __tablename__ = "management_rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_type_id: Mapped[int] = mapped_column(ForeignKey("management_process_types.id"))
    code: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(80), default="info", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ManagementAction(TimestampMixin, Base):
    __tablename__ = "management_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("management_processes.id", ondelete="CASCADE"), index=True)
    rule_id: Mapped[int | None] = mapped_column(ForeignKey("management_rules.id"))
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(80), default="open", index=True)
    mandatory: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    due_on: Mapped[date | None] = mapped_column(Date, index=True)
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ManagementEvidence(TimestampMixin, Base):
    __tablename__ = "management_evidences"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("management_processes.id", ondelete="CASCADE"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    external_url: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class ManagementHistory(Base):
    __tablename__ = "management_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    process_id: Mapped[int] = mapped_column(ForeignKey("management_processes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(120), index=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), index=True)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[str | None] = mapped_column(Text)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
