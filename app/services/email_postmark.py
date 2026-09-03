from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.service_desk import EmailOriginCommand, ServiceDeskFacade
from app.models.email import (
    EmailAttachment,
    EmailAuditEvent,
    EmailChannel,
    EmailChannelAlias,
    EmailInboxRule,
    EmailMessage,
    EmailMessageDelivery,
    EmailThread,
    EmailWebhookEvent,
)
from app.models.tasks import Task
from app.models.work_hierarchy import WorkQueue
from app.services.bootstrap import (
    POSTMARK_INBOUND_DOMAIN,
    POSTMARK_INBOUND_LOCAL_PART,
    seed_email_channels,
)
from app.services.service_desk import (
    initialize_email_operations,
    mark_task_resolved,
    transition_email_waiting,
)

_EMAIL_ADDRESS_RE = re.compile(r"^[^\s<>@]+@[^\s<>@]+\.[^\s<>@]+$")


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


def outbound_identity(
    display_name: str | None,
    from_address: str | None,
    reply_to: str | None,
) -> tuple[str, str]:
    """Build the outbound identity configured for a functional mailbox."""
    name = str(display_name or "").strip()
    if not name or len(name) > 160 or any(ord(char) < 32 or ord(char) == 127 for char in name):
        raise ValueError("O nome visível do remetente não é válido.")
    safe_name = name.replace("\\", "\\\\").replace('"', '\\"')
    sender = _address(from_address)
    candidate = _address(reply_to)
    if not _EMAIL_ADDRESS_RE.fullmatch(sender):
        raise ValueError("O endereço do remetente não é válido.")
    if not _EMAIL_ADDRESS_RE.fullmatch(candidate):
        raise ValueError("O Reply-To não é válido.")
    return f'"{safe_name}" <{sender}>', candidate


def _event_key(payload: dict) -> str:
    message_id = payload.get("MessageID") or payload.get("MessageId")
    if message_id:
        return f"message:{message_id}"
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _outbound_event_key(payload: dict) -> str:
    event_type = str(payload.get("RecordType") or "unknown").strip().casefold()
    message_id = str(payload.get("MessageID") or payload.get("MessageId") or "").strip()
    discriminator = str(
        payload.get("ID")
        or payload.get("DeliveredAt")
        or payload.get("BouncedAt")
        or payload.get("ReportedAt")
        or payload.get("ReceivedAt")
        or ""
    ).strip()
    canonical = f"{event_type}\0{message_id}\0{discriminator}"
    if not message_id or not discriminator:
        safe = {
            key: payload.get(key)
            for key in (
                "RecordType", "MessageID", "MessageId", "ID", "Type", "TypeCode",
                "Inactive", "CanActivate", "DeliveredAt", "BouncedAt", "ReportedAt",
                "ReceivedAt",
            )
        }
        canonical = json.dumps(safe, sort_keys=True, separators=(",", ":"), default=str)
    return "outbound:" + hashlib.sha256(canonical.encode()).hexdigest()


def _sanitized_outbound_payload(payload: dict) -> dict:
    """Keep operational evidence only; never persist recipients or message content."""
    return {
        key: payload.get(key)
        for key in (
            "RecordType", "MessageID", "MessageId", "ID", "Type", "TypeCode",
            "Inactive", "CanActivate", "DeliveredAt", "BouncedAt", "ReportedAt",
            "ReceivedAt",
        )
        if payload.get(key) is not None
    }


def ingest_outbound_event(db: Session, payload: dict) -> tuple[str, bool]:
    event_type = str(payload.get("RecordType") or "").strip()
    normalized_type = event_type.casefold().replace(" ", "")
    supported = {"delivery", "bounce", "spamcomplaint"}
    key = _outbound_event_key(payload)
    event = db.scalar(select(EmailWebhookEvent).where(EmailWebhookEvent.event_key == key))
    if event and event.processed:
        return "duplicate", False
    if not event:
        event = EmailWebhookEvent(
            event_key=key,
            event_type=normalized_type or "unknown",
            payload_json=_sanitized_outbound_payload(payload),
        )
        db.add(event)
        db.flush()
    if normalized_type not in supported:
        event.error = "unsupported_event"
        db.commit()
        return "unsupported", False

    external_id = str(payload.get("MessageID") or payload.get("MessageId") or "").strip()
    message = db.scalar(
        select(EmailMessage).where(EmailMessage.external_message_id == external_id)
    ) if external_id else None
    if not message or message.direction != "outbound":
        event.error = "unmatched_message"
        db.commit()
        return "unmatched", False

    thread = db.get(EmailThread, message.thread_id)
    if not thread:
        event.error = "unmatched_thread"
        db.commit()
        return "unmatched", False

    if normalized_type == "delivery":
        target_state = "delivered"
    elif normalized_type == "spamcomplaint":
        target_state = "spam_complaint"
    else:
        inactive = payload.get("Inactive") is True or str(
            payload.get("Inactive") or ""
        ).casefold() in {"true", "1"}
        hard = inactive or str(payload.get("Type") or "").casefold() in {
            "hardbounce", "spamcomplaint", "manualdeactivation",
        } or payload.get("TypeCode") == 1
        target_state = "bounced" if hard else "soft_bounced"

    precedence = {
        "draft": 0, "pending_approval": 0, "approved": 1, "sent": 2,
        "soft_bounced": 3, "delivered": 4, "bounced": 5, "spam_complaint": 6,
    }
    if precedence.get(target_state, 0) >= precedence.get(message.state, 0):
        message.state = target_state
    event.processed = True
    event.error = None
    db.add(
        EmailMessageDelivery(
            message_id=message.id,
            channel_id=thread.channel_id,
            webhook_event_id=event.id,
            logical_key=key,
            canonical_marker=normalized_type[:20],
            postmark_message_id=external_id,
            received_at=datetime.now(UTC),
        )
    )
    db.add(
        EmailAuditEvent(
            thread_id=thread.id,
            message_id=message.id,
            action=f"postmark_{normalized_type}",
            details_json={
                "webhook_event_id": event.id,
                "resulting_state": message.state,
            },
        )
    )
    db.commit()
    return message.state, True


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


def _normalized_header_date(payload: dict, headers: dict[str, str]) -> str:
    value = str(headers.get("date") or payload.get("Date") or "").strip()
    if not value:
        return ""
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return re.sub(r"\s+", " ", value).casefold()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat()


def _logical_message_key(payload: dict) -> str:
    headers = _headers(payload)
    rfc_message_ids = _message_ids(headers.get("message-id"))
    if rfc_message_ids:
        normalized = rfc_message_ids[0].strip().casefold()
        return "rfc:" + hashlib.sha256(normalized.encode()).hexdigest()

    normalized_date = _normalized_header_date(payload, headers)
    attachment_fingerprints = []
    for item in payload.get("Attachments") or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("Content") or "")
        attachment_fingerprints.append(
            {
                "name": str(item.get("Name") or "").strip().casefold(),
                "type": str(item.get("ContentType") or "").strip().casefold(),
                "content": hashlib.sha256(content.encode()).hexdigest(),
            }
        )
    canonical = {
        "sender": _address(payload.get("From")),
        "sender_name": str(payload.get("FromName") or "").strip().casefold(),
        "subject": re.sub(r"\s+", " ", str(payload.get("Subject") or ""))
        .strip()
        .casefold(),
        "date": normalized_date,
        "text": hashlib.sha256(str(payload.get("TextBody") or "").encode()).hexdigest(),
        "html": hashlib.sha256(str(payload.get("HtmlBody") or "").encode()).hexdigest(),
        "attachments": sorted(
            attachment_fingerprints,
            key=lambda item: (item["name"], item["type"], item["content"]),
        ),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return "fallback:" + hashlib.sha256(encoded.encode()).hexdigest()


def _recipient_email(item: object) -> str:
    if isinstance(item, dict):
        return _address(str(item.get("Email") or ""))
    return _address(str(item or ""))


def _merge_recipients(*groups: list | None) -> list:
    merged: list = []
    seen: set[str] = set()
    for group in groups:
        for item in group or []:
            address = _recipient_email(item)
            if not address or address in seen:
                continue
            seen.add(address)
            merged.append(item if isinstance(item, dict) else {"Email": address})
    return merged


def _delivery_inbound_address(payload: dict) -> str:
    mailbox_hash = str(payload.get("MailboxHash") or "").strip().casefold()
    if mailbox_hash:
        return f"{POSTMARK_INBOUND_LOCAL_PART}+{mailbox_hash}@{POSTMARK_INBOUND_DOMAIN}"
    headers = _headers(payload)
    return str(
        headers.get("delivered-to")
        or headers.get("x-forwarded-to")
        or headers.get("envelope-to")
        or ""
    ).strip()


def _new_delivery(
    *,
    message: EmailMessage,
    channel: EmailChannel,
    event: EmailWebhookEvent,
    payload: dict,
    logical_key: str,
    canonical: bool,
    alias: EmailChannelAlias | None = None,
) -> EmailMessageDelivery:
    original_recipient = (
        str(payload.get("OriginalRecipient") or "").strip()
        or (alias.address if alias else None)
    )
    technical_recipient = (
        alias.inbound_forward_address if alias else None
    ) or _delivery_inbound_address(payload) or None
    return EmailMessageDelivery(
        message_id=message.id,
        channel_id=channel.id,
        webhook_event_id=event.id,
        logical_key=logical_key,
        canonical_marker="canonical" if canonical else None,
        postmark_message_id=str(
            payload.get("MessageID") or payload.get("MessageId") or ""
        )
        or None,
        original_recipient=original_recipient,
        technical_recipient=technical_recipient,
        inbound_address=(alias.address if alias else None)
        or _delivery_inbound_address(payload)
        or None,
        mailbox_hash=str(payload.get("MailboxHash") or "").strip() or None,
        to_json=payload.get("ToFull") or [],
        cc_json=payload.get("CcFull") or [],
        received_at=datetime.now(UTC),
    )


def reply_all_recipients(
    db: Session,
    source_message: EmailMessage,
    from_address: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    channels = list(db.scalars(select(EmailChannel)))
    internal_addresses = {_address(from_address)}
    for channel in channels:
        internal_addresses.add(_address(channel.address))
        internal_addresses.add(_address(channel.default_reply_address))
        internal_addresses.add(_address(channel.inbound_forward_address))
        if channel.inbound_hash:
            internal_addresses.add(
                f"{POSTMARK_INBOUND_LOCAL_PART}+{channel.inbound_hash.casefold()}"
                f"@{POSTMARK_INBOUND_DOMAIN}"
            )
    aliases = list(db.scalars(select(EmailChannelAlias)))
    for alias in aliases:
        internal_addresses.add(_address(alias.address))
        internal_addresses.add(_address(alias.inbound_forward_address))
    internal_addresses.discard("")

    def external(address: str) -> bool:
        domain = address.rpartition("@")[2]
        return bool(address) and address not in internal_addresses and domain not in {
            "carfast.pt",
            "carfast.local",
        }

    sender = _address(source_message.sender)
    to_rows = [{"Email": sender}] if external(sender) else []
    seen = {sender, *internal_addresses}
    cc_rows: list[dict[str, str]] = []
    for item in [
        *(source_message.recipients_json or []),
        *(source_message.cc_json or []),
    ]:
        address = _recipient_email(item)
        if not external(address) or address in seen:
            continue
        seen.add(address)
        row = {"Email": address}
        if isinstance(item, dict) and item.get("Name"):
            row["Name"] = str(item["Name"])
        cc_rows.append(row)
    return to_rows, cc_rows


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
        alias = db.scalar(
            select(EmailChannelAlias)
            .join(EmailChannel, EmailChannel.id == EmailChannelAlias.channel_id)
            .where(
                EmailChannelAlias.active.is_(True),
                EmailChannel.active.is_(True),
                func.lower(EmailChannelAlias.inbound_hash) == mailbox_hash,
            )
        )
        if alias:
            return db.get(EmailChannel, alias.channel_id)
        channel = db.scalar(
            select(EmailChannel).where(
                EmailChannel.active.is_(True),
                func.lower(EmailChannel.inbound_hash) == mailbox_hash,
            )
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
        alias = db.scalar(
            select(EmailChannelAlias)
            .join(EmailChannel, EmailChannel.id == EmailChannelAlias.channel_id)
            .where(
                EmailChannelAlias.active.is_(True),
                EmailChannel.active.is_(True),
                or_(
                    func.lower(EmailChannelAlias.address).in_(addresses),
                    func.lower(EmailChannelAlias.inbound_forward_address).in_(addresses),
                ),
            )
        )
        if alias:
            return db.get(EmailChannel, alias.channel_id)
        channel = db.scalar(
            select(EmailChannel).where(
                EmailChannel.active.is_(True),
                or_(
                    func.lower(EmailChannel.address).in_(addresses),
                    func.lower(EmailChannel.inbound_forward_address).in_(addresses),
                ),
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
        channel = db.scalar(
            select(EmailChannel).where(
                EmailChannel.code == "test", EmailChannel.active.is_(True)
            )
        )
    if channel:
        return channel
    raise ValueError("Inbound payload does not identify a configured email channel.")


def _alias_for_payload(
    db: Session, payload: dict, channel_id: int
) -> EmailChannelAlias | None:
    hashes = {
        str(value or "").strip().casefold()
        for value in [
            payload.get("MailboxHash"),
            *(
                item.get("MailboxHash")
                for item in (payload.get("ToFull") or [])
                if isinstance(item, dict)
            ),
        ]
        if str(value or "").strip()
    }
    addresses = {
        _address(item.get("Email"))
        for field in ("ToFull", "CcFull")
        for item in (payload.get(field) or [])
        if isinstance(item, dict)
    }
    for value in (payload.get("OriginalRecipient"), payload.get("To")):
        addresses.update(
            address
            for address in (_address(part) for part in re.split(r"[,;]", str(value or "")))
            if address
        )
    return db.scalar(
        select(EmailChannelAlias).where(
            EmailChannelAlias.channel_id == channel_id,
            EmailChannelAlias.active.is_(True),
            or_(
                func.lower(EmailChannelAlias.address).in_(addresses),
                func.lower(EmailChannelAlias.inbound_forward_address).in_(addresses),
                func.lower(EmailChannelAlias.inbound_hash).in_(hashes),
            ),
        )
    )


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
        delivery = db.scalar(
            select(EmailMessageDelivery).where(
                EmailMessageDelivery.webhook_event_id == existing_event.id
            )
        )
        message = db.get(EmailMessage, delivery.message_id) if delivery else None
        if not message:
            message_id = payload.get("MessageID") or payload.get("MessageId")
            message = db.scalar(
                select(EmailMessage).where(EmailMessage.external_message_id == message_id)
            )
        if message:
            return db.get(EmailThread, message.thread_id), False
        raise ValueError("Inbound event already exists without a linked email message.")

    channel = _channel_for_payload(db, payload)
    channel_alias = _alias_for_payload(db, payload, channel.id)
    event = EmailWebhookEvent(event_key=key, event_type="inbound", payload_json=payload)
    db.add(event)
    db.flush()
    logical_key = _logical_message_key(payload)
    canonical_delivery = db.scalar(
        select(EmailMessageDelivery)
        .where(
            EmailMessageDelivery.channel_id == channel.id,
            EmailMessageDelivery.logical_key == logical_key,
            EmailMessageDelivery.canonical_marker == "canonical",
        )
        .order_by(EmailMessageDelivery.id)
    )
    if canonical_delivery:
        message = db.get(EmailMessage, canonical_delivery.message_id)
        thread = db.get(EmailThread, message.thread_id) if message else None
        if not message or not thread or thread.channel_id != channel.id:
            raise ValueError("Logical email delivery has an invalid channel association.")
        message.recipients_json = _merge_recipients(
            message.recipients_json, payload.get("ToFull") or []
        )
        message.cc_json = _merge_recipients(message.cc_json, payload.get("CcFull") or [])
        delivery = _new_delivery(
            message=message,
            channel=channel,
            event=event,
            payload=payload,
            logical_key=logical_key,
            canonical=False,
            alias=channel_alias,
        )
        db.add(delivery)
        if delivery.original_recipient and not thread.original_recipient_address:
            thread.original_recipient_address = delivery.original_recipient
        if delivery.technical_recipient and not thread.technical_recipient_address:
            thread.technical_recipient_address = delivery.technical_recipient
        event.processed = True
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                action="inbound_delivery_merged",
                details_json={
                    "webhook_event_id": event.id,
                    "postmark_message_id": payload.get("MessageID")
                    or payload.get("MessageId"),
                    "original_recipient": payload.get("OriginalRecipient"),
                    "inbound_address": _delivery_inbound_address(payload) or None,
                },
            )
        )
        db.commit()
        return thread, False

    cross_channel_delivery = db.scalar(
        select(EmailMessageDelivery)
        .where(
            EmailMessageDelivery.logical_key == logical_key,
            EmailMessageDelivery.canonical_marker == "canonical",
            EmailMessageDelivery.channel_id != channel.id,
        )
        .order_by(EmailMessageDelivery.id)
    )

    external_id = str(payload.get("MessageID") or payload.get("MessageId") or key)
    subject = str(payload.get("Subject") or "(sem assunto)")[:500]
    rule = _inbox_rule(db, channel.id, subject)
    sender = _address(payload.get("From"))
    headers = _headers(payload)
    conversation_id = str(payload.get("OriginalMessageID") or "").strip() or None
    thread = None
    if conversation_id:
        thread = db.scalar(
            select(EmailThread).where(
                EmailThread.channel_id == channel.id,
                EmailThread.external_conversation_id == conversation_id,
            )
        )
    reply_ids = _message_ids(headers.get("in-reply-to"))
    reply_ids.extend(_message_ids(headers.get("references")))
    if not thread and reply_ids:
        parent = db.scalar(
            select(EmailMessage)
            .join(EmailThread, EmailThread.id == EmailMessage.thread_id)
            .where(EmailMessage.external_message_id.in_(reply_ids))
            .where(EmailThread.channel_id == channel.id)
            .order_by(EmailMessage.id.desc())
        )
        if parent:
            thread = db.get(EmailThread, parent.thread_id)
    created_thread = thread is None
    if not thread:
        now = datetime.now(UTC)
        original_recipient = (
            str(payload.get("OriginalRecipient") or "").strip()
            or (channel_alias.address if channel_alias else None)
        )
        technical_recipient = (
            channel_alias.inbound_forward_address if channel_alias else None
        ) or _delivery_inbound_address(payload) or None
        thread = EmailThread(
            channel_id=channel.id,
            subject=subject,
            status="triage",
            sender_email=sender,
            sender_name=payload.get("FromName"),
            external_conversation_id=conversation_id or external_id,
            functional_owner_user_id=channel.functional_owner_user_id,
            original_recipient_address=original_recipient,
            technical_recipient_address=technical_recipient,
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
                "review"
                if channel.requires_triage
                else "classified"
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
            administrative_review_required=(
                channel.administrative_review_on_unclassified
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
        compose_mode="inbound",
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
    db.add(
        _new_delivery(
            message=message,
            channel=channel,
            event=event,
            payload=payload,
            logical_key=logical_key,
            canonical=True,
            alias=channel_alias,
        )
    )
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
        service_desk = ServiceDeskFacade(db)
        service_desk.create_task(task, now=now)
        if auto_task_mode == "complete":
            mark_task_resolved(db, task, actor_user_id=None, now=now)
        service_desk.link_email_origin(
            task.id,
            EmailOriginCommand(
                message_id=external_id,
                sender=sender,
                recipients=payload.get("ToFull") or [],
                subject=subject,
                received_at=message.received_at,
                mailbox=(
                    thread.original_recipient_address
                    or channel.default_reply_address
                    or channel.address
                    or channel.name
                ),
                source_url=f"/v2-clean/email/{thread.id}",
                rule_code=f"email_channel:{channel.code}:{channel.auto_task_mode}",
            ),
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
    db.add(
        EmailAuditEvent(
            thread_id=thread.id,
            message_id=message.id,
            action="inbound_received",
            details_json={
                "logical_message_key": logical_key,
                "original_recipient": thread.original_recipient_address,
                "technical_recipient": thread.technical_recipient_address,
            },
        )
    )
    if cross_channel_delivery:
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                action="inbound_logical_copy_isolated",
                details_json={
                    "reason": "different_channel_authorization_boundary",
                    "delivery_id": cross_channel_delivery.id,
                },
            )
        )
    db.commit()
    return thread, True


def send_message(
    message: EmailMessage,
    from_address: str,
    *,
    reply_to: str | None = None,
    parent_message_id: str | None = None,
    references: list[str] | None = None,
    attachments: list[EmailAttachment] | None = None,
) -> dict:
    if not settings.email_outbound_enabled:
        raise RuntimeError("O envio externo está desligado neste ambiente.")
    if not settings.postmark_server_token:
        raise RuntimeError("POSTMARK_SERVER_TOKEN não está configurado.")
    raw_from = str(from_address or "")
    raw_reply_to = str(reply_to or "")
    has_control = any(
        ord(char) < 32 or ord(char) == 127 for char in raw_from + raw_reply_to
    )
    if (
        has_control
        or not _EMAIL_ADDRESS_RE.fullmatch(_address(from_address))
        or not _EMAIL_ADDRESS_RE.fullmatch(raw_reply_to)
    ):
        raise RuntimeError("From e Reply-To explícitos não estão configurados.")
    recipients = [
        item.get("Email") if isinstance(item, dict) else str(item)
        for item in (message.recipients_json or [])
    ]
    cc_recipients = [
        item.get("Email") if isinstance(item, dict) else str(item)
        for item in (message.cc_json or [])
    ]
    bcc_recipients = [
        item.get("Email") if isinstance(item, dict) else str(item)
        for item in (message.bcc_json or [])
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
    if any(cc_recipients):
        body["Cc"] = ",".join(filter(None, cc_recipients))
    if any(bcc_recipients):
        body["Bcc"] = ",".join(filter(None, bcc_recipients))
    body["ReplyTo"] = reply_to
    if attachments:
        try:
            body["Attachments"] = [
                {
                    "Name": attachment.file_name,
                    "Content": base64.b64encode(
                        Path(attachment.storage_path).read_bytes()
                    ).decode(),
                    "ContentType": attachment.content_type or "application/octet-stream",
                }
                for attachment in attachments
            ]
        except OSError as exc:
            raise RuntimeError("Um anexo da resposta já não está disponível.") from exc
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
