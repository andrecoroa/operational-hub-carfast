from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.api.auth import require_method_permission
from app.core.config import settings
from app.core.database import get_db
from app.documents import SourceReference
from app.documents.adapters import upsert_external_link_document
from app.models.documents import Document, DocumentLink
from app.models.tasks import Task
from app.models.vehicles import Vehicle, VehicleExternalSnapshot
from app.models.workshop_phased import (
    WorkshopPhasedClosureCheck as WorkshopClosureCheck,
)
from app.models.workshop_phased import (
    WorkshopPhasedProcess as WorkshopProcess,
)
from app.models.workshop_phased import (
    WorkshopPhasedProcessAlert as WorkshopProcessAlert,
)
from app.models.workshop_phased import (
    WorkshopPhasedProcessPhase as WorkshopProcessPhase,
)
from app.models.workshop_phased import (
    WorkshopPhasedProcessService as WorkshopProcessService,
)
from app.models.workshop_phased import (
    WorkshopPhasedTechnicalCheck as WorkshopTechnicalCheck,
)
from app.models.workshop_phased import (
    WorkshopPhasedTechnicalIncident as WorkshopTechnicalIncident,
)
from app.models.workshop_phased import (
    WorkshopPhasedTechnicalReport as WorkshopTechnicalReport,
)
from app.services.photo_capture import required_photo_blockers
from app.services.work_classification import apply_source_work_default
from app.services.workshop_configuration import WORKSHOP_STOCK_STATUSES
from app.services.workshop_report_extractor import (
    extract_workshop_report_values,
    extract_workshop_report_values_from_bytes,
)
from app.services.workshop_templates import (
    STELLANTIS_REPORTS,
    TECHNICAL_CHECKS,
    WORKSHOP_CREATION_MODES,
    WORKSHOP_ENTRY_ORIGINS,
    WORKSHOP_PHASE_TEMPLATE,
    WORKSHOP_PRIORITIES,
    WORKSHOP_PROCESS_TYPE_PHASED,
    WORKSHOP_SERVICE_OPTIONS,
    build_process_title,
    service_label_by_code,
)

router = APIRouter(
    prefix="/workshop",
    tags=["workshop"],
    dependencies=[
        Depends(require_method_permission("workshop.read", "workshop.write"))
    ],
)
DbSession = Annotated[Session, Depends(get_db)]
MAX_TECHNICAL_REPORT_UPLOAD_BYTES = 25 * 1024 * 1024

SERVICE_CODES = {service["code"] for service in WORKSHOP_SERVICE_OPTIONS}
ORIGIN_CODES = {origin["code"] for origin in WORKSHOP_ENTRY_ORIGINS}
PRIORITY_CODES = {priority["code"] for priority in WORKSHOP_PRIORITIES}
CREATION_MODE_CODES = {mode["code"] for mode in WORKSHOP_CREATION_MODES}
REPORT_CODES = {report["code"] for report in STELLANTIS_REPORTS}
REPORT_LABELS = {report["code"]: report["label"] for report in STELLANTIS_REPORTS}
CHECK_LABELS = {check["code"]: check["label"] for check in TECHNICAL_CHECKS}
CHECK_STATUSES = {"ok", "not_ok", "not_applicable", "pending_review"}
READING_ORIGINS = {"stellantis_machine", "autel", "other"}
REPORT_MOMENTS = {"initial", "final"}
WORKSHOP_DOCUMENTS_BASE_PATH = (
    r"C:\Users\andre\OneDrive - D'accord Invest - Serviços Partilhados SA"
    r"\CARFAST - OFICINA - OFICINA\CarFast v2 - Oficina\Documentos Processos por anexar ao processo"
)
WORKSHOP_DOCUMENT_TYPES = {
    "workshop_photo",
    "workshop_diagnostic",
    "workshop_bsi",
    "workshop_report",
    "workshop_work_order",
    "workshop_quote",
    "workshop_supplier_invoice",
    "workshop_evidence",
    "workshop_other",
}
STELLANTIS_BRANDS = {
    "abarth",
    "alfa romeo",
    "citroen",
    "citroën",
    "ds",
    "fiat",
    "jeep",
    "lancia",
    "maserati",
    "opel",
    "peugeot",
    "ram",
    "vauxhall",
}
REPORT_STATUSES = {
    "pending",
    "added",
    "read_automatically",
    "pending_validation",
    "validated",
    "corrected_manually",
    "unable_to_read",
    "not_applicable",
}


def _authorized_report_source(original_link: str) -> str:
    clean = str(original_link or "").strip().strip('"')
    if not clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Seleciona um documento PDF já arquivado ou carrega o ficheiro.",
        )
    if "://" in clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A extração por URL externa não é permitida. Importa primeiro o documento.",
        )
    configured_root = str(settings.document_archive_root or "").strip()
    if not configured_root:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="O arquivo documental autorizado não está configurado.",
        )
    root = Path(configured_root).expanduser().resolve()
    candidate = Path(clean).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O relatório não pertence ao arquivo documental autorizado.",
        ) from exc
    if not resolved.is_file() or resolved.suffix.lower() != ".pdf":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="O documento autorizado deve ser um ficheiro PDF.",
        )
    return str(resolved)


def _snapshot_value(data: dict[str, Any], keys: list[str]) -> Any:
    normalized = {str(key).lower().replace("_", ""): value for key, value in (data or {}).items()}
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
        compact_key = key.lower().replace("_", "")
        if compact_key in normalized and normalized[compact_key] not in (None, ""):
            return normalized[compact_key]
    return None


def _vehicle_snapshot_data(db: Session | None, vehicle: Vehicle | None) -> dict[str, Any]:
    if not db or not vehicle:
        return {}
    snapshot = db.scalar(
        select(VehicleExternalSnapshot)
        .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
        .order_by(VehicleExternalSnapshot.updated_at.desc(), VehicleExternalSnapshot.id.desc())
    )
    return dict(snapshot.data_json or {}) if snapshot else {}


def _vehicle_summary(
    vehicle: Vehicle | None,
    fallback_plate: str | None = None,
    db: Session | None = None,
) -> dict[str, Any]:
    if not vehicle:
        return {
            "id": None,
            "plate": fallback_plate,
            "rentway_unit_nr": None,
            "brand": None,
            "model": None,
            "version": None,
            "vin": None,
            "lifecycle_status": None,
            "operational_status": None,
            "active": None,
            "fuel": None,
            "last_service": None,
            "next_service": None,
            "warranty_end_date": None,
            "inspection_date": None,
            "purchase_date": None,
        }
    snapshot = _vehicle_snapshot_data(db, vehicle)
    return {
        "id": vehicle.id,
        "plate": vehicle.plate or fallback_plate,
        "rentway_unit_nr": vehicle.rentway_unit_nr,
        "brand": vehicle.brand,
        "model": vehicle.model,
        "version": vehicle.version,
        "vin": vehicle.vin,
        "lifecycle_status": vehicle.lifecycle_status,
        "operational_status": vehicle.operational_status,
        "active": vehicle.active,
        "fuel": _snapshot_value(snapshot, ["fuel", "combustivel", "combustível"]),
        "last_service": _snapshot_value(
            snapshot,
            ["last_service", "lastservice", "last_service_done", "lastservicedone", "ultimo_servico"],
        ),
        "next_service": _snapshot_value(snapshot, ["next_service", "nextservice", "proximo_servico"]),
        "warranty_end_date": _snapshot_value(
            snapshot,
            ["warrantyenddate", "warranty_end_date", "warrantyend", "fim_garantia"],
        ),
        "inspection_date": _snapshot_value(snapshot, ["inspection_date", "inspectiondate", "ipo", "data_inspecao"]),
        "purchase_date": _snapshot_value(snapshot, ["purchase_date", "purchasedate", "purchase_dat", "data_compra"]),
    }


def _is_stellantis_vehicle(vehicle: Vehicle | None) -> bool:
    if not vehicle or not vehicle.brand:
        return False
    return vehicle.brand.strip().lower() in STELLANTIS_BRANDS


def _workshop_document_type(document_type: str | None, default: str = "workshop_evidence") -> str:
    if document_type in WORKSHOP_DOCUMENT_TYPES:
        return document_type
    return default


def _workshop_document_folder(process: WorkshopProcess) -> str:
    metadata = process.metadata_json or {}
    return metadata.get("document_folder_path") or WORKSHOP_DOCUMENTS_BASE_PATH


def _document_title(process: WorkshopProcess, vehicle: Vehicle | None, label: str) -> str:
    plate = (vehicle.plate if vehicle else process.plate_snapshot) or "Sem matrícula"
    return f"{label} - {plate} - Processo #{process.id}"


def _upsert_workshop_document_from_link(
    db: Session,
    *,
    process: WorkshopProcess,
    vehicle: Vehicle | None,
    link: str | None,
    title: str,
    document_type: str | None,
    user_id: int | None,
    existing_document_id: int | None = None,
    source_subject: str | None = None,
) -> int | None:
    clean_link = (link or "").strip()
    if not clean_link:
        return existing_document_id

    clean_type = _workshop_document_type(document_type)
    clean_plate = ((vehicle.plate if vehicle else process.plate_snapshot) or "").strip().upper()
    return upsert_external_link_document(
        db,
        source_reference=SourceReference(
            module="workshop",
            entity_type="workshop_phased_process",
            entity_id=str(process.id),
            display_snapshot=title,
        ),
        link=clean_link,
        title=title,
        document_type=clean_type,
        classification="workshop",
        entry_channel="workshop_process_link",
        folder_path=_workshop_document_folder(process),
        vehicle_id=process.vehicle_id,
        plate=clean_plate or None,
        user_id=user_id,
        existing_document_id=existing_document_id,
        source_subject=source_subject,
    )


def _technical_report_response(report: WorkshopTechnicalReport) -> dict[str, Any]:
    return {
        "id": report.id,
        "report_code": report.report_code,
        "report_name": report.report_name,
        "reading_origin": report.reading_origin,
        "report_moment": report.report_moment,
        "status": report.status,
        "original_link": report.original_link,
        "original_document_id": report.original_document_id,
        "extracted_values": report.extracted_values_json,
        "validated_values": report.validated_values_json,
        "correction": report.correction_json,
        "observations": report.observations,
        "added_at": report.added_at,
        "validated_by_id": report.validated_by_id,
        "validated_at": report.validated_at,
    }


def _document_response(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "document_type": document.document_type,
        "classification": document.classification,
        "status": document.status,
        "vehicle_id": document.vehicle_id,
        "workshop_process_id": None,
        "plate": document.plate,
        "storage_path": document.storage_path,
        "external_url": document.external_url,
        "folder_path": document.folder_path,
    }


class WorkshopServiceInput(BaseModel):
    service_code: str
    detail: str | None = None
    zone: str | None = None
    short_observation: str | None = None


class WorkshopServiceAdd(BaseModel):
    service_code: str
    detail: str | None = None
    zone: str | None = None
    short_observation: str | None = None
    added_by_id: int | None = None

    @model_validator(mode="after")
    def validate_service(self) -> "WorkshopServiceAdd":
        if self.service_code not in SERVICE_CODES:
            raise ValueError(f"Serviço inválido: {self.service_code}.")
        if self.service_code == "other" and not self.detail:
            raise ValueError("Descrição do serviço Outro é obrigatória.")
        return self


class WorkshopProcessCreate(BaseModel):
    vehicle_id: int | None = None
    plate: str | None = None
    creation_mode: str = "immediate_entry"
    services: list[WorkshopServiceInput] = Field(min_length=1)
    title_manual: str | None = None
    km_current: int | None = None
    origin: str | None = None
    origin_detail: str | None = None
    priority: str = "normal"
    responsible_user_id: int | None = None
    created_by_id: int | None = None
    initial_observation: str | None = None
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def validate_process(self) -> "WorkshopProcessCreate":
        if not self.vehicle_id:
            raise ValueError("Seleciona uma viatura real da frota antes de criar o processo.")
        if self.creation_mode not in CREATION_MODE_CODES:
            raise ValueError("Tipo de criação inválido.")
        if self.priority not in PRIORITY_CODES:
            raise ValueError("Prioridade inválida.")
        if self.origin and self.origin not in ORIGIN_CODES:
            raise ValueError("Origem da entrada inválida.")
        if self.origin == "other" and not self.origin_detail:
            raise ValueError("Descrição da origem é obrigatória quando a origem é Outro.")
        service_codes = [service.service_code for service in self.services]
        invalid_services = [code for code in service_codes if code not in SERVICE_CODES]
        if invalid_services:
            raise ValueError(f"Serviço inválido: {', '.join(invalid_services)}.")
        if "other" in service_codes and not self.title_manual:
            raise ValueError("Título manual é obrigatório quando o serviço é Outro.")
        other_services = [service for service in self.services if service.service_code == "other"]
        if other_services and not any(service.detail for service in other_services):
            raise ValueError("Descrição do serviço Outro é obrigatória.")
        if self.creation_mode == "appointment" and not self.scheduled_at:
            raise ValueError("Data/hora prevista é obrigatória para marcação.")
        return self


class WorkshopProcessSummary(BaseModel):
    id: int
    title: str
    process_type: str
    creation_mode: str
    status: str
    current_phase_code: str | None
    vehicle_id: int | None
    plate: str | None
    priority: str
    alerts: list[dict[str, Any]]


class WorkshopReceptionConfirm(BaseModel):
    km_entry: int | None = None
    entry_at: str | None = None
    process_origin: str | None = None
    priority: str | None = None
    reception_location: str | None = None
    received_by: str | None = None
    key_delivered: str | None = None
    documents_received: str | None = None
    main_request: str | None = None
    reported_symptom: str | None = None
    initial_observation: str | None = None
    immobilized: str | None = None
    quadrant_photo_link: str | None = None
    quadrant_photo_file_name: str | None = None
    vehicle_photo_links: dict[str, str] | None = None
    entry_photo_file_name: str | None = None
    document_link: str | None = None
    visible_damage_status: str | None = None
    damage_origin: str | None = None
    damage_description: str | None = None
    damage_needs_claim_link: str | None = None
    requested_service: str | None = None
    planned_supplier: str | None = None
    initial_authorization_needed: str | None = None
    initial_authorization_reason: str | None = None
    estimated_value: float | None = None
    responsible_user_id: int | None = None
    next_step: str | None = None
    confirmed_by_id: int | None = None


class WorkshopHistoryCheckConfirm(BaseModel):
    internal_history_checked: str = "pending_review"
    open_accident_reports: str = "pending_review"
    accident_reports_detail: str | None = None
    previous_processes_reviewed: str = "pending_review"
    relevant_interventions_identified: str = "pending_review"
    relevant_interventions_summary: str | None = None
    repeated_incidence: str = "pending_review"
    repeated_incidence_description: str | None = None
    related_previous_process: str | None = None
    history_observation: str | None = None
    service_box_checked: str | None = None
    service_box_link: str | None = None
    service_box_reason: str | None = None
    service_box_document_type: str | None = None
    service_box_last_checked_at: str | None = None
    service_box_validity_days: str | None = None
    service_box_needed: str | None = None
    service_box_observation: str | None = None
    campaigns_checked: str | None = None
    campaigns_link: str | None = None
    campaigns_references: str | None = None
    campaigns_reason: str | None = None
    campaigns_document_type: str | None = None
    campaigns_active: str | None = None
    campaign_number: str | None = None
    campaign_description: str | None = None
    maintenance_plan_checked: str | None = None
    maintenance_plan_link: str | None = None
    maintenance_plan_reason: str | None = None
    maintenance_plan_document_type: str | None = None
    maintenance_plan_attached: str | None = None
    maintenance_plan_confirmed: str | None = None
    interval_km: int | None = None
    interval_months: int | None = None
    rentway_next_service_date: str | None = None
    rentway_next_service_km: int | None = None
    calculated_next_service_date: str | None = None
    calculated_next_service_km: int | None = None
    rentway_vs_calculation: str | None = None
    maintenance_plan_observation: str | None = None
    service_to_validate: str | None = None
    last_service_date: str | None = None
    last_service_km: int | None = None
    last_service_supplier: str | None = None
    last_service_document: str | None = None
    last_service_source: str | None = None
    suspicious_repetition: str | None = None
    service_history_observation: str | None = None
    pending_damage_update: str | None = None
    pending_claims: str | None = None
    technical_audit_status: str | None = None
    open_identified_problems: str | None = None
    pending_tasks: str | None = None
    sale_blocked: str | None = None
    diagnosis_focus: str | None = None
    required_reports: str | None = None
    diagnosis_questions: str | None = None
    technical_priority: str | None = None
    operational_validation_status: str | None = None
    reserve_reason: str | None = None
    confirmed_by_id: int | None = None

    @model_validator(mode="after")
    def validate_document_types(self) -> "WorkshopHistoryCheckConfirm":
        for document_type in (
            self.service_box_document_type,
            self.campaigns_document_type,
            self.maintenance_plan_document_type,
        ):
            if document_type is not None and document_type not in WORKSHOP_DOCUMENT_TYPES:
                raise ValueError("Tipo documental de oficina inválido.")
        return self


class WorkshopTechnicalReportCreate(BaseModel):
    report_code: str
    reading_origin: str = "stellantis_machine"
    reading_origin_detail: str | None = None
    report_moment: str = "initial"
    original_link: str | None = None
    document_type: str | None = "workshop_report"
    raw_values: dict[str, Any] | list[Any] | None = None
    extracted_values: dict[str, Any] | list[Any] | None = None
    added_by_id: int | None = None
    observations: str | None = None
    allow_blank: bool = False

    @model_validator(mode="after")
    def validate_report(self) -> "WorkshopTechnicalReportCreate":
        if self.report_code not in REPORT_CODES:
            raise ValueError("Relatório técnico inválido.")
        if self.reading_origin not in READING_ORIGINS:
            raise ValueError("Origem da leitura inválida.")
        if self.reading_origin == "other" and not self.reading_origin_detail:
            raise ValueError("Descrição da origem é obrigatória quando a origem é Outro.")
        if self.report_moment not in REPORT_MOMENTS:
            raise ValueError("Momento do relatório inválido.")
        if self.document_type is not None and self.document_type not in WORKSHOP_DOCUMENT_TYPES:
            raise ValueError("Tipo documental de oficina inválido.")
        return self


class WorkshopTechnicalReportValidate(BaseModel):
    validated_values: dict[str, Any] | list[Any]
    correction: dict[str, Any] | None = None
    validation_decision: str = "validate"
    validated_by_id: int | None = None
    observations: str | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "WorkshopTechnicalReportValidate":
        if self.validation_decision not in {
            "validate",
            "correct_and_validate",
            "keep_pending",
            "reject_reading",
        }:
            raise ValueError("Decisão de validação inválida.")
        return self


class WorkshopTechnicalReportUpdate(BaseModel):
    report_code: str | None = None
    reading_origin: str | None = None
    reading_origin_detail: str | None = None
    report_moment: str | None = None
    original_link: str | None = None
    document_type: str | None = None
    raw_values: dict[str, Any] | list[Any] | None = None
    extracted_values: dict[str, Any] | list[Any] | None = None
    observations: str | None = None
    allow_blank: bool = False

    @model_validator(mode="after")
    def validate_report_update(self) -> "WorkshopTechnicalReportUpdate":
        if self.report_code is not None and self.report_code not in REPORT_CODES:
            raise ValueError("Relatório técnico inválido.")
        if self.reading_origin is not None and self.reading_origin not in READING_ORIGINS:
            raise ValueError("Origem da leitura inválida.")
        if self.report_moment is not None and self.report_moment not in REPORT_MOMENTS:
            raise ValueError("Momento do relatório inválido.")
        if self.reading_origin == "other" and not self.reading_origin_detail:
            raise ValueError("Descrição da origem é obrigatória quando a origem é Outro.")
        if self.document_type is not None and self.document_type not in WORKSHOP_DOCUMENT_TYPES:
            raise ValueError("Tipo documental de oficina inválido.")
        return self


class WorkshopTechnicalReportExtract(BaseModel):
    report_code: str
    original_link: str

    @model_validator(mode="after")
    def validate_extract(self) -> "WorkshopTechnicalReportExtract":
        if self.report_code not in REPORT_CODES:
            raise ValueError("Relatório técnico inválido.")
        if not self.original_link.strip():
            raise ValueError("Indica primeiro o link ou caminho do relatório.")
        return self


class WorkshopTechnicalCheckUpsert(BaseModel):
    check_code: str
    status: str
    observation: str | None = None
    evidence_link: str | None = None
    evidence_document_type: str | None = "workshop_evidence"
    creates_task: bool = False
    potential_customer_charge: bool = False
    task_title: str | None = None
    task_responsible_user_id: int | None = None
    task_priority: str | None = "normal"
    detail: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_check(self) -> "WorkshopTechnicalCheckUpsert":
        if self.check_code not in CHECK_LABELS:
            raise ValueError("Verificação técnica inválida.")
        if self.status not in CHECK_STATUSES:
            raise ValueError("Estado da verificação inválido.")
        if self.creates_task and not self.task_title:
            raise ValueError("Título da tarefa é obrigatório quando cria tarefa.")
        if self.evidence_document_type is not None and self.evidence_document_type not in WORKSHOP_DOCUMENT_TYPES:
            raise ValueError("Tipo documental de oficina inválido.")
        return self


class WorkshopProcessDocumentCreate(BaseModel):
    title: str | None = None
    document_type: str = "workshop_evidence"
    url_original: str | None = None
    url_archive: str | None = None
    added_by_id: int | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def validate_document(self) -> "WorkshopProcessDocumentCreate":
        if self.document_type not in WORKSHOP_DOCUMENT_TYPES:
            raise ValueError("Tipo documental de oficina inválido.")
        if not ((self.url_original or "").strip() or (self.url_archive or "").strip()):
            raise ValueError("Indica pelo menos um link ou caminho.")
        return self


class WorkshopTechnicalIncidentCreate(BaseModel):
    report_id: int | None = None
    check_id: int | None = None
    related_field: str | None = None
    incident_type: str
    description: str
    severity: str
    recommended_action: str | None = None
    vehicle_can_circulate: str | None = None
    evidence_link: str | None = None
    created_by_id: int | None = None


class WorkshopDiagnosisDecisionConfirm(BaseModel):
    main_diagnosis: str
    intervention_type: str | None = None
    affected_system: str | None = None
    severity: str
    probable_cause: str | None = None
    diagnosis_observation: str | None = None
    vehicle_can_circulate: str
    needs_repair: bool = False
    needs_budget: bool = False
    needs_approval: bool = False
    potential_customer_charge: bool = False
    warranty: bool = False
    charge_reason: str | None = None
    customer_contract: str | None = None
    estimated_charge_value: float | None = None
    charge_evidence_link: str | None = None
    warranty_reason: str | None = None
    warranty_evidence_link: str | None = None
    next_action: str
    next_action_responsible_user_id: int | None = None
    next_action_due_at: datetime | None = None
    decision_observation: str | None = None
    create_task: bool = False
    decided_by_id: int | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> "WorkshopDiagnosisDecisionConfirm":
        if self.potential_customer_charge and not self.charge_evidence_link:
            # Non-blocking in product terms, but we still want the caller to be deliberate.
            self.charge_evidence_link = None
        if self.create_task and not self.next_action_responsible_user_id:
            raise ValueError("Responsável é obrigatório quando cria tarefa de próxima ação.")
        return self


class WorkshopBudgetApprovalUpdate(BaseModel):
    supplier: str | None = None
    requested_by_id: int | None = None
    request_description: str | None = None
    services_included: list[str] | None = None
    supplier_deadline_at: datetime | None = None
    budget_received: bool = False
    estimated_value: float | None = None
    vat_included: bool | None = None
    budget_description: str | None = None
    budget_link: str | None = None
    budget_valid_until: datetime | None = None
    needs_approval: bool = True
    approver_user_id: int | None = None
    approval_status: str = "pending"
    approved_value: float | None = None
    rejection_reason: str | None = None
    final_result: str | None = None
    next_action: str | None = None
    observation: str | None = None
    confirmed_by_id: int | None = None


class WorkshopRepairExecutionUpdate(BaseModel):
    execution_type: str | None = None
    mechanic_user_id: int | None = None
    intervention_description: str | None = None
    parts_used: list[dict[str, Any]] | None = None
    result: str | None = None
    final_quadrant_photo_link: str | None = None
    final_km_visible: int | None = None
    final_evidence_links: dict[str, str] | None = None
    final_observation: str | None = None
    confirmed_by_id: int | None = None


class WorkshopClosureConfirm(BaseModel):
    final_result: str
    vehicle_ready: str
    final_test_done: str | None = None
    can_return_to_fleet: str | None = None
    final_km: int | None = None
    new_vehicle_operational_status: str
    final_observation: str
    closed_by_id: int | None = None
    close_with_pending_items: bool = False
    pending_justification: str | None = None
    pending_responsible_user_id: int | None = None
    pending_due_at: datetime | None = None


def _find_vehicle(db: Session, vehicle_id: int | None, plate: str | None) -> Vehicle | None:
    if vehicle_id:
        return db.get(Vehicle, vehicle_id)
    if plate:
        return db.scalar(select(Vehicle).where(Vehicle.plate == plate))
    return None


def _get_process_or_404(db: Session, process_id: int) -> WorkshopProcess:
    process = db.get(WorkshopProcess, process_id)
    if not process:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processo não encontrado.",
        )
    return process


def _get_phase_or_404(
    db: Session,
    process_id: int,
    phase_code: str,
) -> WorkshopProcessPhase:
    phase = db.scalar(
        select(WorkshopProcessPhase).where(
            WorkshopProcessPhase.process_id == process_id,
            WorkshopProcessPhase.phase_code == phase_code,
        )
    )
    if not phase:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fase {phase_code} não encontrada.",
        )
    return phase


def _phase_template_by_code(phase_code: str) -> dict[str, Any] | None:
    return next(
        (phase for phase in WORKSHOP_PHASE_TEMPLATE if phase["code"] == phase_code),
        None,
    )


def _ensure_phase(
    db: Session,
    process: WorkshopProcess,
    phase_code: str,
) -> WorkshopProcessPhase:
    phase = db.scalar(
        select(WorkshopProcessPhase).where(
            WorkshopProcessPhase.process_id == process.id,
            WorkshopProcessPhase.phase_code == phase_code,
        )
    )
    template = _phase_template_by_code(phase_code)
    if phase:
        if template:
            phase.name = template["name"]
            phase.sort_order = template["sort_order"]
            phase.data_json = {
                **(phase.data_json or {}),
                "purpose": (phase.data_json or {}).get("purpose") or template.get("purpose"),
            }
        return phase
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Fase {phase_code} não encontrada.",
        )
    phase = WorkshopProcessPhase(
        process_id=process.id,
        phase_code=phase_code,
        name=template["name"],
        status="not_started",
        sort_order=template["sort_order"],
        data_json={"purpose": template.get("purpose")},
    )
    db.add(phase)
    db.flush()
    return phase


def _ensure_expected_phases(db: Session, process: WorkshopProcess) -> None:
    for template in WORKSHOP_PHASE_TEMPLATE:
        _ensure_phase(db, process, template["code"])


def _add_alert_once(
    db: Session,
    process_id: int,
    code: str,
    message: str,
    severity: str = "warning",
    source: str | None = None,
    phase_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> WorkshopProcessAlert:
    alert = db.scalar(
        select(WorkshopProcessAlert).where(
            WorkshopProcessAlert.process_id == process_id,
            WorkshopProcessAlert.code == code,
            WorkshopProcessAlert.status == "open",
        )
    )
    if alert:
        return alert
    alert = WorkshopProcessAlert(
        process_id=process_id,
        phase_id=phase_id,
        code=code,
        message=message,
        severity=severity,
        status="open",
        source=source,
        detail_json=detail,
    )
    db.add(alert)
    return alert


def _resolve_alerts(
    db: Session,
    process_id: int,
    codes: set[str],
    resolved_by_id: int | None = None,
) -> None:
    if not codes:
        return
    alerts = db.scalars(
        select(WorkshopProcessAlert).where(
            WorkshopProcessAlert.process_id == process_id,
            WorkshopProcessAlert.code.in_(codes),
            WorkshopProcessAlert.status == "open",
        )
    ).all()
    for alert in alerts:
        alert.status = "resolved"
        alert.resolved_at = datetime.utcnow()
        alert.resolved_by_id = resolved_by_id


def _report_value(values: dict[str, Any] | list[Any] | None, key: str) -> Any:
    if not isinstance(values, dict):
        return None
    if key in values:
        return values[key]
    normalized_key = key.replace("_", "").lower()
    for item_key, item_value in values.items():
        normalized_item_key = str(item_key).replace("_", "").replace(" ", "").lower()
        if normalized_item_key == normalized_key:
            return item_value
    return None


def _has_report_payload(
    original_link: str | None,
    raw_values: dict[str, Any] | list[Any] | None,
    extracted_values: dict[str, Any] | list[Any] | None,
) -> bool:
    if str(original_link or "").strip():
        return True
    for values in (raw_values, extracted_values):
        if isinstance(values, dict) and any(
            str(value or "").strip() for value in values.values()
        ):
            return True
        if isinstance(values, list) and values:
            return True
    return False


def _truthy_validation(value: Any) -> bool:
    return str(value or "").strip().lower() in {
        "yes",
        "sim",
        "ok",
        "correto",
        "correct",
        "true",
        "1",
    }


def _verification_option_satisfied(
    value: str | None,
    evidence_link: str | None = None,
    has_validated_report: bool = False,
    reason: str | None = None,
    references: str | None = None,
    require_reference_when_yes: bool = False,
    require_reason_when_no: bool = True,
) -> bool:
    normalized = str(value or "").strip().lower()
    if has_validated_report:
        return True
    if normalized == "yes":
        if require_reference_when_yes and not str(references or "").strip():
            return False
        return bool(str(evidence_link or "").strip())
    if normalized in {"no", "not_applicable"}:
        return bool(str(reason or "").strip()) if normalized == "no" and require_reason_when_no else True
    if normalized == "evidence_link":
        return bool(str(evidence_link or "").strip())
    if normalized == "no_items":
        return True
    return False


def _mark_phase(
    phase: WorkshopProcessPhase,
    status_value: str,
    data: dict[str, Any] | None = None,
    completed_by_id: int | None = None,
) -> None:
    if status_value in {"completed", "validated"}:
        db = object_session(phase)
        blockers = (
            required_photo_blockers(
                db,
                phased_process_id=phase.process_id,
                phase_id=phase.id,
            )
            if db
            else []
        )
        if blockers:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Fotografias obrigatórias: " + " ".join(blockers),
            )
    phase.status = status_value
    if data is not None:
        phase.data_json = {**(phase.data_json or {}), **data}
    if status_value in {"completed", "pending_review", "validated"}:
        phase.completed_at = datetime.utcnow()
        phase.completed_by_id = completed_by_id


def _build_creation_alerts(
    process: WorkshopProcess,
    creation: WorkshopProcessCreate,
) -> list[WorkshopProcessAlert]:
    alerts: list[WorkshopProcessAlert] = []
    if creation.km_current is None:
        alerts.append(
            WorkshopProcessAlert(
                process_id=process.id,
                code="km_current_missing",
                message="KM atual em falta",
                severity="warning",
                status="open",
                source="process_creation",
            )
        )
    if not creation.initial_observation:
        alerts.append(
            WorkshopProcessAlert(
                process_id=process.id,
                code="initial_observation_missing",
                message="Observação inicial em falta",
                severity="warning",
                status="open",
                source="process_creation",
            )
        )
    if not creation.responsible_user_id:
        alerts.append(
            WorkshopProcessAlert(
                process_id=process.id,
                code="responsible_missing",
                message="Responsável em falta",
                severity="info",
                status="open",
                source="process_creation",
            )
        )
    if not creation.origin:
        alerts.append(
            WorkshopProcessAlert(
                process_id=process.id,
                code="entry_origin_missing",
                message="Origem da entrada em falta",
                severity="info",
                status="open",
                source="process_creation",
            )
        )
    return alerts


@router.get("/process-config")
def get_process_config() -> dict[str, Any]:
    return {
        "process_type": WORKSHOP_PROCESS_TYPE_PHASED,
        "creation_modes": WORKSHOP_CREATION_MODES,
        "services": WORKSHOP_SERVICE_OPTIONS,
        "entry_origins": WORKSHOP_ENTRY_ORIGINS,
        "priorities": WORKSHOP_PRIORITIES,
        "phases": WORKSHOP_PHASE_TEMPLATE,
        "stellantis_reports": STELLANTIS_REPORTS,
        "technical_checks": TECHNICAL_CHECKS,
    }


@router.get("/stock-contract")
def get_workshop_stock_contract() -> dict[str, Any]:
    """Describe the future Stock boundary without reporting fictitious inventory."""

    return {
        "schema": "carfast.workshop-stock.v1",
        "available": False,
        "message": "Stock ainda não disponível",
        "ownership": {
            "workshop": [
                "material_need",
                "operation",
                "need_origin",
                "vehicle",
                "variant",
                "technician",
                "location",
                "application_confirmation",
            ],
            "stock": [
                "suggestions",
                "availability",
                "reservations",
                "inventory_movements",
                "costs",
                "consumption",
                "returns",
            ],
        },
        "request_fields": [
            "workshop_process_reference",
            "material_need_id",
            "operation_code",
            "origin",
            "vehicle_id",
            "vehicle_variant",
            "technician_user_id",
            "location_code",
            "material_code",
            "material_description",
            "requested_quantity",
        ],
        "future_response_fields": [
            "stock_request_reference",
            "suggestions",
            "availability",
            "reservation_status",
        ],
        "visual_states": sorted(WORKSHOP_STOCK_STATUSES),
        "template_link": {
            "independent_versioning": True,
            "workshop_fields": ["stock_template_code", "stock_template_version"],
        },
    }


@router.post(
    "/processes/phased",
    response_model=WorkshopProcessSummary,
    status_code=status.HTTP_201_CREATED,
)
def create_phased_workshop_process(
    creation: WorkshopProcessCreate,
    db: DbSession,
) -> WorkshopProcessSummary:
    vehicle = _find_vehicle(db, creation.vehicle_id, creation.plate)
    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Viatura da frota não encontrada.",
        )
    service_codes = [service.service_code for service in creation.services]
    title = build_process_title(service_codes, creation.title_manual)
    process_status = "scheduled" if creation.creation_mode == "appointment" else "open"
    current_phase = "administrative_reception"

    process = WorkshopProcess(
        process_type=WORKSHOP_PROCESS_TYPE_PHASED,
        title=title,
        creation_mode=creation.creation_mode,
        status=process_status,
        vehicle_id=vehicle.id if vehicle else creation.vehicle_id,
        plate_snapshot=vehicle.plate if vehicle else creation.plate,
        current_phase_code=current_phase,
        priority=creation.priority,
        origin=creation.origin,
        origin_detail=creation.origin_detail,
        initial_km=creation.km_current,
        initial_observation=creation.initial_observation,
        responsible_user_id=creation.responsible_user_id,
        created_by_id=creation.created_by_id,
        scheduled_at=creation.scheduled_at,
        metadata_json={
            "title_source": "manual" if "other" in service_codes else "automatic",
            "document_folder_path": WORKSHOP_DOCUMENTS_BASE_PATH,
            "document_folder_scope": "workshop_shared",
            "document_folder_status": "defined",
        },
    )
    db.add(process)
    db.flush()

    for index, service in enumerate(creation.services, start=1):
        db.add(
            WorkshopProcessService(
                process_id=process.id,
                service_code=service.service_code,
                service_label=service_label_by_code(service.service_code),
                detail=service.detail,
                zone=service.zone,
                short_observation=service.short_observation,
                sort_order=index,
            )
        )

    for phase in WORKSHOP_PHASE_TEMPLATE:
        status_value = phase.get("default_status", "not_started")
        if phase["code"] == current_phase:
            status_value = "pending"
        db.add(
            WorkshopProcessPhase(
                process_id=process.id,
                phase_code=phase["code"],
                name=phase["name"],
                status=status_value,
                sort_order=phase["sort_order"],
                data_json={"purpose": phase.get("purpose")},
            )
        )

    db.flush()
    alerts = _build_creation_alerts(process, creation)
    db.add_all(alerts)
    db.commit()
    db.refresh(process)

    return WorkshopProcessSummary(
        id=process.id,
        title=process.title,
        process_type=process.process_type,
        creation_mode=process.creation_mode,
        status=process.status,
        current_phase_code=process.current_phase_code,
        vehicle_id=process.vehicle_id,
        plate=process.plate_snapshot,
        priority=process.priority,
        alerts=[
            {
                "code": alert.code,
                "message": alert.message,
                "severity": alert.severity,
                "status": alert.status,
            }
            for alert in alerts
        ],
    )


@router.post("/processes/{process_id}/services", status_code=status.HTTP_201_CREATED)
def add_workshop_process_service(
    process_id: int,
    service_input: WorkshopServiceAdd,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    if process.closed_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não é possível adicionar serviços a um processo fechado.",
        )

    last_sort_order = db.scalar(
        select(WorkshopProcessService.sort_order)
        .where(WorkshopProcessService.process_id == process.id)
        .order_by(WorkshopProcessService.sort_order.desc())
        .limit(1)
    )
    service = WorkshopProcessService(
        process_id=process.id,
        service_code=service_input.service_code,
        service_label=service_label_by_code(service_input.service_code),
        detail=service_input.detail,
        zone=service_input.zone,
        short_observation=service_input.short_observation,
        sort_order=(last_sort_order or 0) + 1,
    )
    db.add(service)
    process.status = "open"
    db.commit()
    db.refresh(service)
    return {
        "id": service.id,
        "process_id": service.process_id,
        "service_code": service.service_code,
        "service_label": service.service_label,
        "detail": service.detail,
        "zone": service.zone,
        "short_observation": service.short_observation,
        "sort_order": service.sort_order,
    }


@router.post("/processes/{process_id}/documents", status_code=status.HTTP_201_CREATED)
def add_workshop_process_document(
    process_id: int,
    document_input: WorkshopProcessDocumentCreate,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    link = document_input.url_original or document_input.url_archive
    title = (document_input.title or "").strip() or _document_title(
        process,
        vehicle,
        "Documento de oficina",
    )
    document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=link,
        title=title,
        document_type=document_input.document_type,
        user_id=document_input.added_by_id,
        source_subject=document_input.notes or title,
    )
    db.commit()
    document = db.get(Document, document_id) if document_id else None
    if not document:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não foi possível associar o documento.",
        )
    return _document_response(document)


@router.post("/processes/{process_id}/reception")
def confirm_reception(
    process_id: int,
    reception: WorkshopReceptionConfirm,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "administrative_reception")
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    phase_data = phase.data_json or {}
    process.received_at = datetime.utcnow()
    if reception.km_entry is not None:
        process.initial_km = reception.km_entry
    if reception.initial_observation:
        process.initial_observation = reception.initial_observation
    process.status = "pending_review"
    next_phase_code = {
        "history_check": "history_check",
        "technical_phase": "technical_phase",
        "pending_decision": "diagnosis_decision",
    }.get(reception.next_step or "history_check", "history_check")
    process.current_phase_code = next_phase_code

    missing_required = []
    resolved_codes: set[str] = set()
    if reception.km_entry is not None:
        resolved_codes.update({"km_current_missing", "km_entry_missing"})
    if reception.km_entry is None:
        missing_required.append("KM entrada")
        _add_alert_once(
            db,
            process.id,
            "km_entry_missing",
            "KM entrada em falta",
            source="administrative_reception",
            phase_id=phase.id,
        )
    if reception.initial_observation:
        resolved_codes.update(
            {"initial_observation_missing", "reception_observation_missing"}
        )
    if not reception.initial_observation:
        missing_required.append("Observação inicial")
        _add_alert_once(
            db,
            process.id,
            "reception_observation_missing",
            "Observação inicial em falta",
            source="administrative_reception",
            phase_id=phase.id,
        )
    if reception.quadrant_photo_link:
        resolved_codes.add("quadrant_photo_missing")
    if not reception.quadrant_photo_link:
        missing_required.append("Foto do quadrante")
        _add_alert_once(
            db,
            process.id,
            "quadrant_photo_missing",
            "Foto do quadrante em falta",
            source="administrative_reception",
            phase_id=phase.id,
        )
    quadrant_photo_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=reception.quadrant_photo_link,
        title=_document_title(process, vehicle, "Foto do quadrante"),
        document_type="workshop_photo",
        user_id=reception.confirmed_by_id,
        existing_document_id=phase_data.get("quadrant_photo_document_id"),
        source_subject="Foto do quadrante",
    )
    vehicle_photo_document_ids = dict(phase_data.get("vehicle_photo_document_ids") or {})
    for key, link in (reception.vehicle_photo_links or {}).items():
        document_id = _upsert_workshop_document_from_link(
            db,
            process=process,
            vehicle=vehicle,
            link=link,
            title=_document_title(process, vehicle, f"Foto da viatura - {key}"),
            document_type="workshop_photo",
            user_id=reception.confirmed_by_id,
            existing_document_id=vehicle_photo_document_ids.get(key),
            source_subject="Foto da viatura",
        )
        if document_id:
            vehicle_photo_document_ids[key] = document_id
    reception_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=reception.document_link,
        title=_document_title(process, vehicle, "Documento de entrada"),
        document_type="workshop_evidence",
        user_id=reception.confirmed_by_id,
        existing_document_id=phase_data.get("reception_document_id"),
        source_subject="Documento de entrada",
    )
    _resolve_alerts(db, process.id, resolved_codes, reception.confirmed_by_id)

    status_value = "completed" if not missing_required else "pending_review"
    _mark_phase(
        phase,
        status_value,
        {
            "confirmed_at": process.received_at.isoformat(),
            "entry_at": reception.entry_at,
            "process_origin": reception.process_origin,
            "priority": reception.priority,
            "reception_location": reception.reception_location,
            "received_by": reception.received_by,
            "key_delivered": reception.key_delivered,
            "documents_received": reception.documents_received,
            "main_request": reception.main_request,
            "reported_symptom": reception.reported_symptom,
            "km_entry": reception.km_entry,
            "initial_observation": reception.initial_observation,
            "immobilized": reception.immobilized,
            "quadrant_photo_link": reception.quadrant_photo_link,
            "quadrant_photo_file_name": reception.quadrant_photo_file_name,
            "quadrant_photo_document_id": quadrant_photo_document_id,
            "vehicle_photo_links": reception.vehicle_photo_links or {},
            "entry_photo_file_name": reception.entry_photo_file_name,
            "vehicle_photo_document_ids": vehicle_photo_document_ids,
            "document_link": reception.document_link,
            "reception_document_id": reception_document_id,
            "visible_damage_status": reception.visible_damage_status,
            "damage_origin": reception.damage_origin,
            "damage_description": reception.damage_description,
            "damage_needs_claim_link": reception.damage_needs_claim_link,
            "requested_service": reception.requested_service,
            "planned_supplier": reception.planned_supplier,
            "initial_authorization_needed": reception.initial_authorization_needed,
            "initial_authorization_reason": reception.initial_authorization_reason,
            "estimated_value": reception.estimated_value,
            "responsible_user_id": reception.responsible_user_id,
            "next_step": reception.next_step,
            "missing_required": missing_required,
        },
        reception.confirmed_by_id,
    )
    next_phase = _get_phase_or_404(db, process.id, next_phase_code)
    if next_phase.status == "not_started":
        next_phase.status = "pending"
    db.commit()
    return {"process_id": process.id, "phase": phase.phase_code, "status": phase.status}


@router.post("/processes/{process_id}/history-check")
def confirm_history_check(
    process_id: int,
    history: WorkshopHistoryCheckConfirm,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "history_check")
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    phase_data = phase.data_json or {}

    pending_fields = []
    checks = {
        "internal_history_checked": history.internal_history_checked,
        "open_accident_reports": history.open_accident_reports,
        "previous_processes_reviewed": history.previous_processes_reviewed,
        "repeated_incidence": history.repeated_incidence,
    }
    for field_name, value in checks.items():
        if value in {"pending_review", "por_rever", "por_avaliar"}:
            pending_fields.append(field_name)

    if history.relevant_interventions_identified == "yes" and not history.history_observation:
        pending_fields.append("history_observation")
    if history.open_accident_reports == "yes" and not history.accident_reports_detail:
        pending_fields.append("accident_reports_detail")
    if history.repeated_incidence == "yes" and not history.repeated_incidence_description:
        pending_fields.append("repeated_incidence_description")
    validated_plan_report = None
    if _is_stellantis_vehicle(vehicle):
        validated_plan_report = db.scalar(
            select(WorkshopTechnicalReport).where(
                WorkshopTechnicalReport.process_id == process.id,
                WorkshopTechnicalReport.report_code == "maintenance_plan_validation",
                WorkshopTechnicalReport.status.in_(["validated", "corrected_manually"]),
            )
        )
        stellantis_checks = {
            "service_box_checked": (
                history.service_box_checked,
                history.service_box_link,
                False,
                history.service_box_reason,
                None,
                False,
                True,
            ),
            "campaigns_checked": (
                history.campaigns_checked,
                history.campaigns_link,
                False,
                history.campaigns_reason,
                history.campaigns_references,
                True,
                False,
            ),
            "maintenance_plan_checked": (
                history.maintenance_plan_checked,
                history.maintenance_plan_link,
                bool(validated_plan_report),
                history.maintenance_plan_reason,
                None,
                False,
                True,
            ),
        }
        for field_name, (
            value,
            evidence_link,
            has_validated_report,
            reason,
            references,
            require_reference,
            require_reason_when_no,
        ) in stellantis_checks.items():
            if not _verification_option_satisfied(
                value,
                evidence_link,
                has_validated_report,
                reason=reason,
                references=references,
                require_reference_when_yes=require_reference,
                require_reason_when_no=require_reason_when_no,
            ):
                pending_fields.append(field_name)

    alert_messages = {
        "service_box_checked": "Consulta Service Box por confirmar",
        "campaigns_checked": "Campanhas Stellantis por confirmar",
        "maintenance_plan_checked": "Plano de manutenção Stellantis por confirmar",
    }
    for field_name in pending_fields:
        _add_alert_once(
            db,
            process.id,
            f"{field_name}_pending",
            alert_messages.get(field_name, f"{field_name.replace('_', ' ').title()} por rever"),
            source="history_check",
            phase_id=phase.id,
        )

    service_box_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=history.service_box_link,
        title=_document_title(process, vehicle, "Consulta Service Box"),
        document_type=history.service_box_document_type or "workshop_evidence",
        user_id=history.confirmed_by_id,
        existing_document_id=phase_data.get("service_box_document_id"),
        source_subject="Consulta Service Box",
    )
    campaigns_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=history.campaigns_link,
        title=_document_title(process, vehicle, "Campanhas da marca"),
        document_type=history.campaigns_document_type or "workshop_evidence",
        user_id=history.confirmed_by_id,
        existing_document_id=phase_data.get("campaigns_document_id"),
        source_subject="Campanhas da marca",
    )
    maintenance_plan_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=history.maintenance_plan_link,
        title=_document_title(process, vehicle, "Plano de manutenção"),
        document_type=history.maintenance_plan_document_type or "workshop_report",
        user_id=history.confirmed_by_id,
        existing_document_id=phase_data.get("maintenance_plan_document_id"),
        source_subject="Plano de manutenção",
    )

    status_value = "completed" if not pending_fields else "pending_review"
    _mark_phase(
        phase,
        status_value,
        {
            "internal_history_checked": history.internal_history_checked,
            "open_accident_reports": history.open_accident_reports,
            "accident_reports_detail": history.accident_reports_detail,
            "previous_processes_reviewed": history.previous_processes_reviewed,
            "relevant_interventions_identified": history.relevant_interventions_identified,
            "relevant_interventions_summary": history.relevant_interventions_summary,
            "repeated_incidence": history.repeated_incidence,
            "repeated_incidence_description": history.repeated_incidence_description,
            "related_previous_process": history.related_previous_process,
            "history_observation": history.history_observation,
            "service_box_checked": history.service_box_checked,
            "service_box_link": history.service_box_link,
            "service_box_reason": history.service_box_reason,
            "service_box_last_checked_at": history.service_box_last_checked_at,
            "service_box_validity_days": history.service_box_validity_days,
            "service_box_needed": history.service_box_needed,
            "service_box_observation": history.service_box_observation,
            "service_box_document_id": service_box_document_id,
            "campaigns_checked": history.campaigns_checked,
            "campaigns_link": history.campaigns_link,
            "campaigns_references": history.campaigns_references,
            "campaigns_reason": history.campaigns_reason,
            "campaigns_active": history.campaigns_active,
            "campaign_number": history.campaign_number,
            "campaign_description": history.campaign_description,
            "campaigns_document_id": campaigns_document_id,
            "maintenance_plan_checked": (
                "evidence_link" if validated_plan_report else history.maintenance_plan_checked
            ),
            "maintenance_plan_link": history.maintenance_plan_link,
            "maintenance_plan_reason": history.maintenance_plan_reason,
            "maintenance_plan_attached": history.maintenance_plan_attached,
            "maintenance_plan_confirmed": history.maintenance_plan_confirmed,
            "interval_km": history.interval_km,
            "interval_months": history.interval_months,
            "rentway_next_service_date": history.rentway_next_service_date,
            "rentway_next_service_km": history.rentway_next_service_km,
            "calculated_next_service_date": history.calculated_next_service_date,
            "calculated_next_service_km": history.calculated_next_service_km,
            "rentway_vs_calculation": history.rentway_vs_calculation,
            "maintenance_plan_observation": history.maintenance_plan_observation,
            "maintenance_plan_document_id": maintenance_plan_document_id,
            "maintenance_plan_report_id": validated_plan_report.id
            if validated_plan_report
            else None,
            "service_to_validate": history.service_to_validate,
            "last_service_date": history.last_service_date,
            "last_service_km": history.last_service_km,
            "last_service_supplier": history.last_service_supplier,
            "last_service_document": history.last_service_document,
            "last_service_source": history.last_service_source,
            "suspicious_repetition": history.suspicious_repetition,
            "service_history_observation": history.service_history_observation,
            "pending_damage_update": history.pending_damage_update,
            "pending_claims": history.pending_claims,
            "technical_audit_status": history.technical_audit_status,
            "open_identified_problems": history.open_identified_problems,
            "pending_tasks": history.pending_tasks,
            "sale_blocked": history.sale_blocked,
            "diagnosis_focus": history.diagnosis_focus,
            "required_reports": history.required_reports,
            "diagnosis_questions": history.diagnosis_questions,
            "technical_priority": history.technical_priority,
            "operational_validation_status": history.operational_validation_status,
            "reserve_reason": history.reserve_reason,
            "requires_stellantis_checks": _is_stellantis_vehicle(vehicle),
            "pending_fields": pending_fields,
        },
        history.confirmed_by_id,
    )
    process.current_phase_code = "technical_phase"
    next_phase = _get_phase_or_404(db, process.id, "technical_phase")
    if next_phase.status == "not_started":
        next_phase.status = "pending"
    db.commit()
    return {"process_id": process.id, "phase": phase.phase_code, "status": phase.status}


@router.post("/processes/{process_id}/technical-reports", status_code=status.HTTP_201_CREATED)
def add_technical_report(
    process_id: int,
    report_input: WorkshopTechnicalReportCreate,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    if not report_input.allow_blank and not _has_report_payload(
        report_input.original_link,
        report_input.raw_values,
        report_input.extracted_values,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não é possível criar relatório em branco sem confirmação.",
        )
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    phase_code = (
        "internal_repair_execution"
        if report_input.report_moment == "final"
        else "technical_phase"
    )
    phase = _get_phase_or_404(db, process.id, phase_code)
    report_status = "pending_validation" if report_input.extracted_values else "added"
    original_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=report_input.original_link,
        title=_document_title(process, vehicle, REPORT_LABELS[report_input.report_code]),
        document_type=report_input.document_type or "workshop_report",
        user_id=report_input.added_by_id,
        source_subject=REPORT_LABELS[report_input.report_code],
    )
    report = WorkshopTechnicalReport(
        process_id=process.id,
        phase_id=phase.id,
        report_code=report_input.report_code,
        report_name=REPORT_LABELS[report_input.report_code],
        reading_origin=report_input.reading_origin,
        reading_origin_detail=report_input.reading_origin_detail,
        report_moment=report_input.report_moment,
        status=report_status,
        original_document_id=original_document_id,
        original_link=report_input.original_link,
        raw_values_json=report_input.raw_values,
        extracted_values_json=report_input.extracted_values,
        added_by_id=report_input.added_by_id,
        observations=report_input.observations,
    )
    db.add(report)
    phase.status = "pending_validation"
    if report_input.report_moment == "final":
        process.current_phase_code = "internal_repair_execution"
    else:
        process.current_phase_code = "technical_phase"
    db.commit()
    db.refresh(report)
    return _technical_report_response(report)


@router.post("/processes/{process_id}/technical-reports/extract")
def extract_technical_report_values(
    process_id: int,
    report_input: WorkshopTechnicalReportExtract,
    db: DbSession,
) -> dict[str, Any]:
    _get_process_or_404(db, process_id)
    try:
        values = extract_workshop_report_values(
            _authorized_report_source(report_input.original_link),
            report_input.report_code,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {
        "report_code": report_input.report_code,
        "original_link": report_input.original_link,
        "extracted_values": values,
        "status": "pending_validation",
    }


@router.post("/processes/{process_id}/technical-reports/extract-upload")
async def extract_uploaded_technical_report_values(
    process_id: int,
    report_code: str,
    db: DbSession,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    _get_process_or_404(db, process_id)
    if report_code not in REPORT_CODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Relatório técnico inválido.",
        )
    if not str(file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A extração automática só aceita ficheiros PDF.",
        )
    content = await file.read(MAX_TECHNICAL_REPORT_UPLOAD_BYTES + 1)
    if len(content) > MAX_TECHNICAL_REPORT_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="O relatório excede o limite de 25 MB.",
        )
    try:
        values = extract_workshop_report_values_from_bytes(
            content,
            report_code,
            file.filename,
        )
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return {
        "report_code": report_code,
        "original_link": None,
        "file_name": file.filename,
        "extracted_values": values,
        "status": "pending_validation",
    }


@router.post("/technical-reports/{report_id}/validate")
def validate_technical_report(
    report_id: int,
    validation: WorkshopTechnicalReportValidate,
    db: DbSession,
) -> dict[str, Any]:
    report = db.get(WorkshopTechnicalReport, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório técnico não encontrado.",
        )
    correction_payload = {
        **(validation.correction or {}),
        "validation_decision": validation.validation_decision,
        "decided_at": datetime.utcnow().isoformat(),
        "decided_by_id": validation.validated_by_id,
    }
    report.validated_values_json = validation.validated_values
    report.correction_json = correction_payload
    report.validated_by_id = validation.validated_by_id
    report.validated_at = None if validation.validation_decision == "keep_pending" else datetime.utcnow()
    report.observations = validation.observations or report.observations
    if validation.validation_decision == "keep_pending":
        report.status = "pending_validation"
    elif validation.validation_decision == "reject_reading":
        report.status = "unable_to_read"
    elif validation.validation_decision == "correct_and_validate":
        report.status = "corrected_manually"
    else:
        report.status = "validated"
    if report.report_code == "maintenance_plan_validation" and report.status in {"validated", "corrected_manually"}:
        history_phase = db.scalar(
            select(WorkshopProcessPhase).where(
                WorkshopProcessPhase.process_id == report.process_id,
                WorkshopProcessPhase.phase_code == "history_check",
            )
        )
        if history_phase:
            history_phase.data_json = {
                **(history_phase.data_json or {}),
                "maintenance_plan_checked": "yes",
                "maintenance_plan_report_id": report.id,
            }
        _resolve_alerts(
            db,
            report.process_id,
            {"maintenance_plan_checked_pending"},
            validation.validated_by_id,
        )
        if not _truthy_validation(
            _report_value(validation.validated_values, "request_matches_servicebox_plan")
        ):
            _add_alert_once(
                db,
                report.process_id,
                "maintenance_request_plan_mismatch",
                "Solicitação não bate certo com o plano Service Box",
                severity="high",
                source="technical_report",
                phase_id=report.phase_id,
                detail={"report_id": report.id},
            )
        if not _truthy_validation(
            _report_value(validation.validated_values, "rentway_matches_servicebox_plan")
        ):
            _add_alert_once(
                db,
                report.process_id,
                "rentway_maintenance_plan_mismatch",
                "Parametrização Rentway não bate certo com o plano Service Box",
                severity="high",
                source="technical_report",
                phase_id=report.phase_id,
                detail={"report_id": report.id},
            )
    db.commit()
    db.refresh(report)
    return _technical_report_response(report)


@router.patch("/technical-reports/{report_id}")
def update_technical_report(
    report_id: int,
    report_input: WorkshopTechnicalReportUpdate,
    db: DbSession,
) -> dict[str, Any]:
    report = db.get(WorkshopTechnicalReport, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório técnico não encontrado.",
        )
    process = _get_process_or_404(db, report.process_id)
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    if report_input.report_code is not None:
        report.report_code = report_input.report_code
        report.report_name = REPORT_LABELS[report_input.report_code]
    if report_input.reading_origin is not None:
        report.reading_origin = report_input.reading_origin
    if report_input.reading_origin_detail is not None:
        report.reading_origin_detail = report_input.reading_origin_detail
    if report_input.report_moment is not None:
        report.report_moment = report_input.report_moment
    if report_input.original_link is not None:
        report.original_link = report_input.original_link
    if report_input.original_link is not None or report_input.document_type is not None:
        report.original_document_id = _upsert_workshop_document_from_link(
            db,
            process=process,
            vehicle=vehicle,
            link=report.original_link,
            title=_document_title(process, vehicle, report.report_name),
            document_type=report_input.document_type or "workshop_report",
            user_id=report.added_by_id,
            existing_document_id=report.original_document_id,
            source_subject=report.report_name,
        )
    if report_input.raw_values is not None:
        report.raw_values_json = report_input.raw_values
    if report_input.extracted_values is not None:
        report.extracted_values_json = report_input.extracted_values
        if report.status in {"added", "pending", "pending_validation"}:
            report.status = "pending_validation"
    if report_input.observations is not None:
        report.observations = report_input.observations
    if not report_input.allow_blank and not _has_report_payload(
        report.original_link,
        report.raw_values_json,
        report.extracted_values_json,
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Não é possível deixar relatório em branco sem confirmação.",
        )
    db.commit()
    db.refresh(report)
    return _technical_report_response(report)


@router.delete("/technical-reports/{report_id}")
def void_technical_report(report_id: int, db: DbSession) -> dict[str, Any]:
    report = db.get(WorkshopTechnicalReport, report_id)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Relatório técnico não encontrado.",
        )
    if report.status == "voided":
        return _technical_report_response(report)
    report.status = "voided"
    report.observations = "\n".join(
        item
        for item in [
            report.observations,
            f"Relatório anulado em {datetime.utcnow().isoformat()}.",
        ]
        if item
    )
    db.commit()
    db.refresh(report)
    return _technical_report_response(report)


@router.post("/processes/{process_id}/technical-checks")
def upsert_technical_check(
    process_id: int,
    check_input: WorkshopTechnicalCheckUpsert,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    phase = _ensure_phase(db, process, "technical_inspection")
    check = db.scalar(
        select(WorkshopTechnicalCheck).where(
            WorkshopTechnicalCheck.process_id == process.id,
            WorkshopTechnicalCheck.check_code == check_input.check_code,
        )
    )
    if not check:
        check = WorkshopTechnicalCheck(
            process_id=process.id,
            phase_id=phase.id,
            check_code=check_input.check_code,
            label=CHECK_LABELS[check_input.check_code],
        )
        db.add(check)

    task_id = check.task_id
    if check_input.creates_task and not task_id:
        task = Task(
            title=check_input.task_title or f"Validar {CHECK_LABELS[check_input.check_code]}",
            description=check_input.observation,
            category="workshop",
            status="new",
            priority=check_input.task_priority,
            entity_type="workshop_process",
            entity_id=str(process.id),
            assigned_to_id=check_input.task_responsible_user_id,
        )
        apply_source_work_default(
            db,
            task,
            source_type="workshop",
            source_key="technical_check",
        )
        db.add(task)
        db.flush()
        task_id = task.id

    check.status = check_input.status
    check.observation = check_input.observation
    check.evidence_link = check_input.evidence_link
    check.evidence_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=check_input.evidence_link,
        title=_document_title(process, vehicle, f"Evidência - {CHECK_LABELS[check_input.check_code]}"),
        document_type=check_input.evidence_document_type or "workshop_evidence",
        user_id=None,
        existing_document_id=check.evidence_document_id,
        source_subject=CHECK_LABELS[check_input.check_code],
    )
    check.creates_task = check_input.creates_task
    check.potential_customer_charge = check_input.potential_customer_charge
    check.task_id = task_id
    check.detail_json = check_input.detail

    if check_input.status == "not_ok":
        _add_alert_once(
            db,
            process.id,
            f"technical_check_{check_input.check_code}_not_ok",
            f"{CHECK_LABELS[check_input.check_code]} com incidência",
            source="technical_check",
            phase_id=phase.id,
            detail={"check_code": check_input.check_code},
        )
    if check_input.potential_customer_charge and not check_input.evidence_link:
        _add_alert_once(
            db,
            process.id,
            f"{check_input.check_code}_charge_evidence_missing",
            "Evidência de cobrança em falta",
            source="technical_check",
            phase_id=phase.id,
            detail={"check_code": check_input.check_code},
        )

    phase.status = "with_incidents" if check_input.status == "not_ok" else "in_progress"
    process.current_phase_code = "technical_inspection"
    db.commit()
    db.refresh(check)
    return {"id": check.id, "status": check.status, "task_id": check.task_id}


@router.post("/processes/{process_id}/incidents", status_code=status.HTTP_201_CREATED)
def create_technical_incident(
    process_id: int,
    incident_input: WorkshopTechnicalIncidentCreate,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _ensure_phase(db, process, "technical_inspection")
    incident = WorkshopTechnicalIncident(
        process_id=process.id,
        phase_id=phase.id,
        report_id=incident_input.report_id,
        check_id=incident_input.check_id,
        related_field=incident_input.related_field,
        incident_type=incident_input.incident_type,
        description=incident_input.description,
        severity=incident_input.severity,
        recommended_action=incident_input.recommended_action,
        vehicle_can_circulate=incident_input.vehicle_can_circulate,
        evidence_link=incident_input.evidence_link,
        created_by_id=incident_input.created_by_id,
    )
    db.add(incident)
    _add_alert_once(
        db,
        process.id,
        f"technical_incident_{incident_input.incident_type}",
        incident_input.description[:240],
        severity=incident_input.severity,
        source="technical_incident",
        phase_id=phase.id,
    )
    phase.status = "with_incidents"
    process.current_phase_code = "technical_inspection"
    db.commit()
    db.refresh(incident)
    return {"id": incident.id, "status": incident.status}


@router.post("/processes/{process_id}/diagnosis-decision")
def confirm_diagnosis_decision(
    process_id: int,
    decision: WorkshopDiagnosisDecisionConfirm,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "diagnosis_decision")

    task_id = None
    if decision.create_task:
        task = Task(
            title=f"Oficina: {decision.next_action}",
            description=decision.decision_observation or decision.main_diagnosis,
            category="workshop",
            status="new",
            priority="high" if decision.severity in {"high", "critical"} else "normal",
            entity_type="workshop_process",
            entity_id=str(process.id),
            assigned_to_id=decision.next_action_responsible_user_id,
            due_on=decision.next_action_due_at.date() if decision.next_action_due_at else None,
            created_by_id=decision.decided_by_id,
        )
        apply_source_work_default(
            db,
            task,
            source_type="workshop",
            source_key="diagnosis_decision",
        )
        db.add(task)
        db.flush()
        task_id = task.id

    if decision.vehicle_can_circulate in {"no", "Não", "nao"}:
        _add_alert_once(
            db,
            process.id,
            "vehicle_cannot_circulate",
            "Viatura não pode circular",
            severity="critical",
            source="diagnosis_decision",
            phase_id=phase.id,
        )
    if decision.potential_customer_charge and not decision.charge_evidence_link:
        _add_alert_once(
            db,
            process.id,
            "charge_evidence_missing",
            "Evidência de cobrança em falta",
            source="diagnosis_decision",
            phase_id=phase.id,
        )
    if decision.needs_budget:
        _add_alert_once(
            db,
            process.id,
            "budget_phase_pending",
            "Orçamento / Aprovação pendente para reparação externa",
            severity="info",
            source="diagnosis_decision",
            phase_id=phase.id,
        )

    _mark_phase(
        phase,
        "completed",
        {
            "main_diagnosis": decision.main_diagnosis,
            "intervention_type": decision.intervention_type,
            "affected_system": decision.affected_system,
            "severity": decision.severity,
            "probable_cause": decision.probable_cause,
            "diagnosis_observation": decision.diagnosis_observation,
            "vehicle_can_circulate": decision.vehicle_can_circulate,
            "needs_repair": decision.needs_repair,
            "needs_budget": decision.needs_budget,
            "needs_approval": decision.needs_approval,
            "potential_customer_charge": decision.potential_customer_charge,
            "warranty": decision.warranty,
            "charge_reason": decision.charge_reason,
            "customer_contract": decision.customer_contract,
            "estimated_charge_value": decision.estimated_charge_value,
            "charge_evidence_link": decision.charge_evidence_link,
            "warranty_reason": decision.warranty_reason,
            "warranty_evidence_link": decision.warranty_evidence_link,
            "next_action": decision.next_action,
            "next_action_responsible_user_id": decision.next_action_responsible_user_id,
            "next_action_due_at": (
                decision.next_action_due_at.isoformat() if decision.next_action_due_at else None
            ),
            "decision_observation": decision.decision_observation,
            "task_id": task_id,
        },
        decision.decided_by_id,
    )
    process.current_phase_code = (
        "budget_approval" if decision.needs_budget else "internal_repair_execution"
    )
    next_phase = _get_phase_or_404(db, process.id, process.current_phase_code)
    if next_phase.status in {"not_started", "pending_definition"}:
        next_phase.status = "pending"
    db.commit()
    return {
        "process_id": process.id,
        "phase": phase.phase_code,
        "status": phase.status,
        "task_id": task_id,
        "next_phase": process.current_phase_code,
    }


@router.post("/processes/{process_id}/budget-approval")
def update_budget_approval(
    process_id: int,
    budget: WorkshopBudgetApprovalUpdate,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "budget_approval")
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    phase_data = phase.data_json or {}

    missing = []
    if not budget.supplier:
        missing.append("Fornecedor / oficina")
    if not budget.request_description:
        missing.append("Descrição do pedido")
    if budget.budget_received and budget.estimated_value is None:
        missing.append("Valor estimado")
    if budget.budget_received and not budget.budget_link:
        _add_alert_once(
            db,
            process.id,
            "budget_link_missing",
            "Orçamento sem link/anexo",
            source="budget_approval",
            phase_id=phase.id,
        )
    if budget.needs_approval and budget.approval_status == "pending":
        _add_alert_once(
            db,
            process.id,
            "approval_pending",
            "Aprovação pendente",
            severity="info",
            source="budget_approval",
            phase_id=phase.id,
        )
    if not budget.budget_received:
        _add_alert_once(
            db,
            process.id,
            "budget_pending",
            "A aguardar orçamento",
            severity="info",
            source="budget_approval",
            phase_id=phase.id,
        )

    completed = (
        budget.budget_received
        and (not budget.needs_approval or budget.approval_status in {"approved", "rejected"})
        and bool(budget.final_result)
    )
    budget_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=budget.budget_link,
        title=_document_title(process, vehicle, "Orçamento"),
        document_type="workshop_quote",
        user_id=budget.requested_by_id,
        existing_document_id=phase_data.get("budget_document_id"),
        source_subject="Orçamento de oficina",
    )
    status_value = "completed" if completed and not missing else "pending_review"
    _mark_phase(
        phase,
        status_value,
        {
            "supplier": budget.supplier,
            "requested_by_id": budget.requested_by_id,
            "request_description": budget.request_description,
            "services_included": budget.services_included or [],
            "supplier_deadline_at": (
                budget.supplier_deadline_at.isoformat() if budget.supplier_deadline_at else None
            ),
            "budget_received": budget.budget_received,
            "estimated_value": budget.estimated_value,
            "vat_included": budget.vat_included,
            "budget_description": budget.budget_description,
            "budget_link": budget.budget_link,
            "budget_document_id": budget_document_id,
            "budget_valid_until": (
                budget.budget_valid_until.isoformat() if budget.budget_valid_until else None
            ),
            "needs_approval": budget.needs_approval,
            "approver_user_id": budget.approver_user_id,
            "approval_status": budget.approval_status,
            "approved_value": budget.approved_value,
            "rejection_reason": budget.rejection_reason,
            "final_result": budget.final_result,
            "next_action": budget.next_action,
            "observation": budget.observation,
            "missing_required": missing,
        },
        budget.confirmed_by_id,
    )
    if budget.approval_status == "approved":
        process.current_phase_code = "internal_repair_execution"
        next_phase = _get_phase_or_404(db, process.id, "internal_repair_execution")
        if next_phase.status == "not_started":
            next_phase.status = "pending"
    elif budget.approval_status == "rejected":
        process.current_phase_code = "diagnosis_decision"
    else:
        process.current_phase_code = "budget_approval"
    db.commit()
    return {
        "process_id": process.id,
        "phase": phase.phase_code,
        "status": phase.status,
        "next_phase": process.current_phase_code,
    }


@router.post("/processes/{process_id}/internal-repair")
def update_internal_repair(
    process_id: int,
    repair: WorkshopRepairExecutionUpdate,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "internal_repair_execution")
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    phase_data = phase.data_json or {}
    missing = []
    if not repair.intervention_description:
        missing.append("Descrição da intervenção")
    if not repair.result:
        missing.append("Resultado da intervenção")
    needs_final_photo = (
        repair.result
        and repair.result != "no_intervention_needed"
        and not repair.final_quadrant_photo_link
    )
    if needs_final_photo:
        missing.append("Foto final do quadrante")
        _add_alert_once(
            db,
            process.id,
            "final_quadrant_photo_missing",
            "Foto final do quadrante em falta",
            source="internal_repair_execution",
            phase_id=phase.id,
        )

    final_quadrant_photo_document_id = _upsert_workshop_document_from_link(
        db,
        process=process,
        vehicle=vehicle,
        link=repair.final_quadrant_photo_link,
        title=_document_title(process, vehicle, "Foto final do quadrante"),
        document_type="workshop_photo",
        user_id=repair.confirmed_by_id,
        existing_document_id=phase_data.get("final_quadrant_photo_document_id"),
        source_subject="Foto final do quadrante",
    )
    final_evidence_document_ids = dict(phase_data.get("final_evidence_document_ids") or {})
    for key, link in (repair.final_evidence_links or {}).items():
        document_id = _upsert_workshop_document_from_link(
            db,
            process=process,
            vehicle=vehicle,
            link=link,
            title=_document_title(process, vehicle, f"Evidência final - {key}"),
            document_type="workshop_evidence",
            user_id=repair.confirmed_by_id,
            existing_document_id=final_evidence_document_ids.get(key),
            source_subject="Evidência final de reparação",
        )
        if document_id:
            final_evidence_document_ids[key] = document_id

    _mark_phase(
        phase,
        "completed" if not missing else "pending_review",
        {
            "execution_type": repair.execution_type,
            "mechanic_user_id": repair.mechanic_user_id,
            "intervention_description": repair.intervention_description,
            "parts_used": repair.parts_used or [],
            "result": repair.result,
            "final_quadrant_photo_link": repair.final_quadrant_photo_link,
            "final_quadrant_photo_document_id": final_quadrant_photo_document_id,
            "final_km_visible": repair.final_km_visible,
            "final_evidence_links": repair.final_evidence_links or {},
            "final_evidence_document_ids": final_evidence_document_ids,
            "final_observation": repair.final_observation,
            "missing_required": missing,
        },
        repair.confirmed_by_id,
    )
    process.current_phase_code = "final_closure"
    next_phase = _get_phase_or_404(db, process.id, "final_closure")
    if next_phase.status == "not_started":
        next_phase.status = "pending"
    db.commit()
    return {"process_id": process.id, "phase": phase.phase_code, "status": phase.status}


@router.post("/processes/{process_id}/close")
def close_workshop_process(
    process_id: int,
    closure: WorkshopClosureConfirm,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "final_closure")

    open_critical_alerts = db.scalars(
        select(WorkshopProcessAlert).where(
            WorkshopProcessAlert.process_id == process.id,
            WorkshopProcessAlert.status == "open",
            WorkshopProcessAlert.severity.in_(["critical", "high"]),
        )
    ).all()
    if open_critical_alerts and not closure.close_with_pending_items:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Existem alertas críticos abertos. Feche com pendências ou resolva os alertas.",
        )
    if closure.close_with_pending_items and not closure.pending_justification:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Justificação é obrigatória para fechar com pendências.",
        )

    if closure.close_with_pending_items:
        db.add(
            WorkshopClosureCheck(
                process_id=process.id,
                check_code="pending_items",
                label="Fecho com pendências",
                status="pending",
                justification=closure.pending_justification,
                responsible_user_id=closure.pending_responsible_user_id,
                due_at=closure.pending_due_at,
            )
        )

    process.status = (
        "completed_with_pending_items" if closure.close_with_pending_items else "completed"
    )
    process.current_phase_code = "final_closure"
    process.closed_at = datetime.utcnow()
    _mark_phase(
        phase,
        process.status,
        {
            "final_result": closure.final_result,
            "vehicle_ready": closure.vehicle_ready,
            "final_test_done": closure.final_test_done,
            "can_return_to_fleet": closure.can_return_to_fleet,
            "final_km": closure.final_km,
            "new_vehicle_operational_status": closure.new_vehicle_operational_status,
            "final_observation": closure.final_observation,
            "closed_at": process.closed_at.isoformat(),
            "close_with_pending_items": closure.close_with_pending_items,
        },
        closure.closed_by_id,
    )

    if process.vehicle_id:
        vehicle = db.get(Vehicle, process.vehicle_id)
        if vehicle:
            vehicle.operational_status = closure.new_vehicle_operational_status

    db.commit()
    return {"process_id": process.id, "status": process.status, "closed_at": process.closed_at}


@router.get("/processes")
def list_workshop_processes(db: DbSession) -> list[dict[str, Any]]:
    processes = db.scalars(
        select(WorkshopProcess).order_by(WorkshopProcess.created_at.desc())
    ).all()
    rows = []
    for process in processes:
        vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
        services = db.scalars(
            select(WorkshopProcessService)
            .where(WorkshopProcessService.process_id == process.id)
            .order_by(WorkshopProcessService.sort_order)
        ).all()
        phases = db.scalars(
            select(WorkshopProcessPhase)
            .where(WorkshopProcessPhase.process_id == process.id)
            .order_by(WorkshopProcessPhase.sort_order)
        ).all()
        open_alerts = db.scalars(
            select(WorkshopProcessAlert).where(
                WorkshopProcessAlert.process_id == process.id,
                WorkshopProcessAlert.status == "open",
            )
        ).all()
        rows.append(
            {
                "id": process.id,
                "title": process.title,
                "process_type": process.process_type,
                "creation_mode": process.creation_mode,
                "status": process.status,
                "current_phase_code": process.current_phase_code,
                "vehicle_id": process.vehicle_id,
                "plate": process.plate_snapshot,
                "priority": process.priority,
                "origin": process.origin,
                "created_at": process.created_at,
                "updated_at": process.updated_at,
                "closed_at": process.closed_at,
                "vehicle": _vehicle_summary(vehicle, process.plate_snapshot, db),
                "document_folder": {
                    "path": (process.metadata_json or {}).get(
                        "document_folder_path", WORKSHOP_DOCUMENTS_BASE_PATH
                    ),
                    "scope": (process.metadata_json or {}).get(
                        "document_folder_scope", "workshop_shared"
                    ),
                    "status": (process.metadata_json or {}).get(
                        "document_folder_status", "defined"
                    ),
                },
                "services_label": " + ".join(
                    service.service_label for service in services if service.service_label
                ),
                "phases": [
                    {
                        "phase_code": phase.phase_code,
                        "name": phase.name,
                        "status": phase.status,
                        "sort_order": phase.sort_order,
                    }
                    for phase in phases
                ],
                "open_alerts_count": len(open_alerts),
            }
        )
    return rows


@router.get("/processes/{process_id}")
def get_workshop_process(process_id: int, db: DbSession) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    existing_phase_codes = set(
        db.scalars(
            select(WorkshopProcessPhase.phase_code).where(
                WorkshopProcessPhase.process_id == process.id
            )
        ).all()
    )
    expected_phase_codes = {phase["code"] for phase in WORKSHOP_PHASE_TEMPLATE}
    if not expected_phase_codes.issubset(existing_phase_codes):
        _ensure_expected_phases(db, process)
        db.commit()

    services = db.scalars(
        select(WorkshopProcessService)
        .where(WorkshopProcessService.process_id == process.id)
        .order_by(WorkshopProcessService.sort_order)
    ).all()
    phases = db.scalars(
        select(WorkshopProcessPhase)
        .where(WorkshopProcessPhase.process_id == process.id)
        .order_by(WorkshopProcessPhase.sort_order)
    ).all()
    alerts = db.scalars(
        select(WorkshopProcessAlert)
        .where(WorkshopProcessAlert.process_id == process.id)
        .where(WorkshopProcessAlert.status == "open")
        .order_by(WorkshopProcessAlert.created_at)
    ).all()
    reports = db.scalars(
        select(WorkshopTechnicalReport)
        .where(WorkshopTechnicalReport.process_id == process.id)
        .where(WorkshopTechnicalReport.status != "voided")
        .order_by(WorkshopTechnicalReport.created_at)
    ).all()
    linked_document_ids = db.scalars(
        select(DocumentLink.document_id).where(
            DocumentLink.entity_type == "workshop_phased_process",
            DocumentLink.entity_id == str(process.id),
        )
    ).all()
    documents = db.scalars(
        select(Document)
        .where(Document.id.in_(linked_document_ids))
        .order_by(Document.id.desc())
    ).all() if linked_document_ids else []
    checks = db.scalars(
        select(WorkshopTechnicalCheck)
        .where(WorkshopTechnicalCheck.process_id == process.id)
        .order_by(WorkshopTechnicalCheck.created_at)
    ).all()
    incidents = db.scalars(
        select(WorkshopTechnicalIncident)
        .where(WorkshopTechnicalIncident.process_id == process.id)
        .order_by(WorkshopTechnicalIncident.created_at)
    ).all()
    closure_checks = db.scalars(
        select(WorkshopClosureCheck)
        .where(WorkshopClosureCheck.process_id == process.id)
        .order_by(WorkshopClosureCheck.created_at)
    ).all()
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None

    return {
        "id": process.id,
        "title": process.title,
        "process_type": process.process_type,
        "creation_mode": process.creation_mode,
        "status": process.status,
        "current_phase_code": process.current_phase_code,
        "vehicle_id": process.vehicle_id,
        "plate": process.plate_snapshot,
        "priority": process.priority,
        "origin": process.origin,
        "origin_detail": process.origin_detail,
        "initial_km": process.initial_km,
        "initial_observation": process.initial_observation,
        "scheduled_at": process.scheduled_at,
        "created_at": process.created_at,
        "closed_at": process.closed_at,
        "vehicle": _vehicle_summary(vehicle, process.plate_snapshot, db),
        "document_folder": {
            "path": (process.metadata_json or {}).get(
                "document_folder_path", WORKSHOP_DOCUMENTS_BASE_PATH
            ),
            "scope": (process.metadata_json or {}).get(
                "document_folder_scope", "workshop_shared"
            ),
            "status": (process.metadata_json or {}).get(
                "document_folder_status", "defined"
            ),
        },
        "documents": [
            {
                "id": document.id,
                "title": document.title,
                "document_type": document.document_type,
                "classification": document.classification,
                "status": document.status,
                "vehicle_id": document.vehicle_id,
                "workshop_process_id": None,
                "plate": document.plate,
                "storage_path": document.storage_path,
                "external_url": document.external_url,
                "folder_path": document.folder_path,
            }
            for document in documents
        ],
        "services_label": " + ".join(
            service.service_label for service in services if service.service_label
        ),
        "services": [
            {
                "id": service.id,
                "service_code": service.service_code,
                "service_label": service.service_label,
                "detail": service.detail,
                "zone": service.zone,
                "short_observation": service.short_observation,
                "sort_order": service.sort_order,
            }
            for service in services
        ],
        "phases": [
            {
                "id": phase.id,
                "phase_code": phase.phase_code,
                "name": phase.name,
                "status": phase.status,
                "sort_order": phase.sort_order,
                "data": phase.data_json,
            }
            for phase in phases
        ],
        "alerts": [
            {
                "code": alert.code,
                "message": alert.message,
                "severity": alert.severity,
                "status": alert.status,
                "source": alert.source,
                "phase_id": alert.phase_id,
            }
            for alert in alerts
        ],
        "technical_reports": [
            {
                "id": report.id,
                "report_code": report.report_code,
                "report_name": report.report_name,
                "reading_origin": report.reading_origin,
                "report_moment": report.report_moment,
                "status": report.status,
                "original_document_id": report.original_document_id,
                "original_link": report.original_link,
                "extracted_values": report.extracted_values_json,
                "validated_values": report.validated_values_json,
                "validated_at": report.validated_at,
            }
            for report in reports
        ],
        "technical_checks": [
            {
                "id": check.id,
                "check_code": check.check_code,
                "label": check.label,
                "status": check.status,
                "creates_task": check.creates_task,
                "potential_customer_charge": check.potential_customer_charge,
                "evidence_document_id": check.evidence_document_id,
                "evidence_link": check.evidence_link,
                "task_id": check.task_id,
                "incident_id": check.incident_id,
            }
            for check in checks
        ],
        "technical_incidents": [
            {
                "id": incident.id,
                "incident_type": incident.incident_type,
                "description": incident.description,
                "severity": incident.severity,
                "recommended_action": incident.recommended_action,
                "vehicle_can_circulate": incident.vehicle_can_circulate,
                "status": incident.status,
            }
            for incident in incidents
        ],
        "closure_checks": [
            {
                "id": check.id,
                "check_code": check.check_code,
                "label": check.label,
                "status": check.status,
                "justification": check.justification,
                "responsible_user_id": check.responsible_user_id,
                "due_at": check.due_at,
            }
            for check in closure_checks
        ],
    }
