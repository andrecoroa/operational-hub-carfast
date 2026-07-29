from __future__ import annotations

from datetime import UTC, datetime
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import Document, DocumentEvent, DocumentWorkflowState
from app.services.audit import record_audit


INGESTION_STATUSES = frozenset({"received", "queued", "processing", "completed", "failed"})
ASSOCIATION_STATUSES = frozenset({"unassociated", "suggested", "associated", "failed"})
EXTRACTION_STATUSES = frozenset({"not_requested", "queued", "processing", "extracted", "failed"})
VALIDATION_STATUSES = frozenset({"pending", "automatic_validated", "human_validated", "rejected"})
DESTINATION_STATUSES = frozenset({"triage", "imports", "invoices", "diagnostics", "archive", "unknown"})
INVOICE_NATURES = frozenset({"por_classificar", "operacional", "financeira"})

WORKFLOW_LABELS = {
    "received": "Recebido",
    "queued": "Em fila",
    "processing": "Em processamento",
    "completed": "Concluído",
    "failed": "Com erro",
    "unassociated": "Sem associação",
    "suggested": "Associação sugerida",
    "associated": "Associado",
    "not_requested": "Não solicitado",
    "extracted": "Extraído",
    "pending": "Pendente",
    "automatic_validated": "Validado automaticamente",
    "human_validated": "Validado por pessoa",
    "rejected": "Rejeitado",
    "triage": "Triagem",
    "imports": "Importações",
    "invoices": "Faturas",
    "diagnostics": "Diagnósticos",
    "archive": "Arquivo",
    "unknown": "Por definir",
    "por_classificar": "Por classificar",
    "operacional": "Operacional",
    "financeira": "Financeira",
}


def legacy_workflow_values(document: Document) -> dict[str, Any]:
    """Map a legacy document to the multidimensional Clean state.

    This adapter keeps old rows visible while the migration is gradual.  It is
    intentionally deterministic so it can be used by both the data migration
    and read paths without modifying a row during a GET request.
    """

    legacy_status = (document.status or "received").strip().lower()
    document_type = (document.document_type or "").strip().lower()
    is_invoice = document_type in {"workshop_supplier_invoice", "finance_supplier_invoice"}
    is_diagnostic = document_type in {
        "workshop_diagnostic",
        "workshop_report",
        "diagnostic_report",
        "technical_report",
    }

    if legacy_status in {"failed", "ocr_issue", "unable_to_read", "error"}:
        ingestion_status = "failed"
    elif legacy_status in {"pending_triage", "received", "pending"}:
        ingestion_status = "received"
    else:
        ingestion_status = "completed"

    association_status = "associated" if document.vehicle_id else "unassociated"
    if legacy_status in {"ocr_issue", "unable_to_read"}:
        extraction_status = "failed"
    elif legacy_status in {"extracted", "classified", "pending_validation"}:
        extraction_status = "extracted"
    else:
        extraction_status = "not_requested"

    if legacy_status in {"classified", "archived"}:
        validation_status = "human_validated"
    elif legacy_status == "ignored":
        validation_status = "rejected"
    else:
        validation_status = "pending"

    if legacy_status == "pending_triage":
        destination_status = "triage"
    elif is_diagnostic:
        destination_status = "diagnostics"
    elif document_type == "finance_supplier_invoice":
        destination_status = "archive"
    elif is_invoice:
        destination_status = "invoices"
    elif document.archived:
        destination_status = "archive"
    else:
        destination_status = "archive"

    invoice_nature = None
    if document_type == "finance_supplier_invoice":
        invoice_nature = "financeira"
    elif document_type == "workshop_supplier_invoice":
        invoice_nature = "operacional"

    return {
        "ingestion_status": ingestion_status,
        "association_status": association_status,
        "extraction_status": extraction_status,
        "validation_status": validation_status,
        "destination_status": destination_status,
        "invoice_nature": invoice_nature,
        "suggested_invoice_nature": None,
        "suggestion_confidence": None,
        "human_confirmed": validation_status == "human_validated",
    }


def workflow_values(
    document: Document,
    state: DocumentWorkflowState | None,
) -> dict[str, Any]:
    values = legacy_workflow_values(document)
    if state:
        values.update(
            {
                "id": state.id,
                "ingestion_status": state.ingestion_status,
                "association_status": state.association_status,
                "extraction_status": state.extraction_status,
                "validation_status": state.validation_status,
                "destination_status": state.destination_status,
                "invoice_nature": state.invoice_nature,
                "suggested_invoice_nature": state.suggested_invoice_nature,
                "suggestion_confidence": state.suggestion_confidence,
                "human_confirmed": state.human_confirmed,
                "confirmed_by_id": state.confirmed_by_id,
                "confirmed_at": state.confirmed_at,
                "decision_reason": state.decision_reason,
            }
        )
    values["labels"] = {
        key: WORKFLOW_LABELS.get(str(value), str(value))
        for key, value in values.items()
        if key.endswith("_status") or key.endswith("_nature")
    }
    return values


def get_or_create_workflow_state(
    db: Session,
    document: Document,
) -> DocumentWorkflowState:
    state = db.scalar(
        select(DocumentWorkflowState).where(DocumentWorkflowState.document_id == document.id)
    )
    if state:
        return state
    state = DocumentWorkflowState(document_id=document.id, **legacy_workflow_values(document))
    db.add(state)
    db.flush()
    return state


def transition_document_workflow(
    db: Session,
    *,
    document: Document,
    user_id: int | None,
    reason: str,
    ingestion_status: str | None = None,
    association_status: str | None = None,
    extraction_status: str | None = None,
    validation_status: str | None = None,
    destination_status: str | None = None,
) -> DocumentWorkflowState:
    requested = {
        "ingestion_status": (ingestion_status, INGESTION_STATUSES),
        "association_status": (association_status, ASSOCIATION_STATUSES),
        "extraction_status": (extraction_status, EXTRACTION_STATUSES),
        "validation_status": (validation_status, VALIDATION_STATUSES),
        "destination_status": (destination_status, DESTINATION_STATUSES),
    }
    for field, (value, allowed) in requested.items():
        if value is not None and value not in allowed:
            raise ValueError(f"Estado inválido para {field}: {value}")

    state = get_or_create_workflow_state(db, document)
    before = {field: getattr(state, field) for field in requested}
    for field, (value, _allowed) in requested.items():
        if value is not None:
            setattr(state, field, value)
    after = {field: getattr(state, field) for field in requested}
    state.decision_reason = reason.strip() or state.decision_reason
    db.add(
        DocumentEvent(
            document_id=document.id,
            action="document.workflow.transitioned",
            old_value=json.dumps(before, ensure_ascii=False),
            new_value=json.dumps({"states": after, "reason": reason}, ensure_ascii=False),
            user_id=user_id,
        )
    )
    record_audit(
        db,
        action="document.workflow.transitioned",
        entity_type="document",
        entity_id=document.id,
        before_json=before,
        after_json=after,
        detail=reason,
        user_id=user_id,
    )
    return state


def classify_invoice_nature(
    db: Session,
    *,
    document: Document,
    nature: str,
    user_id: int | None,
    suggested_nature: str | None = None,
    suggestion_confidence: float | None = None,
    decision_reason: str = "",
) -> DocumentWorkflowState:
    """Apply an invoice decision and recalculate the legacy derived view.

    Historical events are append-only.  Reclassification changes the current
    projection but never deletes the previous decision or operational events.
    """

    clean_nature = nature.strip().lower()
    if clean_nature not in INVOICE_NATURES:
        raise ValueError("A natureza da fatura é obrigatória e tem de ser única.")
    clean_suggestion = (suggested_nature or "").strip().lower() or None
    if clean_suggestion and clean_suggestion not in INVOICE_NATURES:
        raise ValueError("Sugestão de natureza inválida.")
    if suggestion_confidence is not None and not 0 <= suggestion_confidence <= 1:
        raise ValueError("A confiança tem de estar entre 0 e 1.")

    state = get_or_create_workflow_state(db, document)
    before = {
        "invoice_nature": state.invoice_nature,
        "document_type": document.document_type,
        "classification": document.classification,
        "legacy_status": document.status,
        "destination_status": state.destination_status,
        "validation_status": state.validation_status,
    }

    state.invoice_nature = clean_nature
    state.suggested_invoice_nature = clean_suggestion
    state.suggestion_confidence = suggestion_confidence
    state.human_confirmed = True
    state.confirmed_by_id = user_id
    state.confirmed_at = datetime.now(UTC)
    state.decision_reason = decision_reason.strip() or "Classificação manual de fatura"
    state.ingestion_status = "completed"

    if clean_nature == "por_classificar":
        document.document_type = "workshop_supplier_invoice"
        document.classification = "invoice"
        document.status = "pending_classification"
        state.validation_status = "pending"
        state.destination_status = "invoices"
        timeline_visible = False
        archive_only = False
    elif clean_nature == "operacional":
        document.document_type = "workshop_supplier_invoice"
        document.classification = "workshop"
        document.status = "classified"
        state.validation_status = "human_validated"
        state.destination_status = "invoices"
        timeline_visible = True
        archive_only = False
    else:
        document.document_type = "finance_supplier_invoice"
        document.classification = "finance"
        document.status = "archived"
        document.archived = True
        document.archived_at = document.archived_at or datetime.now(UTC)
        document.archived_by_id = user_id
        state.validation_status = "human_validated"
        state.destination_status = "archive"
        timeline_visible = False
        archive_only = True

    state.association_status = "associated" if document.vehicle_id else "unassociated"
    after = {
        "invoice_nature": state.invoice_nature,
        "document_type": document.document_type,
        "classification": document.classification,
        "legacy_status": document.status,
        "destination_status": state.destination_status,
        "validation_status": state.validation_status,
        "timeline_visible": timeline_visible,
        "archive_only": archive_only,
        "suggested_invoice_nature": state.suggested_invoice_nature,
        "suggestion_confidence": state.suggestion_confidence,
        "human_confirmed": True,
    }
    action = (
        "invoice.nature.reclassified"
        if before["invoice_nature"] and before["invoice_nature"] != clean_nature
        else "invoice.nature.classified"
    )
    db.add(
        DocumentEvent(
            document_id=document.id,
            action=action,
            old_value=json.dumps(before, ensure_ascii=False),
            new_value=json.dumps(after, ensure_ascii=False),
            user_id=user_id,
        )
    )
    db.add(
        DocumentEvent(
            document_id=document.id,
            action="invoice.derivatives.recalculated",
            old_value=None,
            new_value=json.dumps(
                {
                    "timeline_visible": timeline_visible,
                    "archive_only": archive_only,
                    "history_preserved": True,
                },
                ensure_ascii=False,
            ),
            user_id=user_id,
        )
    )
    record_audit(
        db,
        action=action,
        entity_type="document",
        entity_id=document.id,
        before_json=before,
        after_json=after,
        detail=state.decision_reason,
        user_id=user_id,
    )
    return state


def confident_destination(suggested_destination: str | None, confidence: float | None) -> str:
    """Only route automatically when the classifier is explicit and >= 90%."""

    destination = (suggested_destination or "").strip().lower()
    if destination not in DESTINATION_STATUSES - {"triage", "unknown"}:
        return "triage"
    if confidence is None or confidence < 0.90:
        return "triage"
    return destination
