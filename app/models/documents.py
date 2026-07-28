from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class Document(TimestampMixin, Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str | None] = mapped_column(String(200), index=True)
    document_type: Mapped[str | None] = mapped_column(String(80), index=True)
    classification: Mapped[str | None] = mapped_column(String(120), index=True)
    source: Mapped[str | None] = mapped_column(String(80), index=True)
    entry_channel: Mapped[str | None] = mapped_column(String(120), index=True)
    source_sender: Mapped[str | None] = mapped_column(String(255), index=True)
    source_subject: Mapped[str | None] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255))
    file_name: Mapped[str] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(120))
    file_size: Mapped[int | None] = mapped_column(Integer)
    storage_provider: Mapped[str] = mapped_column(String(40), default="local")
    storage_path: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(Text)
    folder_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="received", index=True)
    confidentiality_level: Mapped[str | None] = mapped_column(String(40), index=True)
    retention_policy: Mapped[str | None] = mapped_column(String(80))
    file_hash: Mapped[str | None] = mapped_column(String(128), index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"))
    workshop_process_id: Mapped[int | None] = mapped_column(ForeignKey("workshop_processes.id"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"))
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    customer_name: Mapped[str | None] = mapped_column(String(200), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), index=True)
    reservation_number: Mapped[str | None] = mapped_column(String(120), index=True)
    contract_number: Mapped[str | None] = mapped_column(String(120), index=True)
    document_date: Mapped[date | None] = mapped_column(Date, index=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    archived_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class DocumentLink(TimestampMixin, Base):
    __tablename__ = "document_links"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    entity_type: Mapped[str] = mapped_column(String(120), index=True)
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str | None] = mapped_column(String(120), index=True)


class DocumentEvent(Base):
    __tablename__ = "document_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(120), index=True)
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class VehicleDocumentRecord(TimestampMixin, Base):
    __tablename__ = "vehicle_document_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    source_record_type: Mapped[str] = mapped_column(String(40), default="archive", index=True)
    main_group: Mapped[str] = mapped_column(String(40), index=True)
    subtype: Mapped[str | None] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(40), default="pending", index=True)
    comparison_state: Mapped[str | None] = mapped_column(String(40), index=True)
    process_reference: Mapped[str | None] = mapped_column(String(80), index=True)
    external_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    title: Mapped[str | None] = mapped_column(String(200), index=True)
    plate: Mapped[str | None] = mapped_column(String(40), index=True)
    vin: Mapped[str | None] = mapped_column(String(80), index=True)
    supplier_name: Mapped[str | None] = mapped_column(String(200), index=True)
    raw_description: Mapped[str | None] = mapped_column(Text)
    document_date: Mapped[date | None] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, index=True)
    km: Mapped[int | None] = mapped_column(Integer, index=True)
    end_km: Mapped[int | None] = mapped_column(Integer, index=True)
    has_physical_file: Mapped[bool] = mapped_column(Boolean, default=False)
    storage_path: Mapped[str | None] = mapped_column(Text)
    external_url: Mapped[str | None] = mapped_column(Text)
    source_system: Mapped[str | None] = mapped_column(String(80), index=True)
    metadata_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class VehicleDocumentRecordTag(TimestampMixin, Base):
    __tablename__ = "vehicle_document_record_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_document_records.id", ondelete="CASCADE"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    value: Mapped[str | None] = mapped_column(String(120), index=True)
    free_text: Mapped[str | None] = mapped_column(Text)
    source_kind: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class VehicleDocumentAlert(TimestampMixin, Base):
    __tablename__ = "vehicle_document_alerts"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_document_records.id", ondelete="SET NULL"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    alert_type: Mapped[str] = mapped_column(String(80), index=True)
    severity: Mapped[str] = mapped_column(String(40), default="warning", index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class VehicleDocumentPendingAction(TimestampMixin, Base):
    __tablename__ = "vehicle_document_pending_actions"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    record_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_document_records.id", ondelete="SET NULL"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id", ondelete="SET NULL"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    action_type: Mapped[str] = mapped_column(String(80), index=True)
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="open", index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class VehicleDocumentAuditField(TimestampMixin, Base):
    __tablename__ = "vehicle_document_audit_fields"
    __table_args__ = (UniqueConstraint("vehicle_id", "field_code", name="uq_vehicle_document_audit_field"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id", ondelete="CASCADE"), index=True)
    field_code: Mapped[str] = mapped_column(String(120), index=True)
    value_json: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
    audited_on: Mapped[date | None] = mapped_column(Date)
    observation: Mapped[str | None] = mapped_column(Text)
    document_basis: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))


class DiagnosticDocument(TimestampMixin, Base):
    """Diagnostic-specific metadata kept separate from generic document fields."""

    __tablename__ = "diagnostic_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"),
        unique=True,
        index=True,
    )
    diagnostic_type: Mapped[str] = mapped_column(String(120), index=True)
    diagnostic_status: Mapped[str] = mapped_column(
        String(40),
        default="received",
        index=True,
    )
    association_status: Mapped[str] = mapped_column(
        String(40),
        default="unassociated",
        index=True,
    )
    report_number: Mapped[str | None] = mapped_column(String(160), index=True)
    diagnostic_tool: Mapped[str | None] = mapped_column(String(160))
    diagnostic_tool_serial: Mapped[str | None] = mapped_column(String(160))
    technician_name: Mapped[str | None] = mapped_column(String(160))
    odometer_km: Mapped[int | None] = mapped_column(Integer)
    detected_plate: Mapped[str | None] = mapped_column(String(40), index=True)
    detected_vin: Mapped[str | None] = mapped_column(String(80), index=True)
    ocr_status: Mapped[str] = mapped_column(String(40), default="not_requested", index=True)
    ocr_confidence: Mapped[float | None] = mapped_column(Float)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_payload_json: Mapped[dict | list | None] = mapped_column(JSON)
    validation_status: Mapped[str] = mapped_column(
        String(40),
        default="pending",
        index=True,
    )
    validation_notes: Mapped[str | None] = mapped_column(Text)
    validated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiagnosticExtraction(Base):
    """Immutable, versioned extraction of a diagnostic PDF.

    The normalized fields on ``DiagnosticDocument`` are the operational view. This
    table keeps every extraction run so a new parser never destroys text, metadata
    or fields captured by an older parser.
    """

    __tablename__ = "diagnostic_extractions"

    id: Mapped[int] = mapped_column(primary_key=True)
    diagnostic_document_id: Mapped[int] = mapped_column(
        ForeignKey("diagnostic_documents.id", ondelete="CASCADE"),
        index=True,
    )
    extractor_name: Mapped[str] = mapped_column(String(120))
    extractor_version: Mapped[str] = mapped_column(String(40))
    parser_name: Mapped[str] = mapped_column(String(120))
    parser_version: Mapped[str] = mapped_column(String(40))
    source_machine: Mapped[str | None] = mapped_column(String(80), index=True)
    source_family: Mapped[str | None] = mapped_column(String(40), index=True)
    source_filename: Mapped[str | None] = mapped_column(String(255))
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    source_page_count: Mapped[int] = mapped_column(Integer)
    extraction_method: Mapped[str] = mapped_column(String(80))
    extraction_status: Mapped[str] = mapped_column(String(40), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    native_text: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    raw_metadata_json: Mapped[dict | list | None] = mapped_column(JSON)
    pages_json: Mapped[dict | list | None] = mapped_column(JSON)
    normalized_data_json: Mapped[dict | list | None] = mapped_column(JSON)
    dynamic_fields_json: Mapped[dict | list | None] = mapped_column(JSON)
    warnings_json: Mapped[dict | list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
