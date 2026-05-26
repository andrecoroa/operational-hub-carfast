from __future__ import annotations

from datetime import UTC, date, datetime
from secrets import compare_digest

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select

from app.api.deps import DbSession
from app.core.config import settings
from app.models.documents import Document, DocumentEvent
from app.models.integrations import EmailIntake
from app.models.tasks import QuickRecord
from app.services.audit import record_audit

router = APIRouter(prefix="/integrations")


class EmailIntakePayload(BaseModel):
    source_mailbox: str = Field(..., min_length=3, max_length=255)
    sender: str | None = Field(default=None, max_length=255)
    subject: str | None = Field(default=None, max_length=255)
    body_preview: str | None = None
    received_at: datetime | None = None
    email_url: str | None = None
    attachments_url: str | None = None
    list_item_id: str | None = Field(default=None, max_length=255)
    list_item_url: str | None = None
    external_message_id: str | None = Field(default=None, max_length=255)
    conversation_id: str | None = Field(default=None, max_length=255)
    target_kind: str | None = Field(default=None, max_length=80)
    target_area: str | None = Field(default=None, max_length=80)


def clip(value: str | None, length: int) -> str | None:
    if value is None:
        return None
    clean_value = value.strip()
    return clean_value[:length] if clean_value else None


def require_integration_key(header_key: str | None) -> None:
    expected_key = settings.integration_api_key
    if not expected_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Integration key is not configured.",
        )
    if not header_key or not compare_digest(header_key, expected_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid integration key.")


def normalize_area(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized in {"workshop", "oficina"}:
        return "workshop"
    if normalized in {"finance", "financial", "financeiro"}:
        return "finance"
    return None


def document_folder_label(document_type: str) -> str:
    return {
        "workshop_other": "Outros documentos de oficina",
        "finance_other": "Outros documentos financeiros",
    }.get(document_type, "Outros documentos")


def suggest_folder_path(area: str, document_date: date | None, document_type: str) -> str:
    reference_date = document_date or date.today()
    year = f"{reference_date.year:04d}"
    month = f"{reference_date.month:02d}"
    if area == "workshop":
        return f"Oficina/Sem matrícula/{year}/{month}/{document_folder_label(document_type)}"
    return f"Financeiro/{year}/{month}/{document_folder_label(document_type)}"


def classify_payload(payload: EmailIntakePayload) -> tuple[str, str, str]:
    requested_kind = (payload.target_kind or "").strip().lower()
    requested_area = normalize_area(payload.target_area)
    mailbox = payload.source_mailbox.lower()

    if requested_kind in {"document", "documento"}:
        area = requested_area or ("workshop" if "oficina" in mailbox else "finance")
        return "document", area, "Integração pediu criação de documento."
    if requested_kind in {"quick_record", "quick", "registo", "registo_rapido"}:
        workspace = requested_area or ("workshop" if "oficina" in mailbox else "operational")
        return "quick_record", workspace, "Integração pediu criação de registo rápido."

    if "oficina" in mailbox or "workshop" in mailbox:
        return "quick_record", "workshop", "E-mail recebido na caixa de oficina."
    if "finance" in mailbox or "financeiro" in mailbox or "fatur" in mailbox or "contab" in mailbox:
        return "document", "finance", "E-mail recebido na caixa financeira."
    if "document" in mailbox or "arquivo" in mailbox:
        return "document", requested_area or "finance", "E-mail recebido na caixa documental."
    return "quick_record", "operational", "E-mail recebido sem regra específica."


def existing_intake(db: DbSession, payload: EmailIntakePayload) -> EmailIntake | None:
    conditions = []
    if payload.external_message_id:
        conditions.append(EmailIntake.external_message_id == payload.external_message_id.strip())
    if payload.list_item_id:
        conditions.append(EmailIntake.list_item_id == payload.list_item_id.strip())
    if payload.email_url:
        conditions.append(EmailIntake.email_url == payload.email_url.strip())
    if not conditions:
        return None
    return db.scalar(select(EmailIntake).where(or_(*conditions)).order_by(EmailIntake.id.desc()))


def source_link(payload: EmailIntakePayload) -> str | None:
    return clip(payload.attachments_url, 2000) or clip(payload.email_url, 2000) or clip(payload.list_item_url, 2000)


def create_quick_record(db: DbSession, intake: EmailIntake, payload: EmailIntakePayload, workspace: str) -> QuickRecord:
    clean_workspace = workspace if workspace in {"operational", "workshop", "management", "administration"} else "operational"
    record_type = "technical_request" if clean_workspace == "workshop" else "information"
    description_parts = [
        clip(payload.body_preview, 4000),
        f"Remetente: {payload.sender}" if payload.sender else None,
        f"Caixa de entrada: {payload.source_mailbox}",
        f"Link do e-mail: {payload.email_url}" if payload.email_url else None,
        f"Link de anexos/lista: {payload.attachments_url or payload.list_item_url}" if (payload.attachments_url or payload.list_item_url) else None,
    ]
    record = QuickRecord(
        workspace=clean_workspace,
        record_type=record_type,
        title=clip(payload.subject, 200) or "Entrada recebida por e-mail",
        description="\n".join(part for part in description_parts if part),
        status="new",
        priority="normal",
        source="email",
        customer_email=clip(payload.sender, 255),
        entity_type="email_intake",
        entity_id=str(intake.id),
    )
    db.add(record)
    db.flush()
    return record


def create_document(db: DbSession, intake: EmailIntake, payload: EmailIntakePayload, area: str) -> Document:
    link = source_link(payload)
    if not link:
        raise ValueError("document_link_required")
    document_type = "workshop_other" if area == "workshop" else "finance_other"
    document_date = (payload.received_at or datetime.now(UTC)).date()
    title = clip(payload.subject, 200) or "Documento recebido por e-mail"
    document = Document(
        title=title,
        document_type=document_type,
        classification=area,
        status="unclassified",
        source="email",
        entry_channel=clip(payload.source_mailbox, 120),
        source_sender=clip(payload.sender, 255),
        source_subject=clip(payload.subject, 255),
        original_name=title[:255],
        file_name=title[:255],
        file_type=None,
        file_size=None,
        storage_provider="sharepoint",
        storage_path=link,
        storage_key=clip(payload.email_url, 2000),
        external_url=link,
        folder_path=suggest_folder_path(area, document_date, document_type),
        document_date=document_date,
        uploaded_by_id=None,
        archived_by_id=None,
        archived_at=None,
        archived=False,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentEvent(
            document_id=document.id,
            action="created_from_email",
            old_value=None,
            new_value=f"Entrada de e-mail #{intake.id}. Pasta sugerida: {document.folder_path}",
            user_id=None,
        )
    )
    if payload.body_preview:
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="source_preview",
                old_value=None,
                new_value=clip(payload.body_preview, 4000),
                user_id=None,
            )
        )
    return document


@router.post("/email-intake", status_code=status.HTTP_201_CREATED)
def intake_email(
    payload: EmailIntakePayload,
    db: DbSession,
    x_carfast_integration_key: str | None = Header(default=None),
):
    require_integration_key(x_carfast_integration_key)

    duplicate = existing_intake(db, payload)
    if duplicate:
        return {
            "status": "duplicate",
            "intake_id": duplicate.id,
            "target_type": duplicate.target_entity_type,
            "target_id": duplicate.target_entity_id,
            "target_url": duplicate.target_url,
        }

    target_kind, target_area, routing_note = classify_payload(payload)
    intake = EmailIntake(
        source_mailbox=payload.source_mailbox.strip().lower(),
        sender=clip(payload.sender, 255),
        subject=clip(payload.subject, 255),
        body_preview=payload.body_preview.strip() if payload.body_preview else None,
        received_at=payload.received_at,
        email_url=clip(payload.email_url, 2000),
        attachments_url=clip(payload.attachments_url, 2000),
        list_item_id=clip(payload.list_item_id, 255),
        list_item_url=clip(payload.list_item_url, 2000),
        external_message_id=clip(payload.external_message_id, 255),
        conversation_id=clip(payload.conversation_id, 255),
        status="received",
        routing_note=routing_note,
        payload_json=payload.model_dump(mode="json"),
    )
    db.add(intake)
    db.flush()

    try:
        if target_kind == "document":
            target = create_document(db, intake, payload, target_area)
            intake.target_entity_type = "document"
            intake.target_entity_id = str(target.id)
            intake.target_url = f"/documents/{target.id}"
        else:
            target = create_quick_record(db, intake, payload, target_area)
            intake.target_entity_type = "quick_record"
            intake.target_entity_id = str(target.id)
            intake.target_url = f"/task-board/quick/{target.id}"
        intake.status = "created_in_app"
        record_audit(
            db,
            action="integration.email_intake.created",
            entity_type=intake.target_entity_type,
            entity_id=intake.target_entity_id,
            detail=f"E-mail recebido de {payload.source_mailbox} criado na app.",
            after_json={
                "intake_id": intake.id,
                "target_type": intake.target_entity_type,
                "target_url": intake.target_url,
                "routing_note": intake.routing_note,
            },
        )
        db.commit()
    except Exception as exc:
        intake.status = "error"
        intake.error_message = str(exc)
        record_audit(
            db,
            action="integration.email_intake.error",
            entity_type="email_intake",
            entity_id=intake.id,
            detail=f"Erro ao tratar entrada de e-mail: {exc}",
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    return {
        "status": intake.status,
        "intake_id": intake.id,
        "target_type": intake.target_entity_type,
        "target_id": intake.target_entity_id,
        "target_url": intake.target_url,
        "routing_note": intake.routing_note,
    }
