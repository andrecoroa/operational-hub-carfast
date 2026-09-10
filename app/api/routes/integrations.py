from __future__ import annotations

import html as html_lib
import json
import re
from datetime import UTC, date, datetime
from secrets import compare_digest
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select

from app.api.deps import DbSession
from app.core.config import settings
from app.documents import DocumentManagementFacade, LinkIngestionRequest, SourceReference
from app.models.documents import Document, DocumentEvent
from app.models.integrations import EmailIntake, EmailIntakeAttachment
from app.models.tasks import QuickRecord
from app.services.audit import record_audit

router = APIRouter(prefix="/integrations")

EMAIL_HEADER_RE = re.compile(r"^(de|from|enviado|sent|para|to|cc|assunto|subject)\s*:", re.IGNORECASE)
EMAIL_CONTACT_RE = re.compile(r"(@|www\.|https?://|\+\d{2,}|\btel\.?:)", re.IGNORECASE)
SIGNATURE_MARKERS = (
    "melhores cumprimentos",
    "best regards",
    "cumprimentos",
)
SIGNATURE_ROLE_LINES = {
    "administrador",
    "gestor",
    "gestor operacional",
    "diretor",
    "director",
    "diretor geral",
    "director geral",
    "financeiro",
}


class EmailIntakePayload(BaseModel):
    source_mailbox: Any = Field(...)
    sender: Any | None = None
    subject: Any | None = None
    body_preview: Any | None = None
    received_at: datetime | None = None
    email_url: Any | None = None
    attachments_url: Any | None = None
    list_item_id: Any | None = None
    list_item_url: Any | None = None
    external_message_id: Any | None = None
    conversation_id: Any | None = None
    target_kind: Any | None = None
    target_area: Any | None = None
    attachments: Any | None = None

    @field_validator("received_at", mode="before")
    @classmethod
    def empty_received_at_as_none(cls, value: Any) -> Any:
        if value == "":
            return None
        return value


def extract_sharepoint_value(value: Any, *, prefer_url: bool = False) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                return extract_sharepoint_value(json.loads(stripped), prefer_url=prefer_url)
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, dict):
        ordered_keys = (
            ("Url", "url", "Value", "Email", "DisplayName", "Description")
            if prefer_url
            else ("Value", "Email", "DisplayName", "Description", "Url", "url")
        )
        for key in ordered_keys:
            candidate = value.get(key)
            if candidate:
                return candidate
        return " ".join(str(part) for part in value.values() if part)
    if isinstance(value, list):
        return " ".join(str(extract_sharepoint_value(item, prefer_url=prefer_url)) for item in value if item)
    return value


def as_text(value: Any, length: int | None = None, *, prefer_url: bool = False) -> str | None:
    if value is None:
        return None
    clean_value = str(extract_sharepoint_value(value, prefer_url=prefer_url)).strip()
    if not clean_value:
        return None
    return clean_value[:length] if length else clean_value


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_attachments(value: Any) -> list[dict[str, Any]]:
    if not value:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            return normalize_attachments(json.loads(stripped))
        except json.JSONDecodeError:
            return []
    if isinstance(value, dict):
        if isinstance(value.get("value"), list):
            return normalize_attachments(value["value"])
        if isinstance(value.get("attachments"), list):
            return normalize_attachments(value["attachments"])
        return [value]
    if not isinstance(value, list):
        return []

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(value, start=1):
        if isinstance(item, str):
            url = as_text(item, 2000, prefer_url=True)
            if url:
                normalized.append({"name": f"Anexo {idx}", "url": url})
            continue
        if not isinstance(item, dict):
            continue
        url = (
            as_text(item.get("url"), 2000, prefer_url=True)
            or as_text(item.get("link"), 2000, prefer_url=True)
            or as_text(item.get("webUrl"), 2000, prefer_url=True)
            or as_text(item.get("Link"), 2000, prefer_url=True)
            or as_text(item.get("Url"), 2000, prefer_url=True)
        )
        if not url:
            continue
        name = (
            as_text(item.get("name"), 255)
            or as_text(item.get("fileName"), 255)
            or as_text(item.get("displayName"), 255)
            or as_text(item.get("Name"), 255)
            or f"Anexo {idx}"
        )
        normalized.append(
            {
                "name": name,
                "url": url,
                "content_type": as_text(item.get("content_type") or item.get("contentType") or item.get("mimeType"), 160),
                "size": as_int(item.get("size") or item.get("Size") or item.get("length")),
            }
        )
    return normalized


def clean_html_preview(value: Any, length: int = 4000) -> str | None:
    text = as_text(value, 20000)
    if not text:
        return None
    text = html_lib.unescape(text)
    text = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|tr|table|li|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"\r", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = reduce_email_noise(text.strip())
    return text[:length] if text else None


def is_likely_signature_name(line: str, next_line: str | None) -> bool:
    if not next_line:
        return False
    if EMAIL_CONTACT_RE.search(next_line) or next_line.strip().lower() in SIGNATURE_ROLE_LINES:
        words = line.split()
        return 1 <= len(words) <= 4 and all(part[:1].isupper() for part in words if part[:1].isalpha())
    return False


def reduce_email_noise(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""

    first_header_index = next((idx for idx, line in enumerate(lines[:12]) if EMAIL_HEADER_RE.match(line)), None)
    if first_header_index is not None and first_header_index > 0:
        lines = lines[first_header_index:]

    result: list[str] = []
    skip_signature = False
    for idx, line in enumerate(lines):
        lowered = line.lower()
        next_line = lines[idx + 1] if idx + 1 < len(lines) else None

        if EMAIL_HEADER_RE.match(line):
            skip_signature = False
            continue
        if any(marker in lowered for marker in SIGNATURE_MARKERS):
            skip_signature = True
            continue
        if skip_signature:
            continue
        if EMAIL_CONTACT_RE.search(line):
            continue
        if lowered in SIGNATURE_ROLE_LINES:
            continue
        if is_likely_signature_name(line, next_line):
            continue

        result.append(line)

    compacted = "\n".join(result)
    compacted = re.sub(r"\n{3,}", "\n\n", compacted)
    return compacted.strip()


def clip(value: Any, length: int) -> str | None:
    return as_text(value, length)


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
    normalized = (as_text(value) or "").strip().lower()
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
    requested_kind = (as_text(payload.target_kind) or "").strip().lower()
    requested_area = normalize_area(payload.target_area)
    mailbox = (as_text(payload.source_mailbox) or "").lower()

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
    if "hub" in mailbox or "operacional" in mailbox:
        return "quick_record", "operational", "E-mail recebido na caixa operacional."
    return "quick_record", "operational", "E-mail recebido sem regra específica."


def existing_intake(db: DbSession, payload: EmailIntakePayload) -> EmailIntake | None:
    conditions = []
    external_message_id = clip(payload.external_message_id, 255)
    list_item_id = clip(payload.list_item_id, 255)
    email_url = as_text(payload.email_url, 2000, prefer_url=True)
    if external_message_id:
        conditions.append(EmailIntake.external_message_id == external_message_id)
    if list_item_id:
        conditions.append(EmailIntake.list_item_id == list_item_id)
    if email_url:
        conditions.append(EmailIntake.email_url == email_url)
    if not conditions:
        return None
    return db.scalar(select(EmailIntake).where(or_(*conditions)).order_by(EmailIntake.id.desc()))


def source_link(payload: EmailIntakePayload) -> str | None:
    attachments = normalize_attachments(payload.attachments)
    return (
        as_text(payload.attachments_url, 2000, prefer_url=True)
        or as_text(payload.email_url, 2000, prefer_url=True)
        or as_text(payload.list_item_url, 2000, prefer_url=True)
        or (attachments[0]["url"] if attachments else None)
    )


def create_quick_record(db: DbSession, intake: EmailIntake, payload: EmailIntakePayload, workspace: str) -> QuickRecord:
    clean_workspace = workspace if workspace in {"operational", "workshop", "management", "administration"} else "operational"
    record_type = "technical_request" if clean_workspace == "workshop" else "information"
    mailbox = clip(payload.source_mailbox, 255) or "desconhecida"
    sender = clip(payload.sender, 255)
    email_url = as_text(payload.email_url, 2000, prefer_url=True)
    attachments_url = as_text(payload.attachments_url, 2000, prefer_url=True) or as_text(payload.list_item_url, 2000, prefer_url=True)
    description_parts = [
        clean_html_preview(payload.body_preview, 4000),
        f"Remetente: {sender}" if sender else None,
        f"Caixa de entrada: {mailbox}",
        f"Link do e-mail: {email_url}" if email_url else None,
        f"Link de anexos/lista: {attachments_url}" if attachments_url else None,
    ]
    record = QuickRecord(
        workspace=clean_workspace,
        record_type=record_type,
        title=clip(payload.subject, 200) or "Entrada recebida por e-mail",
        description="\n".join(part for part in description_parts if part),
        status="new",
        priority="normal",
        source="email",
        customer_email=sender,
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
    document = DocumentManagementFacade(db).ingest_link(
        LinkIngestionRequest(
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
            storage_provider="sharepoint",
            storage_path=link,
            storage_key=clip(payload.email_url, 2000),
            external_url=link,
            folder_path=suggest_folder_path(area, document_date, document_type),
            document_date=document_date,
            uploaded_by_id=None,
        ),
        source_reference=SourceReference(
            module="service_desk",
            entity_type="email_intake",
            entity_id=str(intake.id),
            display_snapshot=title,
        ),
        event_action="created_from_email",
        event_detail=f"Entrada de e-mail #{intake.id}. Pasta sugerida: {suggest_folder_path(area, document_date, document_type)}",
    )
    preview = clean_html_preview(payload.body_preview, 4000)
    if preview:
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="source_preview",
                old_value=None,
                new_value=preview,
                user_id=None,
            )
        )
    return document


def create_email_attachments(
    db: DbSession,
    intake: EmailIntake,
    payload: EmailIntakePayload,
    document: Document | None = None,
) -> list[EmailIntakeAttachment]:
    created: list[EmailIntakeAttachment] = []
    for item in normalize_attachments(payload.attachments):
        attachment = EmailIntakeAttachment(
            email_intake_id=intake.id,
            document_id=document.id if document else None,
            name=item["name"],
            url=item["url"],
            content_type=item.get("content_type"),
            size=item.get("size"),
            status="pending",
        )
        db.add(attachment)
        created.append(attachment)
    if document and created:
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="attachments.received",
                old_value=None,
                new_value=f"{len(created)} anexos recebidos para tratamento.",
                user_id=None,
            )
        )
    return created


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
    mailbox = clip(payload.source_mailbox, 255) or "desconhecida"
    preview = clean_html_preview(payload.body_preview, 4000)
    intake = EmailIntake(
        source_mailbox=mailbox.lower(),
        sender=clip(payload.sender, 255),
        subject=clip(payload.subject, 255),
        body_preview=preview,
        received_at=payload.received_at,
        email_url=as_text(payload.email_url, 2000, prefer_url=True),
        attachments_url=as_text(payload.attachments_url, 2000, prefer_url=True),
        list_item_id=clip(payload.list_item_id, 255),
        list_item_url=as_text(payload.list_item_url, 2000, prefer_url=True),
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
            create_email_attachments(db, intake, payload, target)
            intake.target_entity_type = "document"
            intake.target_entity_id = str(target.id)
            intake.target_url = f"/documents/{target.id}"
        else:
            target = create_quick_record(db, intake, payload, target_area)
            create_email_attachments(db, intake, payload)
            intake.target_entity_type = "quick_record"
            intake.target_entity_id = str(target.id)
            intake.target_url = f"/task-board/quick/{target.id}"
        intake.status = "created_in_app"
        record_audit(
            db,
            action="integration.email_intake.created",
            entity_type=intake.target_entity_type,
            entity_id=intake.target_entity_id,
            detail=f"E-mail recebido de {mailbox} criado na app.",
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
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    return {
        "status": intake.status,
        "intake_id": intake.id,
        "target_type": intake.target_entity_type,
        "target_id": intake.target_entity_id,
        "target_url": intake.target_url,
        "routing_note": intake.routing_note,
    }
