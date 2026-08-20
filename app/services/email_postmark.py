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

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email import (
    EmailAttachment,
    EmailAuditEvent,
    EmailChannel,
    EmailInboxRule,
    EmailMessage,
    EmailThread,
    EmailWebhookEvent,
)
from app.models.tasks import Task, TaskEmailOrigin
from app.models.work_hierarchy import WorkQueue
from app.services.bootstrap import (
    POSTMARK_INBOUND_DOMAIN,
    POSTMARK_INBOUND_LOCAL_PART,
    seed_email_channels,
)
from app.services.service_desk import (
    initialize_email_operations,
    initialize_task_service_desk,
    mark_task_resolved,
    transition_email_waiting,
)


def ensure_email_channels(db: Session) -> None:
    seed_email_channels(db)
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
    recipients = payload.get("ToFull") or []
    # Postmark exposes plus-addressing first as the top-level MailboxHash and
    # also on ToFull recipients.  Keep that precedence deterministic: a
    # forwarded/original recipient must not override the stream-level hash.
    mailbox_hashes: list[str] = []
    for value in [
        payload.get("MailboxHash"),
        *(
            item.get("MailboxHash")
            for item in recipients
            if isinstance(item, dict)
        ),
    ]:
        mailbox_hash = str(value or "").strip().casefold()
        if mailbox_hash and mailbox_hash not in mailbox_hashes:
            mailbox_hashes.append(mailbox_hash)
    for mailbox_hash in mailbox_hashes:
        channel = db.scalar(
            select(EmailChannel).where(func.lower(EmailChannel.inbound_hash) == mailbox_hash)
        )
        if channel:
            return channel
    addresses = {_address(item.get("Email")) for item in recipients if isinstance(item, dict)}
    for value in (payload.get("OriginalRecipient"), payload.get("To")):
        for part in re.split(r"[,;]", str(value or "")):
            address = _address(part)
            if address:
                addresses.add(address)
    headers = _headers(payload)
    for header in ("x-original-to", "delivered-to", "x-forwarded-to", "envelope-to"):
        for part in re.split(r"[,;]", headers.get(header, "")):
            address = _address(part)
            if address:
                addresses.add(address)
    channel = None
    if addresses:
        channel = db.scalar(
            select(EmailChannel).where(
                (EmailChannel.address.in_(addresses))
                | (EmailChannel.inbound_forward_address.in_(addresses))
            )
        )
    if not channel:
        channels = list(db.scalars(select(EmailChannel).where(EmailChannel.active.is_(True))))
        for address in addresses:
            local_part, _, domain = address.casefold().partition("@")
            channel = next(
                (
                    item
                    for item in channels
                    if (
                        item.inbound_hash
                        and domain == POSTMARK_INBOUND_DOMAIN
                        and local_part
                        == f"{POSTMARK_INBOUND_LOCAL_PART}+{item.inbound_hash}".casefold()
                    )
                    or local_part == f"intake+{item.code}".casefold()
                    or local_part.startswith(f"intake+{item.code}+")
                ),
                None,
            )
            if channel:
                break
    # Preserve messages historically forwarded to the stream's bare inbound address.
    if not channel and (
        f"{POSTMARK_INBOUND_LOCAL_PART}@{POSTMARK_INBOUND_DOMAIN}" in addresses
        or "hub@carfast.pt" in addresses
    ):
        channel = db.scalar(select(EmailChannel).where(EmailChannel.code == "test"))
    if channel:
        return channel
    raise ValueError("Inbound payload does not identify a configured email channel.")


def _storage_root() -> Path:
    root = Path(settings.email_storage_root or "var/email")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _inbox_rule(db: Session, channel_id: int, subject: str) -> EmailInboxRule | None:
    normalized = subject.strip().casefold()
    rules = db.scalars(
        select(EmailInboxRule)
        .where(
            EmailInboxRule.channel_id == channel_id,
            EmailInboxRule.active.is_(True),
        )
        .order_by(EmailInboxRule.sort_order, EmailInboxRule.id)
    ).all()
    for rule in rules:
        expected = rule.subject_match.strip().casefold()
        if expected and (
            (rule.match_type == "exact" and normalized == expected)
            or (rule.match_type == "contains" and expected in normalized)
        ):
            return rule
    return None


def ingest_inbound(db: Session, payload: dict) -> tuple[EmailThread, bool]:
    key = _event_key(payload)
    existing_event = db.scalar(select(EmailWebhookEvent).where(EmailWebhookEvent.event_key == key))
    if existing_event:
        message_id = payload.get("MessageID") or payload.get("MessageId")
        message = db.scalar(
            select(EmailMessage).where(EmailMessage.external_message_id == message_id)
        )
        return db.get(EmailThread, message.thread_id), False

    channel = _channel_for_payload(db, payload)
    event = EmailWebhookEvent(event_key=key, event_type="inbound", payload_json=payload)
    db.add(event)
    db.flush()
    external_id = str(payload.get("MessageID") or payload.get("MessageId") or key)
    subject = str(payload.get("Subject") or "(sem assunto)")[:500]
    rule = _inbox_rule(db, channel.id, subject)
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
            work_queue_id=(
                rule.default_queue_id
                if rule and rule.default_queue_id
                else channel.default_queue_id
            ),
            work_department_id=(
                rule.default_department_id
                if rule and rule.default_department_id
                else channel.default_department_id
            ),
            work_category_id=(
                rule.default_category_id
                if rule and rule.default_category_id
                else channel.default_category_id
            ),
            work_subcategory_id=(
                rule.default_subcategory_id
                if rule and rule.default_subcategory_id
                else channel.default_subcategory_id
            ),
            classification_status=(
                "classified"
                if (
                    rule.default_queue_id
                    if rule and rule.default_queue_id
                    else channel.default_queue_id
                )
                and (
                    rule.default_department_id
                    if rule and rule.default_department_id
                    else channel.default_department_id
                )
                else "unclassified"
            ),
            document_type=(
                rule.default_document_type
                if rule and rule.default_document_type
                else channel.default_document_type
            ),
            waiting_until=(
                now
                + timedelta(
                    days=rule.default_wait_days
                    if rule and rule.default_wait_days is not None
                    else channel.default_wait_days
                )
                if (
                    rule.default_wait_days
                    if rule and rule.default_wait_days is not None
                    else channel.default_wait_days
                )
                is not None
                else None
            ),
            last_message_at=now,
        )
        initialize_email_operations(db, thread, channel=channel, rule=rule, now=now)
        db.add(thread)
        db.flush()
    elif thread.status in {"waiting_reply", "resolved", "archived"}:
        transition_email_waiting(
            db,
            thread,
            waiting=False,
            user_id=None,
            reason="Nova mensagem recebida",
        )
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
    auto_task_mode = rule.auto_task_mode if rule and rule.auto_task_mode else channel.auto_task_mode
    if created_thread and auto_task_mode in {"open", "complete"}:
        queue = db.get(WorkQueue, thread.work_queue_id) if thread.work_queue_id else None
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
            status="closed" if auto_task_mode == "complete" else "new",
            priority="normal",
            customer_email=sender,
            due_on=thread.resolution_due_at.date() if thread.resolution_due_at else None,
            work_queue_id=thread.work_queue_id,
            work_department_id=thread.work_department_id,
            work_category_id=thread.work_category_id,
            work_subcategory_id=thread.work_subcategory_id,
            classification_status=thread.classification_status,
            resolved_at=now if auto_task_mode == "complete" else None,
            closed_at=now if auto_task_mode == "complete" else None,
        )
        db.add(task)
        db.flush()
        initialize_task_service_desk(db, task, now=now)
        if auto_task_mode == "complete":
            mark_task_resolved(db, task, actor_user_id=None, now=now)
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
        thread.status = "resolved" if auto_task_mode == "complete" else "task_created"
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                action="task_created_automatically",
                details_json={"task_id": task.id, "mode": auto_task_mode},
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
