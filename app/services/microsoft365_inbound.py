from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email import (
    EmailAuditEvent,
    EmailChannel,
    EmailChannelTransport,
    EmailMessage,
    EmailSyncCheckpoint,
)
from app.services.email_postmark import ingest_inbound
from app.services.microsoft365_oauth import _delegated_access_token

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"
INBOX_SELECT = ",".join(
    (
        "id",
        "internetMessageId",
        "conversationId",
        "subject",
        "receivedDateTime",
        "from",
        "toRecipients",
        "ccRecipients",
        "body",
        "internetMessageHeaders",
        "hasAttachments",
    )
)


def _recipient(item: dict[str, Any] | None) -> dict[str, str]:
    value = (item or {}).get("emailAddress") or {}
    return {
        "Email": str(value.get("address") or "").strip(),
        "Name": str(value.get("name") or "").strip(),
    }


def _graph_get(url: str, token_kwargs: dict[str, str]) -> dict[str, Any]:
    token = _delegated_access_token(**token_kwargs)

    def submit(access_token: str) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())

    try:
        return submit(token)
    except urllib.error.HTTPError as exc:
        if exc.code != 401:
            raise RuntimeError(f"Microsoft Graph devolveu HTTP {exc.code}.") from exc
    try:
        return submit(_delegated_access_token(**token_kwargs, force_refresh=True))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Microsoft Graph devolveu HTTP {exc.code} após renovar a autenticação."
        ) from exc


def _attachments(
    mailbox: str, message_id: str, token_kwargs: dict[str, str]
) -> list[dict[str, Any]]:
    mailbox_id = urllib.parse.quote(mailbox, safe="")
    graph_id = urllib.parse.quote(message_id, safe="")
    url = (
        f"{GRAPH_ROOT}/users/{mailbox_id}/messages/{graph_id}/attachments"
        "?$select=id,name,contentType,size,isInline,contentId,contentBytes"
    )
    rows: list[dict[str, Any]] = []
    while url:
        page = _graph_get(url, token_kwargs)
        rows.extend(
            item
            for item in page.get("value") or []
            if item.get("@odata.type") in {None, "#microsoft.graph.fileAttachment"}
        )
        url = str(page.get("@odata.nextLink") or "")
    return rows


def graph_message_payload(
    item: dict[str, Any], *, mailbox: str, attachments: list[dict[str, Any]]
) -> dict[str, Any]:
    sender = _recipient(item.get("from"))
    body = item.get("body") or {}
    received = str(item.get("receivedDateTime") or "")
    headers = [
        {"Name": str(row.get("name") or ""), "Value": str(row.get("value") or "")}
        for row in item.get("internetMessageHeaders") or []
        if row.get("name")
    ]
    if item.get("internetMessageId") and not any(
        row["Name"].casefold() == "message-id" for row in headers
    ):
        headers.append({"Name": "Message-ID", "Value": item["internetMessageId"]})
    return {
        "SourceProvider": "microsoft_graph",
        "MessageID": str(item["id"]),
        "OriginalMessageID": str(item.get("conversationId") or ""),
        "OriginalRecipient": mailbox,
        "From": sender["Email"],
        "FromName": sender["Name"],
        "To": mailbox,
        "ToFull": [_recipient(row) for row in item.get("toRecipients") or []],
        "CcFull": [_recipient(row) for row in item.get("ccRecipients") or []],
        "Subject": str(item.get("subject") or "(sem assunto)"),
        "Date": received,
        "TextBody": str(body.get("content") or "") if body.get("contentType") == "text" else None,
        "HtmlBody": str(body.get("content") or "") if body.get("contentType") != "text" else None,
        "Headers": headers,
        "Attachments": attachments,
    }


def sync_transport_inbox(db: Session, transport: EmailChannelTransport) -> dict[str, int]:
    if transport.provider != "microsoft365" or not transport.enabled:
        return {"seen": 0, "created": 0}
    required = {
        "tenant_id": transport.tenant_id,
        "client_id": transport.client_id,
        "client_credential_reference": transport.client_credential_reference,
        "token_reference": transport.token_reference,
        "mailbox": transport.mailbox_address,
    }
    if not all(required.values()):
        raise RuntimeError("O transporte Microsoft 365 não tem configuração completa.")
    channel = db.get(EmailChannel, transport.channel_id)
    if channel is None or not channel.active:
        return {"seen": 0, "created": 0}

    checkpoint = db.scalar(
        select(EmailSyncCheckpoint).where(
            EmailSyncCheckpoint.transport_id == transport.id,
            EmailSyncCheckpoint.folder == "inbox",
        )
    )
    if checkpoint is None:
        checkpoint = EmailSyncCheckpoint(
            transport_id=transport.id,
            folder="inbox",
            status="pending",
            initial_window_started_at=datetime.now(UTC)
            - timedelta(days=transport.initial_sync_days),
        )
        db.add(checkpoint)
        db.flush()

    mailbox = str(required.pop("mailbox"))
    token_kwargs = {key: str(value) for key, value in required.items()}
    mailbox_id = urllib.parse.quote(mailbox, safe="")
    if checkpoint.delta_link:
        url = checkpoint.delta_link
    else:
        started = checkpoint.initial_window_started_at or (
            datetime.now(UTC) - timedelta(days=transport.initial_sync_days)
        )
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        filter_value = urllib.parse.quote(
            f"receivedDateTime ge {started.astimezone(UTC).isoformat().replace('+00:00', 'Z')}",
            safe="",
        )
        url = (
            f"{GRAPH_ROOT}/users/{mailbox_id}/mailFolders/inbox/messages/delta"
            f"?$filter={filter_value}&$select={urllib.parse.quote(INBOX_SELECT, safe=',')}"
        )

    seen = created = 0
    checkpoint.status = "running"
    checkpoint.last_error = None
    db.commit()
    try:
        while url:
            page = _graph_get(url, token_kwargs)
            for item in page.get("value") or []:
                if item.get("@removed") or not item.get("id"):
                    continue
                seen += 1
                files = (
                    _attachments(mailbox, item["id"], token_kwargs)
                    if item.get("hasAttachments")
                    else []
                )
                thread, was_created = ingest_inbound(
                    db, graph_message_payload(item, mailbox=mailbox, attachments=files)
                )
                created += int(was_created)
                message = db.scalar(
                    select(EmailMessage).where(EmailMessage.external_message_id == item["id"])
                )
                received = item.get("receivedDateTime")
                if message and received:
                    message.received_at = datetime.fromisoformat(
                        str(received).replace("Z", "+00:00")
                    )
                    previous = thread.last_message_at
                    if previous and previous.tzinfo is None:
                        previous = previous.replace(tzinfo=UTC)
                    thread.last_message_at = max(
                        filter(None, (previous, message.received_at))
                    )
                    already_audited = db.scalar(
                        select(EmailAuditEvent.id).where(
                            EmailAuditEvent.message_id == message.id,
                            EmailAuditEvent.action == "microsoft_graph_synced",
                        )
                    )
                    if already_audited is None:
                        db.add(
                            EmailAuditEvent(
                                thread_id=thread.id,
                                message_id=message.id,
                                action="microsoft_graph_synced",
                                details_json={"folder": "inbox", "transport_id": transport.id},
                            )
                        )
                    db.commit()
            next_link = str(page.get("@odata.nextLink") or "")
            delta_link = str(page.get("@odata.deltaLink") or "")
            if delta_link:
                checkpoint.delta_link = delta_link
            url = next_link
        checkpoint.status = "ready"
        checkpoint.last_synced_at = datetime.now(UTC)
        db.commit()
        return {"seen": seen, "created": created}
    except Exception as exc:
        db.rollback()
        checkpoint = db.get(EmailSyncCheckpoint, checkpoint.id)
        checkpoint.status = "error"
        checkpoint.last_error = str(exc)[:2000]
        db.commit()
        raise


def sync_enabled_inboxes(db: Session) -> dict[int, dict[str, int]]:
    transports = db.scalars(
        select(EmailChannelTransport).where(
            EmailChannelTransport.provider == "microsoft365",
            EmailChannelTransport.enabled.is_(True),
        )
    ).all()
    return {transport.id: sync_transport_inbox(db, transport) for transport in transports}
