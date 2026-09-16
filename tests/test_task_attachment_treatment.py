from sqlalchemy import func, select

from app.models.audit import AuditLog
from app.models.documents import Document, DocumentEvent, DocumentLink, DocumentWorkflowState
from app.models.tasks import Task, TaskDocument, TaskHistory
from app.models.vehicles import Vehicle
from app.services.task_attachment_treatment import treat_task_attachment


def _task_attachment(db_session):
    vehicle = Vehicle(plate="AA-01-BB", vin="VIN-TREAT-001")
    task = Task(title="Tratar anexo", task_type="operational", status="new")
    document = Document(
        title="Anexo recebido",
        original_name="anexo.pdf",
        file_name="anexo.pdf",
        storage_provider="sharepoint",
        storage_path="/email/anexo.pdf",
        external_url="https://example.test/anexo.pdf",
        file_hash="hash-original",
        status="received",
    )
    db_session.add_all([vehicle, task, document])
    db_session.flush()
    db_session.add(TaskDocument(task_id=task.id, document_id=document.id, category="attachment"))
    db_session.flush()
    return task, document, vehicle


def test_treat_task_attachment_reuses_file_and_records_audit(db_session):
    task, document, vehicle = _task_attachment(db_session)

    treated = treat_task_attachment(
        db_session,
        task_id=task.id,
        document_id=document.id,
        vehicle_id=vehicle.id,
        document_type="maintenance_plan",
        user_id=None,
    )

    assert treated.id == document.id
    assert treated.storage_path == "/email/anexo.pdf"
    assert treated.external_url == "https://example.test/anexo.pdf"
    assert treated.file_hash == "hash-original"
    assert treated.vehicle_id == vehicle.id
    assert treated.plate == "AA-01-BB"
    assert treated.document_type == "maintenance_plan"
    assert treated.classification == "fleet"
    assert treated.status == "classified"
    assert db_session.scalar(
        select(func.count()).select_from(DocumentLink).where(
            DocumentLink.document_id == document.id,
            DocumentLink.entity_type == "vehicle",
            DocumentLink.entity_id == str(vehicle.id),
        )
    ) == 1
    state = db_session.scalar(
        select(DocumentWorkflowState).where(DocumentWorkflowState.document_id == document.id)
    )
    assert state.association_status == "associated"
    assert state.validation_status == "human_validated"
    assert state.destination_status == "archive"
    assert db_session.scalar(
        select(func.count()).select_from(DocumentEvent).where(
            DocumentEvent.document_id == document.id,
            DocumentEvent.action == "task_attachment.treated",
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(TaskHistory).where(
            TaskHistory.task_id == task.id,
            TaskHistory.field_name == "task_attachment.treated",
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "task_attachment.treated",
            AuditLog.entity_id == str(document.id),
        )
    ) == 1


def test_treat_task_attachment_is_idempotent(db_session):
    task, document, vehicle = _task_attachment(db_session)
    args = {
        "task_id": task.id,
        "document_id": document.id,
        "vehicle_id": vehicle.id,
        "document_type": "maintenance_plan",
        "user_id": None,
    }

    treat_task_attachment(db_session, **args)
    treat_task_attachment(db_session, **args)

    assert db_session.scalar(
        select(func.count()).select_from(DocumentLink).where(
            DocumentLink.document_id == document.id,
            DocumentLink.entity_type == "vehicle",
            DocumentLink.entity_id == str(vehicle.id),
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(DocumentEvent).where(
            DocumentEvent.document_id == document.id,
            DocumentEvent.action == "task_attachment.treated",
        )
    ) == 1
    assert db_session.scalar(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "task_attachment.treated",
            AuditLog.entity_id == str(document.id),
        )
    ) == 1


def test_treat_task_attachment_rejects_non_attachment_link(db_session):
    task, document, vehicle = _task_attachment(db_session)
    link = db_session.scalar(
        select(TaskDocument).where(
            TaskDocument.task_id == task.id,
            TaskDocument.document_id == document.id,
        )
    )
    link.category = "source"
    db_session.flush()

    try:
        treat_task_attachment(
            db_session,
            task_id=task.id,
            document_id=document.id,
            vehicle_id=vehicle.id,
            document_type="maintenance_plan",
            user_id=None,
        )
    except ValueError as exc:
        assert "inválidos" in str(exc)
    else:
        raise AssertionError("Expected a non-attachment link to be rejected")
