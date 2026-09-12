from datetime import UTC, datetime

from sqlalchemy import func, select

import app.services.microsoft365_inbound as inbound
from app.models.email import (
    EmailAuditEvent,
    EmailChannel,
    EmailChannelTransport,
    EmailMessage,
    EmailSyncCheckpoint,
)


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
