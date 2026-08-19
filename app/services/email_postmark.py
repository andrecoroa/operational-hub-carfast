from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email import (
    EmailAttachment,
    EmailAuditEvent,
    EmailChannel,
    EmailMessage,
    EmailThread,
    EmailWebhookEvent,
)
from app.models.tasks import Task, TaskEmailOrigin
from app.models.work_hierarchy import WorkQueue


def ensure_email_channels(db: Session) -> None:
    address = settings.email_initial_address.strip().lower()
    existing = db.scalar(select(EmailChannel).where(EmailChannel.code == "test"))
    if not existing:
        db.add(EmailChannel(code="test", name="Caixa de teste", address=address))
    elif existing.address != address:
        existing.address = address
    db.flush()


def webhook_authorized(authorization: str | None) -> bool:
    user = settings.postmark_inbound_basic_user or ""
    password = settings.postmark_inbound_basic_password or ""
    if not user or not password or not authorization or not authorization.startswith("Basic "):
        return False
    try:
        supplied = base64.b64decode(authorization[6:]).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(supplied, f"{user}:{password}")


def _address(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"<([^>]+)>", value)
    return (match.group(1) if match else value).strip().lower()


def _event_key(payload: dict) -> str:
    message_id = payload.get("MessageID") or payload.get("MessageId")
    if message_id:
        return f"message:{message_id}"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _headers(payload: dict) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("Headers") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or "").strip().lower()
        value = str(item.get("Value") or "").strip()
        if name and value:
            result[name] = value
    return result


def _message_ids(value: str | None) -> list[str]:
    if not value:
        return []
    bracketed = re.findall(r"<([^>]+)>", value)
    if bracketed:
        return [item.strip() for item in bracketed if item.strip()]
    return [item.strip().strip("<>") for item in value.split() if item.strip()]


def _channel_for_payload(db: Session, payload: dict) -> EmailChannel:
    ensure_email_channels(db)
    mailbox_hash = str(payload.get("MailboxHash") or "").strip()
    if mailbox_hash:
        channel = db.scalar(select(EmailChannel).where(EmailChannel.inbound_hash == mailbox_hash))
        if channel:
            return channel
    recipients = payload.get("ToFull") or []
    addresses = {_address(item.get("Email")) for item in recipients if isinstance(item, dict)}
    to_value = _address(payload.get("OriginalRecipient") or payload.get("To"))
    if to_value:
        addresses.add(to_value)
    channel = (
        db.scalar(select(EmailChannel).where(EmailChannel.address.in_(addresses)))
        if addresses
        else None
    )
    return channel or db.scalar(select(EmailChannel).where(EmailChannel.code == "test"))


def _storage_root() -> Path:
    root = Path(settings.email_storage_root or "var/email")
    root.mkdir(parents=True, exist_ok=True)
    return root


def ingest_inbound(db: Session, payload: dict) -> tuple[EmailThread, bool]:
    key = _event_key(payload)
    existing_event = db.scalar(select(EmailWebhookEvent).where(EmailWebhookEvent.event_key == key))
    if existing_event:
        message_id = payload.get("MessageID") or payload.get("MessageId")
        message = db.scalar(
            select(EmailMessage).where(EmailMessage.external_message_id == message_id)
        )
        return db.get(EmailThread, message.thread_id), False

    event = EmailWebhookEvent(event_key=key, event_type="inbound", payload_json=payload)
    db.add(event)
    db.flush()
    channel = _channel_for_payload(db, payload)
    external_id = str(payload.get("MessageID") or payload.get("MessageId") or key)
    subject = str(payload.get("Subject") or "(sem assunto)")[:500]
    sender = _address(payload.get("From"))
    headers = _headers(payload)
    conversation_id = str(payload.get("OriginalMessageID") or "").strip() or None
    thread = None
    if conversation_id:
        thread = db.scalar(
            select(EmailThread).where(EmailThread.external_conversation_id == conversation_id)
        )
    reply_ids = _message_ids(headers.get("in-reply-to"))
    reply_ids.extend(_message_ids(headers.get("references")))
    if not thread and reply_ids:
        parent = db.scalar(
            select(EmailMessage)
            .where(EmailMessage.external_message_id.in_(reply_ids))
            .order_by(EmailMessage.id.desc())
        )
        if parent:
            thread = db.get(EmailThread, parent.thread_id)
    created_thread = thread is None
    if not thread:
        now = datetime.now(UTC)
        thread = EmailThread(
            channel_id=channel.id,
            subject=subject,
            status="triage",
            sender_email=sender,
            sender_name=payload.get("FromName"),
            external_conversation_id=conversation_id or external_id,
            work_queue_id=channel.default_queue_id,
            work_department_id=channel.default_department_id,
            work_category_id=channel.default_category_id,
            work_subcategory_id=channel.default_subcategory_id,
            classification_status=(
                "classified"
                if channel.default_queue_id and channel.default_department_id
                else "unclassified"
            ),
            document_type=channel.default_document_type,
            assigned_to_id=channel.default_assignee_id,
            due_at=(
                now + timedelta(days=channel.default_due_days)
                if channel.default_due_days is not None
                else None
            ),
            waiting_until=(
                now + timedelta(days=channel.default_wait_days)
                if channel.default_wait_days is not None
                else None
            ),
            last_message_at=now,
        )
        db.add(thread)
        db.flush()
    elif thread.status in {"resolved", "archived"}:
        thread.status = "new_reply"

    message = EmailMessage(
        thread_id=thread.id,
        external_message_id=external_id,
        direction="inbound",
        state="received",
        sender=sender,
        recipients_json=payload.get("ToFull") or [],
        cc_json=payload.get("CcFull") or [],
        subject=subject,
        text_body=payload.get("TextBody"),
        html_body=payload.get("HtmlBody"),
        headers_json=payload.get("Headers") or [],
        received_at=datetime.now(UTC),
    )
    db.add(message)
    db.flush()
    for item in payload.get("Attachments") or []:
        content = base64.b64decode(item.get("Content") or "")
        if len(content) > settings.email_max_attachment_bytes:
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", item.get("Name") or "attachment")
        digest = hashlib.sha256(content).hexdigest()
        folder = _storage_root() / str(thread.id) / str(message.id)
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / safe_name
        path.write_bytes(content)
        db.add(
            EmailAttachment(
                message_id=message.id,
                file_name=safe_name,
                content_type=item.get("ContentType"),
                content_id=item.get("ContentID"),
                size=len(content),
                storage_path=str(path),
                sha256=digest,
            )
        )
    thread.last_message_at = message.received_at
    if created_thread and channel.auto_task_mode in {"open", "complete"}:
        queue = db.get(WorkQueue, channel.default_queue_id) if channel.default_queue_id else None
        now = datetime.now(UTC)
        task = Task(
            title=subject[:200],
            description=f"Criada automaticamente a partir do email recebido de {sender}.",
            task_type=(
                "administration_task"
                if queue and queue.code == "administration"
                else "operational_task"
            ),
            source="email",
            status="closed" if channel.auto_task_mode == "complete" else "new",
            priority="normal",
            customer_email=sender,
            assigned_to_id=channel.default_assignee_id,
            due_on=thread.due_at.date() if thread.due_at else None,
            work_queue_id=thread.work_queue_id,
            work_department_id=thread.work_department_id,
            work_category_id=thread.work_category_id,
            work_subcategory_id=thread.work_subcategory_id,
            classification_status=thread.classification_status,
            resolved_at=now if channel.auto_task_mode == "complete" else None,
            closed_at=now if channel.auto_task_mode == "complete" else None,
        )
        db.add(task)
        db.flush()
        db.add(
            TaskEmailOrigin(
                task_id=task.id,
                message_id=external_id,
                sender=sender,
                recipients_json=payload.get("ToFull") or [],
                subject=subject,
                received_at=message.received_at,
                mailbox=channel.address,
                source_url=f"/v2-clean/email/{thread.id}",
                rule_code=f"email_channel:{channel.code}:{channel.auto_task_mode}",
            )
        )
        thread.task_id = task.id
        thread.status = "resolved" if channel.auto_task_mode == "complete" else "task_created"
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                action="task_created_automatically",
                details_json={"task_id": task.id, "mode": channel.auto_task_mode},
            )
        )
    event.processed = True
    db.add(EmailAuditEvent(thread_id=thread.id, message_id=message.id, action="inbound_received"))
    db.commit()
    return thread, True


def send_message(
    message: EmailMessage,
    from_address: str,
    *,
    reply_to: str | None = None,
    parent_message_id: str | None = None,
    references: list[str] | None = None,
) -> dict:
    if not settings.email_outbound_enabled:
        raise RuntimeError("O envio externo está desligado neste ambiente.")
    if not settings.postmark_server_token:
        raise RuntimeError("POSTMARK_SERVER_TOKEN não está configurado.")
    recipients = [
        item.get("Email") if isinstance(item, dict) else str(item)
        for item in (message.recipients_json or [])
    ]
    body = {
        "From": from_address,
        "To": ",".join(filter(None, recipients)),
        "Subject": message.subject,
        "TextBody": message.text_body or "",
        "HtmlBody": message.html_body or None,
        "MessageStream": settings.postmark_message_stream,
        "Metadata": {
            "carfast_thread_id": str(message.thread_id),
            "carfast_message_id": str(message.id),
        },
    }
    if reply_to:
        body["ReplyTo"] = reply_to
    outbound_headers = []
    if parent_message_id:
        outbound_headers.append({"Name": "In-Reply-To", "Value": f"<{parent_message_id}>"})
    reference_ids = [item for item in (references or []) if item]
    if parent_message_id and parent_message_id not in reference_ids:
        reference_ids.append(parent_message_id)
    if reference_ids:
        body["Headers"] = outbound_headers + [
            {
                "Name": "References",
                "Value": " ".join(f"<{item}>" for item in reference_ids),
            }
        ]
    elif outbound_headers:
        body["Headers"] = outbound_headers
    request = urllib.request.Request(
        "https://api.postmarkapp.com/email",
        data=json.dumps(body).encode(),
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": settings.postmark_server_token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Postmark devolveu HTTP {exc.code}.") from exc
