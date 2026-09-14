import base64
from datetime import UTC, datetime

from sqlalchemy import func, select

import app.services.microsoft365_inbound as inbound
from app.models.email import (
    EmailAttachment,
    EmailAuditEvent,
    EmailChannel,
    EmailChannelAlias,
    EmailChannelTransport,
    EmailMessage,
    EmailMessageDelivery,
    EmailSyncCheckpoint,
)
from app.services.email_postmark import ingest_inbound, reply_all_recipients


def _transport(db_session):
    channel = EmailChannel(
        code="frota_graph_test",
        name="Frota Graph test",
        address=None,
        active=True,
    )
    db_session.add(channel)
    db_session.flush()
    transport = EmailChannelTransport(
        channel_id=channel.id,
        provider="microsoft365",
        enabled=True,
        mailbox_address="frota-graph@carfast.local",
        tenant_id="tenant",
        client_id="client",
        client_credential_reference="env://CLIENT_SECRET",
        token_reference="db://token",
        initial_sync_days=5,
    )
    db_session.add(transport)
    db_session.commit()
    return transport


def _message():
    return {
        "id": "A" * 180,
        "internetMessageId": "<graph-test@example.test>",
        "conversationId": "conversation-1",
        "subject": "Teste real de entrada",
        "receivedDateTime": "2026-09-11T23:35:14Z",
        "from": {"emailAddress": {"address": "sender@example.test", "name": "Sender"}},
        "toRecipients": [
            {"emailAddress": {"address": "frota-graph@carfast.local", "name": "Frota"}}
        ],
        "ccRecipients": [],
        "body": {"contentType": "html", "content": "<p>teste</p>"},
        "internetMessageHeaders": [],
        "hasAttachments": False,
    }


def test_graph_payload_is_provider_marked_and_preserves_rfc_message_id():
    payload = inbound.graph_message_payload(
        _message(), mailbox="frota-graph@carfast.local", attachments=[]
    )
    assert payload["SourceProvider"] == "microsoft_graph"
    assert payload["OriginalRecipient"] == "frota-graph@carfast.local"
    assert {row["Name"].casefold() for row in payload["Headers"]} == {"message-id"}


def test_graph_payload_preserves_original_recipient_from_delivery_header():
    message = _message()
    message["internetMessageHeaders"] = [
        {"name": "Delivered-To", "value": "Functional Alias <claims@example.test>"}
    ]
    payload = inbound.graph_message_payload(
        message, mailbox="functional@example.test", attachments=[]
    )

    assert payload["OriginalRecipient"] == "claims@example.test"
    assert payload["To"] == "claims@example.test"
    assert payload["ToFull"] == [
        {"Email": "claims@example.test", "Name": ""},
        {"Email": "frota-graph@carfast.local", "Name": "Frota"}
    ]


def test_graph_payload_prefers_non_mailbox_to_recipient_then_falls_back():
    message = _message()
    message["toRecipients"] = [
        {"emailAddress": {"address": "functional@example.test"}},
        {"emailAddress": {"address": "alias@example.test"}},
    ]
    payload = inbound.graph_message_payload(
        message, mailbox="functional@example.test", attachments=[]
    )
    assert payload["OriginalRecipient"] == "alias@example.test"

    message["toRecipients"] = []
    payload = inbound.graph_message_payload(
        message, mailbox="functional@example.test", attachments=[]
    )
    assert payload["OriginalRecipient"] == "functional@example.test"


def test_graph_attachment_collection_avoids_derived_property_select(monkeypatch):
    requested = []

    def fake_get(url, token_kwargs):
        requested.append(url)
        return {
            "value": [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "attachment-id",
                    "contentBytes": "YQ==",
                }
            ]
        }

    monkeypatch.setattr(inbound, "_graph_get", fake_get)
    rows = inbound._attachments("frota@example.test", "message-id", {})

    assert len(rows) == 1
    assert requested == [
        "https://graph.microsoft.com/v1.0/users/frota%40example.test/"
        "messages/message-id/attachments"
    ]
    assert "$select" not in requested[0]


def test_delta_sync_persists_message_checkpoint_and_is_idempotent(db_session, monkeypatch):
    transport = _transport(db_session)
    pages = [
        {"value": [_message()], "@odata.deltaLink": "https://graph.test/delta-1"},
        {"value": [], "@odata.deltaLink": "https://graph.test/delta-2"},
    ]

    def fake_get(url, token_kwargs):
        assert token_kwargs["tenant_id"] == "tenant"
        return pages.pop(0)

    monkeypatch.setattr(inbound, "_graph_get", fake_get)
    first = inbound.sync_transport_inbox(db_session, transport)
    second = inbound.sync_transport_inbox(db_session, transport)

    assert first == {"seen": 1, "created": 1}
    assert second == {"seen": 0, "created": 0}
    assert db_session.scalar(select(func.count()).select_from(EmailMessage)) == 1
    message = db_session.scalar(select(EmailMessage))
    assert message.received_at.replace(tzinfo=UTC) == datetime(
        2026, 9, 11, 23, 35, 14, tzinfo=UTC
    )
    checkpoint = db_session.scalar(select(EmailSyncCheckpoint))
    assert checkpoint.status == "ready"
    assert checkpoint.delta_link == "https://graph.test/delta-2"
    audit = db_session.scalar(
        select(EmailAuditEvent).where(EmailAuditEvent.action == "microsoft_graph_synced")
    )
    assert audit.details_json["folder"] == "inbox"


def test_manual_sync_can_select_transport_by_configured_alias(db_session, monkeypatch):
    transport = _transport(db_session)
    alias = EmailChannelAlias(
        channel_id=transport.channel_id,
        address="approved-alias@carfast.local",
        active=True,
    )
    db_session.add(alias)
    db_session.commit()
    calls = []

    def fake_sync(db, selected):
        calls.append(selected.id)
        return {"seen": 0, "created": 0}

    monkeypatch.setattr(inbound, "sync_transport_inbox", fake_sync)

    result = inbound.sync_enabled_inboxes(
        db_session, mailboxes=["APPROVED-ALIAS@carfast.local"]
    )

    assert result == {transport.id: {"seen": 0, "created": 0}}
    assert calls == [transport.id]


def test_graph_original_recipient_routes_to_configured_alias_channel(db_session):
    transport = _transport(db_session)
    alias = EmailChannelAlias(
        channel_id=transport.channel_id,
        address="claims@carfast.local",
        active=True,
    )
    db_session.add(alias)
    db_session.commit()
    message = _message()
    message["internetMessageHeaders"] = [
        {"name": "X-Original-To", "value": "claims@carfast.local"}
    ]

    thread, created = ingest_inbound(
        db_session,
        inbound.graph_message_payload(
            message, mailbox=transport.mailbox_address, attachments=[]
        ),
    )

    assert created is True
    assert thread.channel_id == transport.channel_id
    stored = db_session.scalar(select(EmailMessage))
    assert stored.recipients_json == [
        {"Email": "claims@carfast.local", "Name": ""},
        {"Email": "frota-graph@carfast.local", "Name": "Frota"}
    ]


def test_manual_sync_rejects_unknown_or_untransported_address(db_session):
    _transport(db_session)

    try:
        inbound.sync_enabled_inboxes(
            db_session, mailboxes=["unknown@carfast.local"]
        )
    except ValueError as exc:
        assert "unknown@carfast.local" in str(exc)
    else:
        raise AssertionError("unknown address must not be silently accepted")


def test_graph_attachment_and_postmark_copy_merge_without_duplicate(
    db_session, monkeypatch, tmp_path
):
    transport = _transport(db_session)
    channel = db_session.get(EmailChannel, transport.channel_id)
    channel.address = transport.mailbox_address
    channel.default_reply_address = transport.mailbox_address
    channel.from_address = transport.mailbox_address
    channel.reply_to_address = transport.mailbox_address
    db_session.commit()
    monkeypatch.setattr(
        "app.services.email_postmark.settings.email_storage_root", str(tmp_path)
    )

    graph = _message()
    graph["id"] = "graph-attachment-message"
    graph["hasAttachments"] = True
    encoded = base64.b64encode(b"graph attachment").decode("ascii")
    graph_payload = inbound.graph_message_payload(
        graph,
        mailbox=transport.mailbox_address,
        attachments=[
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "id": "graph-attachment-1",
                "name": "proof.txt",
                "contentType": "text/plain",
                "size": len(b"graph attachment"),
                "isInline": False,
                "contentBytes": encoded,
            }
        ],
    )
    thread, created = ingest_inbound(db_session, graph_payload)
    assert created is True

    postmark_payload = {
        "MessageID": "postmark-copy-message",
        "From": "sender@example.test",
        "FromName": "Sender",
        "To": transport.mailbox_address,
        "ToFull": [{"Email": transport.mailbox_address}],
        "CcFull": [],
        "Subject": graph["subject"],
        "TextBody": "same logical email",
        "HtmlBody": None,
        "Headers": [
            {"Name": "Message-ID", "Value": graph["internetMessageId"]},
        ],
        "Attachments": [],
    }
    duplicate_thread, duplicate_created = ingest_inbound(db_session, postmark_payload)

    assert duplicate_created is False
    assert duplicate_thread.id == thread.id
    assert db_session.scalar(select(func.count()).select_from(EmailMessage)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailMessageDelivery)) == 2
    attachment = db_session.scalar(select(EmailAttachment))
    assert attachment.source_provider == "microsoft_graph"
    assert attachment.ingest_state == "stored"
    assert attachment.storage_path

    message = db_session.scalar(select(EmailMessage))
    assert message.direction == "inbound"
    to_rows, cc_rows = reply_all_recipients(
        db_session, message, transport.mailbox_address
    )
    assert to_rows == [{"Email": "sender@example.test"}]
    assert cc_rows == []
    assert channel.reply_to_address == transport.mailbox_address
