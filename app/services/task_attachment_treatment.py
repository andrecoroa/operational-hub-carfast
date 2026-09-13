from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import Document, DocumentEvent, DocumentLink
from app.models.tasks import Task, TaskDocument, TaskHistory
from app.models.vehicles import Vehicle
from app.services.audit import record_audit
from app.services.document_workflow import get_or_create_workflow_state, transition_document_workflow


DOCUMENT_TYPE_AREAS = {
    "workshop_photo": "workshop",
    "workshop_diagnostic": "workshop",
    "workshop_bsi": "workshop",
    "workshop_work_order": "workshop",
    "workshop_quote": "workshop",
    "workshop_supplier_invoice": "workshop",
    "workshop_evidence": "workshop",
    "workshop_report": "workshop",
    "workshop_other": "workshop",
    "maintenance_plan": "fleet",
    "general_fleet": "fleet",
    "finance_supplier_invoice": "finance",
    "finance_credit_note": "finance",
    "finance_receipt": "finance",
    "finance_payment_proof": "finance",
    "finance_customer_document": "finance",
    "finance_rental_plan": "finance",
    "finance_other": "finance",
}


def treat_task_attachment(
    db: Session,
    *,
    task_id: int,
    document_id: int,
    vehicle_id: int,
    document_type: str,
    user_id: int | None,
) -> Document:
    """Classify a task attachment in place and associate it with a vehicle.

    The existing ``Document`` row is deliberately reused so its storage path,
    external URL and file hash remain unchanged.
    """

    task = db.get(Task, task_id)
    document = db.get(Document, document_id)
    vehicle = db.get(Vehicle, vehicle_id)
    task_link = db.scalar(
        select(TaskDocument).where(
            TaskDocument.task_id == task_id,
            TaskDocument.document_id == document_id,
            TaskDocument.category.in_(("attachment", "Anexo")),
        )
    )
    if not task or not document or not vehicle or not task_link:
        raise ValueError("Anexo, tarefa ou viatura inválidos.")

    clean_type = document_type.strip()
    classification = DOCUMENT_TYPE_AREAS.get(clean_type)
    if not classification:
        raise ValueError("Tipologia documental inválida.")

    before = {
        "vehicle_id": document.vehicle_id,
        "plate": document.plate,
        "document_type": document.document_type,
        "classification": document.classification,
        "status": document.status,
        "storage_path": document.storage_path,
        "external_url": document.external_url,
        "file_hash": document.file_hash,
    }
    document.vehicle_id = vehicle.id
    document.plate = vehicle.plate
    document.document_type = clean_type
    document.classification = classification
    document.status = "classified"

    vehicle_link = db.scalar(
        select(DocumentLink).where(
            DocumentLink.document_id == document.id,
            DocumentLink.entity_type == "vehicle",
            DocumentLink.entity_id == str(vehicle.id),
        )
    )
    if not vehicle_link:
        db.add(
            DocumentLink(
                document_id=document.id,
                entity_type="vehicle",
                entity_id=str(vehicle.id),
                category="task_attachment_treatment",
            )
        )

    state = get_or_create_workflow_state(db, document)
    if (
        state.association_status != "associated"
        or state.validation_status != "human_validated"
        or state.destination_status != "archive"
    ):
        transition_document_workflow(
            db,
            document=document,
            user_id=user_id,
            reason=f"Anexo da tarefa CF-TASK-{task.id:05d} tratado manualmente.",
            association_status="associated",
            validation_status="human_validated",
            destination_status="archive",
        )

    after = {
        "vehicle_id": document.vehicle_id,
        "plate": document.plate,
        "document_type": document.document_type,
        "classification": document.classification,
        "status": document.status,
        "storage_path": document.storage_path,
        "external_url": document.external_url,
        "file_hash": document.file_hash,
    }
    if before != after:
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="task_attachment.treated",
                old_value=json.dumps(before, ensure_ascii=False),
                new_value=json.dumps(after, ensure_ascii=False),
                user_id=user_id,
            )
        )
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="task_attachment.treated",
                old_value=str(document.id),
                new_value=f"{vehicle.plate or vehicle.id} · {clean_type}",
            )
        )
        record_audit(
            db,
            action="task_attachment.treated",
            entity_type="document",
            entity_id=document.id,
            detail=f"Anexo da tarefa tratado e associado à viatura {vehicle.plate or vehicle.id}.",
            before_json=before,
            after_json=after,
            user_id=user_id,
        )
    db.flush()
    return document
