from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.tasks import Task
from app.models.vehicles import Vehicle
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

router = APIRouter(prefix="/workshop", tags=["workshop"])
DbSession = Annotated[Session, Depends(get_db)]

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


def _vehicle_summary(vehicle: Vehicle | None, fallback_plate: str | None = None) -> dict[str, Any]:
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
        }
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
    }


def _is_stellantis_vehicle(vehicle: Vehicle | None) -> bool:
    if not vehicle or not vehicle.brand:
        return False
    return vehicle.brand.strip().lower() in STELLANTIS_BRANDS


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
    initial_observation: str | None = None
    quadrant_photo_link: str | None = None
    vehicle_photo_links: dict[str, str] | None = None
    visible_damage_status: str | None = None
    damage_description: str | None = None
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
    campaigns_checked: str | None = None
    campaigns_link: str | None = None
    maintenance_plan_checked: str | None = None
    maintenance_plan_link: str | None = None
    confirmed_by_id: int | None = None


class WorkshopTechnicalReportCreate(BaseModel):
    report_code: str
    reading_origin: str = "stellantis_machine"
    reading_origin_detail: str | None = None
    report_moment: str = "initial"
    original_link: str | None = None
    raw_values: dict[str, Any] | list[Any] | None = None
    extracted_values: dict[str, Any] | list[Any] | None = None
    added_by_id: int | None = None
    observations: str | None = None

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
        return self


class WorkshopTechnicalReportValidate(BaseModel):
    validated_values: dict[str, Any] | list[Any]
    correction: dict[str, Any] | None = None
    validated_by_id: int | None = None
    observations: str | None = None


class WorkshopTechnicalReportUpdate(BaseModel):
    report_code: str | None = None
    reading_origin: str | None = None
    reading_origin_detail: str | None = None
    report_moment: str | None = None
    original_link: str | None = None
    raw_values: dict[str, Any] | list[Any] | None = None
    extracted_values: dict[str, Any] | list[Any] | None = None
    observations: str | None = None

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
        return self


class WorkshopTechnicalCheckUpsert(BaseModel):
    check_code: str
    status: str
    observation: str | None = None
    evidence_link: str | None = None
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
) -> bool:
    normalized = str(value or "").strip().lower()
    if has_validated_report:
        return True
    if normalized in {"no", "not_applicable", "yes"}:
        return True
    if normalized == "evidence_link":
        return bool(evidence_link)
    return False


def _mark_phase(
    phase: WorkshopProcessPhase,
    status_value: str,
    data: dict[str, Any] | None = None,
    completed_by_id: int | None = None,
) -> None:
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
        metadata_json={"title_source": "manual" if "other" in service_codes else "automatic"},
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
        if phase["code"] == "process_creation":
            status_value = "completed"
        elif phase["code"] == current_phase:
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


@router.post("/processes/{process_id}/reception")
def confirm_reception(
    process_id: int,
    reception: WorkshopReceptionConfirm,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "administrative_reception")
    process.received_at = datetime.utcnow()
    if reception.km_entry is not None:
        process.initial_km = reception.km_entry
    if reception.initial_observation:
        process.initial_observation = reception.initial_observation
    process.status = "pending_review"
    process.current_phase_code = "history_check"

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
    _resolve_alerts(db, process.id, resolved_codes, reception.confirmed_by_id)

    status_value = "completed" if not missing_required else "pending_review"
    _mark_phase(
        phase,
        status_value,
        {
            "confirmed_at": process.received_at.isoformat(),
            "km_entry": reception.km_entry,
            "initial_observation": reception.initial_observation,
            "quadrant_photo_link": reception.quadrant_photo_link,
            "vehicle_photo_links": reception.vehicle_photo_links or {},
            "visible_damage_status": reception.visible_damage_status,
            "damage_description": reception.damage_description,
            "missing_required": missing_required,
        },
        reception.confirmed_by_id,
    )
    next_phase = _get_phase_or_404(db, process.id, "history_check")
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
            ),
            "campaigns_checked": (
                history.campaigns_checked,
                history.campaigns_link,
                False,
            ),
            "maintenance_plan_checked": (
                history.maintenance_plan_checked,
                history.maintenance_plan_link,
                bool(validated_plan_report),
            ),
        }
        for field_name, (value, evidence_link, has_validated_report) in stellantis_checks.items():
            if not _verification_option_satisfied(value, evidence_link, has_validated_report):
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
            "campaigns_checked": history.campaigns_checked,
            "campaigns_link": history.campaigns_link,
            "maintenance_plan_checked": (
                "evidence_link" if validated_plan_report else history.maintenance_plan_checked
            ),
            "maintenance_plan_link": history.maintenance_plan_link,
            "maintenance_plan_report_id": validated_plan_report.id
            if validated_plan_report
            else None,
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
    phase_code = (
        "internal_repair_execution"
        if report_input.report_moment == "final"
        else "technical_phase"
    )
    phase = _get_phase_or_404(db, process.id, phase_code)
    report_status = "pending_validation" if report_input.extracted_values else "added"
    report = WorkshopTechnicalReport(
        process_id=process.id,
        phase_id=phase.id,
        report_code=report_input.report_code,
        report_name=REPORT_LABELS[report_input.report_code],
        reading_origin=report_input.reading_origin,
        reading_origin_detail=report_input.reading_origin_detail,
        report_moment=report_input.report_moment,
        status=report_status,
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
    return {
        "id": report.id,
        "status": report.status,
        "report_name": report.report_name,
        "extracted_values": report.extracted_values_json,
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
    report.validated_values_json = validation.validated_values
    report.correction_json = validation.correction
    report.validated_by_id = validation.validated_by_id
    report.validated_at = datetime.utcnow()
    report.observations = validation.observations or report.observations
    report.status = "corrected_manually" if validation.correction else "validated"
    if report.report_code == "maintenance_plan_validation":
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
    return {"id": report.id, "status": report.status}


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
    if report_input.raw_values is not None:
        report.raw_values_json = report_input.raw_values
    if report_input.extracted_values is not None:
        report.extracted_values_json = report_input.extracted_values
        if report.status in {"added", "pending", "pending_validation"}:
            report.status = "pending_validation"
    if report_input.observations is not None:
        report.observations = report_input.observations
    db.commit()
    return {
        "id": report.id,
        "status": report.status,
        "report_name": report.report_name,
        "extracted_values": report.extracted_values_json,
    }


@router.post("/processes/{process_id}/technical-checks")
def upsert_technical_check(
    process_id: int,
    check_input: WorkshopTechnicalCheckUpsert,
    db: DbSession,
) -> dict[str, Any]:
    process = _get_process_or_404(db, process_id)
    phase = _get_phase_or_404(db, process.id, "technical_phase")
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
        db.add(task)
        db.flush()
        task_id = task.id

    check.status = check_input.status
    check.observation = check_input.observation
    check.evidence_link = check_input.evidence_link
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
    phase = _get_phase_or_404(db, process.id, "technical_phase")
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
            "final_km_visible": repair.final_km_visible,
            "final_evidence_links": repair.final_evidence_links or {},
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
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
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
                "vehicle": _vehicle_summary(vehicle, process.plate_snapshot),
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
        .order_by(WorkshopTechnicalReport.created_at)
    ).all()
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
        "vehicle": _vehicle_summary(vehicle, process.plate_snapshot),
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
