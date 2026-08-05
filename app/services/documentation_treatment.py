from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.documents import (
    Document,
    DocumentEvent,
    DocumentWorkflowState,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.models.vehicles import Vehicle
from app.services.audit import record_audit
from app.services.document_workflow import (
    INVOICE_NATURES,
    classify_invoice_nature,
    get_or_create_workflow_state,
)
from app.services.stock import ensure_invoice_import

TREATMENT_ACTIONS = frozenset(
    {
        "classify",
        "associate",
        "extract",
        "reprocess",
        "save_services",
        "validate",
        "resolve",
        "complete",
        "archive",
        "reconcile",
    }
)

TREATMENT_ACTION_LABELS = {
    "classify": "Classificar / guardar pendente",
    "associate": "Associar à viatura",
    "extract": "Extrair",
    "reprocess": "Reprocessar",
    "save_services": "Guardar serviços",
    "validate": "Validar documento",
    "resolve": "Concluir com exceção",
    "complete": "Concluir tratamento",
    "archive": "Arquivar",
    "reconcile": "Reconciliar com documento real",
}

TREATMENT_REASON_LABELS = {
    "action_not_supported": "A ação não é suportada.",
    "expected_invoice_requires_real_document": "A fatura esperada ainda não tem documento real.",
    "expected_invoice_action": "A fatura esperada só permite associação ou reconciliação.",
    "vehicle_required": "Falta associar a viatura.",
    "vehicle_not_found": "A matrícula indicada não corresponde a uma viatura.",
    "extraction_required": "Falta concluir a extração.",
    "invoice_nature_required": "Falta classificar a natureza da fatura.",
    "services_required": "Falta guardar pelo menos um serviço.",
    "validation_required": "Falta validar o documento.",
    "reason_required": "É obrigatório indicar o motivo da exceção.",
    "common_plate_confirmation_required": "Confirme explicitamente a matrícula comum do lote.",
    "document_removed": "O documento foi removido e não pode ser tratado.",
    "document_required": "O documento não existe.",
}


def _is_invoice(document: Document) -> bool:
    return (document.document_type or "").strip().lower() in {
        "workshop_supplier_invoice",
        "finance_supplier_invoice",
    }


def _is_diagnostic(document: Document) -> bool:
    return (document.document_type or "").strip().lower() in {
        "workshop_diagnostic",
        "workshop_report",
        "diagnostic_report",
        "technical_report",
    }


def service_count(db: Session, document_id: int) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(VehicleDocumentRecordTag)
            .where(VehicleDocumentRecordTag.document_id == document_id)
        )
        or 0
    )


def document_treatment_dimensions(
    document: Document,
    state: DocumentWorkflowState,
    *,
    saved_service_count: int,
) -> dict[str, dict[str, str]]:
    is_invoice = _is_invoice(document)
    requires_vehicle = not is_invoice or state.invoice_nature in {
        None,
        "por_classificar",
        "operacional",
    }
    association = (
        {"status": "completed", "label": "Concluído"}
        if state.association_status == "associated" or not requires_vehicle
        else {
            "status": "error" if state.association_status == "failed" else "pending",
            "label": "Erro" if state.association_status == "failed" else "Pendente",
        }
    )
    extraction = {
        "status": (
            "completed"
            if state.extraction_status == "extracted"
            else "error"
            if state.extraction_status == "failed"
            else "pending"
        ),
        "label": (
            "Concluído"
            if state.extraction_status == "extracted"
            else "Erro"
            if state.extraction_status == "failed"
            else "Pendente"
        ),
    }
    if not is_invoice or state.invoice_nature not in {None, "por_classificar", "operacional"}:
        services = {"status": "completed", "label": "Não aplicável"}
    elif not document.vehicle_id:
        services = {"status": "blocked", "label": "Bloqueado"}
    elif saved_service_count:
        services = {"status": "completed", "label": f"{saved_service_count} guardado(s)"}
    else:
        services = {"status": "pending", "label": "Pendente"}
    validation = {
        "status": "completed" if state.validation_status == "human_validated" else "pending",
        "label": "Concluído" if state.validation_status == "human_validated" else "Pendente",
    }
    nature = {
        "status": (
            "completed"
            if not is_invoice or state.invoice_nature not in {None, "por_classificar"}
            else "pending"
        ),
        "label": state.invoice_nature or ("Não aplicável" if not is_invoice else "Por classificar"),
    }
    dimensions = {
        "nature": nature,
        "association": association,
        "extraction": extraction,
        "services": services,
        "validation": validation,
    }
    dimensions["next_action"] = {
        "status": "pending",
        "label": next_treatment_action(document, state, saved_service_count=saved_service_count),
    }
    return dimensions


def next_treatment_action(
    document: Document,
    state: DocumentWorkflowState,
    *,
    saved_service_count: int,
) -> str:
    if _is_invoice(document) and state.invoice_nature in {None, "por_classificar"}:
        return "Classificar natureza"
    if state.association_status != "associated" and (
        not _is_invoice(document) or state.invoice_nature == "operacional"
    ):
        return "Associar viatura"
    if state.extraction_status != "extracted" and (
        _is_invoice(document) or _is_diagnostic(document)
    ):
        return "Extrair / reprocessar"
    if _is_invoice(document) and state.invoice_nature == "operacional" and not saved_service_count:
        return "Guardar serviços"
    if state.validation_status != "human_validated":
        return "Validar documento"
    return "Concluir tratamento"


def expected_invoice_dimensions(record: VehicleDocumentRecord) -> dict[str, dict[str, str]]:
    associated = bool(record.vehicle_id)
    return {
        "nature": {"status": "blocked", "label": "Fatura esperada"},
        "association": {
            "status": "completed" if associated else "pending",
            "label": "Concluído" if associated else "Pendente",
        },
        "extraction": {"status": "blocked", "label": "Sem documento real"},
        "services": {"status": "blocked", "label": "Sem documento real"},
        "validation": {"status": "blocked", "label": "Sem documento real"},
        "next_action": {
            "status": "pending",
            "label": "Reconciliar documento" if associated else "Associar viatura",
        },
    }


def document_action_compatibility(
    document: Document,
    state: DocumentWorkflowState,
    *,
    action: str,
    invoice_nature: str = "",
    plate: str = "",
    reason: str = "",
    saved_service_count: int = 0,
) -> tuple[bool, str]:
    clean_action = action.strip().lower()
    if clean_action not in TREATMENT_ACTIONS - {"reconcile"}:
        return False, "action_not_supported"
    if (document.status or "").strip().lower() in {"removed", "deleted"}:
        return False, "document_removed"
    effective_nature = (
        invoice_nature.strip().lower()
        if clean_action == "classify" and invoice_nature.strip()
        else state.invoice_nature
    )
    will_associate = state.association_status == "associated"
    if clean_action == "associate" and not plate.strip():
        return False, "vehicle_required"
    if clean_action == "save_services" and not document.vehicle_id:
        return False, "vehicle_required"
    if clean_action == "resolve":
        return (True, "") if reason.strip() else (False, "reason_required")
    if clean_action in {"validate", "complete", "archive"}:
        if _is_invoice(document) and effective_nature in {None, "", "por_classificar"}:
            return False, "invoice_nature_required"
        requires_vehicle = not _is_invoice(document) or effective_nature == "operacional"
        if requires_vehicle and not will_associate:
            return False, "vehicle_required"
        if (
            _is_invoice(document) or _is_diagnostic(document)
        ) and state.extraction_status != "extracted":
            return False, "extraction_required"
        if _is_invoice(document) and effective_nature == "operacional" and not saved_service_count:
            return False, "services_required"
        if clean_action in {"complete", "archive"} and state.validation_status != "human_validated":
            return False, "validation_required"
    return True, ""


def expected_action_compatibility(
    record: VehicleDocumentRecord,
    *,
    action: str,
    plate: str = "",
) -> tuple[bool, str]:
    clean_action = action.strip().lower()
    if clean_action == "associate":
        if record.vehicle_id:
            return False, "expected_invoice_action"
        return (True, "") if plate.strip() else (False, "vehicle_required")
    if clean_action == "reconcile":
        return True, ""
    return False, "expected_invoice_requires_real_document"


def find_vehicle_by_plate(db: Session, plate: str) -> Vehicle | None:
    clean_plate = plate.strip()
    if not clean_plate:
        return None
    return db.scalar(select(Vehicle).where(func.lower(Vehicle.plate) == clean_plate.lower()))


def associate_expected_invoice(
    db: Session,
    *,
    record: VehicleDocumentRecord,
    plate: str,
    user_id: int | None,
) -> Vehicle:
    vehicle = find_vehicle_by_plate(db, plate)
    if not vehicle:
        raise ValueError("vehicle_not_found")
    before = {"vehicle_id": record.vehicle_id, "plate": record.plate, "status": record.status}
    record.vehicle_id = vehicle.id
    record.plate = vehicle.plate
    record.vin = vehicle.vin
    record.updated_by_id = user_id
    metadata = dict(record.metadata_json or {})
    metadata.update({"association_method": "treatment", "association_identifier": plate.strip()})
    record.metadata_json = metadata
    record_audit(
        db,
        action="expected_invoice.associated",
        entity_type="vehicle_document_record",
        entity_id=record.id,
        before_json=before,
        after_json={
            "vehicle_id": record.vehicle_id,
            "plate": record.plate,
            "status": record.status,
        },
        detail="Fatura esperada associada na fila de tratamento.",
        user_id=user_id,
    )
    return vehicle


def apply_document_treatment_action(
    db: Session,
    *,
    document: Document,
    action: str,
    user_id: int | None,
    reason: str = "",
    invoice_nature: str = "",
    destination: str = "",
    plate: str = "",
    extraction_succeeded: bool | None = None,
) -> DocumentWorkflowState:
    clean_action = action.strip().lower()
    if clean_action not in TREATMENT_ACTIONS - {"reconcile", "save_services"}:
        raise ValueError("action_not_supported")
    clean_reason = reason.strip() or TREATMENT_ACTION_LABELS[clean_action]
    state = get_or_create_workflow_state(db, document)
    before = {
        "invoice_nature": state.invoice_nature,
        "association_status": state.association_status,
        "extraction_status": state.extraction_status,
        "validation_status": state.validation_status,
        "destination_status": state.destination_status,
        "document_status": document.status,
        "archived": document.archived,
    }
    clean_nature = invoice_nature.strip().lower() if clean_action == "classify" else ""
    if clean_nature:
        if clean_nature not in INVOICE_NATURES:
            raise ValueError("invoice_nature_required")
        classify_invoice_nature(
            db,
            document=document,
            nature=clean_nature,
            user_id=user_id,
            decision_reason=clean_reason,
        )
        state = get_or_create_workflow_state(db, document)
        if clean_nature == "stock":
            ensure_invoice_import(db, document=document, user_id=user_id)
    if clean_action == "associate" and plate.strip():
        vehicle = find_vehicle_by_plate(db, plate)
        if not vehicle:
            raise ValueError("vehicle_not_found")
        document.vehicle_id = vehicle.id
        document.plate = vehicle.plate
        state.association_status = "associated"
    if clean_action == "classify" and destination.strip() in {
        "triage",
        "imports",
        "invoices",
        "diagnostics",
        "archive",
    }:
        state.destination_status = destination.strip()

    if clean_action == "classify":
        state.ingestion_status = "completed"
        if state.validation_status != "human_validated":
            document.status = "pending_validation"
    elif clean_action == "associate":
        if not plate.strip():
            raise ValueError("vehicle_required")
    elif clean_action in {"extract", "reprocess"}:
        if extraction_succeeded is False:
            state.extraction_status = "failed"
            document.status = "ocr_issue"
        else:
            state.extraction_status = "extracted" if extraction_succeeded else "queued"
            document.status = "extracted" if extraction_succeeded else "pending_extraction"
        state.validation_status = "pending"
    elif clean_action == "validate":
        state.validation_status = "human_validated"
        state.human_confirmed = True
        state.confirmed_by_id = user_id
        state.confirmed_at = datetime.now(UTC)
        document.status = "pending_completion"
    elif clean_action == "resolve":
        if not reason.strip():
            raise ValueError("reason_required")
        state.validation_status = "human_validated"
        state.human_confirmed = True
        state.confirmed_by_id = user_id
        state.confirmed_at = datetime.now(UTC)
        document.status = "classified"
    elif clean_action in {"complete", "archive"}:
        if clean_action == "archive" or state.destination_status == "archive":
            state.destination_status = "archive"
            document.archived = True
            document.archived_at = document.archived_at or datetime.now(UTC)
            document.archived_by_id = user_id
            document.status = "archived"
        else:
            document.status = "classified"
    state.decision_reason = clean_reason
    after = {
        "invoice_nature": state.invoice_nature,
        "association_status": state.association_status,
        "extraction_status": state.extraction_status,
        "validation_status": state.validation_status,
        "destination_status": state.destination_status,
        "document_status": document.status,
        "archived": document.archived,
    }
    db.add(
        DocumentEvent(
            document_id=document.id,
            action=f"document.treatment.{clean_action}",
            old_value=json.dumps(before, ensure_ascii=False),
            new_value=json.dumps({**after, "reason": clean_reason}, ensure_ascii=False),
            user_id=user_id,
        )
    )
    record_audit(
        db,
        action=f"document.treatment.{clean_action}",
        entity_type="document",
        entity_id=document.id,
        before_json=before,
        after_json=after,
        detail=clean_reason,
        user_id=user_id,
    )
    return state
