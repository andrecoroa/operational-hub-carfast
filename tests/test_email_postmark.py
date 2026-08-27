import base64
import json
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import app.web.email as email_web
from app.core.config import settings
from app.models.admin import User
from app.models.email import (
    EmailAttachment,
    EmailChannel,
    EmailChannelUser,
    EmailExecutorEligibility,
    EmailInboxRule,
    EmailMessage,
    EmailMessageDelivery,
    EmailThread,
    EmailWebhookEvent,
)
from app.models.organization import Team, TeamMember
from app.services.bootstrap import (
    POSTMARK_INBOUND_DOMAIN,
    POSTMARK_INBOUND_LOCAL_PART,
    postmark_inbound_address,
    seed_email_channels,
)
from app.services.email_postmark import (
    ensure_email_channels,
    ingest_inbound,
    reply_all_recipients,
    send_message,
    webhook_authorized,
)
from app.services.service_desk import (
    claim_email_thread,
    initialize_email_operations,
    sla_snapshot,
)
from app.services.work_classification import thread_reference


def _payload(message_id: str = "pm-test-1") -> dict:
    return {
        "MessageID": message_id,
        "From": "Cliente Teste <cliente@example.com>",
        "FromName": "Cliente Teste",
        "To": "hub@carfast.pt",
        "ToFull": [{"Email": "hub@carfast.pt", "Name": "CarFast"}],
        "Subject": "Pedido de informação",
        "TextBody": "Boa tarde, preciso de ajuda.",
        "HtmlBody": "<p>Boa tarde, preciso de ajuda.</p>",
        "Headers": [],
        "Attachments": [
            {
                "Name": "pedido.txt",
                "ContentType": "text/plain",
                "Content": base64.b64encode(b"conteudo").decode(),
                "ContentID": "",
            }
        ],
    }


def test_webhook_basic_auth_requires_configured_exact_credentials(monkeypatch):
    monkeypatch.setattr(settings, "postmark_inbound_basic_user", "postmark")
    monkeypatch.setattr(settings, "postmark_inbound_basic_password", "secret")
    valid = "Basic " + base64.b64encode(b"postmark:secret").decode()
    invalid = "Basic " + base64.b64encode(b"postmark:wrong").decode()

    assert webhook_authorized(valid) is True
    assert webhook_authorized(invalid) is False
    assert webhook_authorized(None) is False


def test_inbound_is_idempotent_and_archives_attachments(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    first_thread, first_created = ingest_inbound(db_session, _payload())
    second_thread, second_created = ingest_inbound(db_session, _payload())

    assert first_created is True
    assert second_created is False
    assert first_thread.id == second_thread.id
    assert db_session.scalar(select(func.count()).select_from(EmailThread)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailMessage)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailAttachment)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailWebhookEvent)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailMessageDelivery)) == 1
    attachment = db_session.scalar(select(EmailAttachment))
    assert (
        tmp_path.joinpath(
            str(first_thread.id), str(attachment.message_id), "pedido.txt"
        ).read_bytes()
        == b"conteudo"
    )


def test_same_logical_email_via_two_postmark_deliveries_is_merged_and_auditable(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    first = _payload("pm-forward-a")
    first.update(
        {
            "MailboxHash": "hub",
            "OriginalRecipient": "apoio@carfast.pt",
            "ToFull": [{"Email": "apoio@carfast.pt", "Name": "Apoio"}],
            "CcFull": [{"Email": "operacoes@carfast.pt", "Name": "Operações"}],
            "Headers": [
                {"Name": "Message-ID", "Value": "<external-message-42@example.com>"},
                {"Name": "Date", "Value": "Fri, 21 Aug 2026 09:15:00 +0100"},
            ],
        }
    )
    second = dict(first)
    second["MessageID"] = "pm-forward-b"
    second["OriginalRecipient"] = "operacoes@carfast.pt"

    first_thread, first_created = ingest_inbound(db_session, first)
    second_thread, second_created = ingest_inbound(db_session, second)
    repeated_thread, repeated_created = ingest_inbound(db_session, second)

    assert first_created is True
    assert second_created is False
    assert repeated_created is False
    assert first_thread.id == second_thread.id == repeated_thread.id
    assert db_session.scalar(select(func.count()).select_from(EmailThread)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailMessage)) == 1
    assert db_session.scalar(select(func.count()).select_from(EmailWebhookEvent)) == 2
    assert db_session.scalar(select(func.count()).select_from(EmailMessageDelivery)) == 2
    deliveries = list(
        db_session.scalars(select(EmailMessageDelivery).order_by(EmailMessageDelivery.id))
    )
    assert {item.original_recipient for item in deliveries} == {
        "apoio@carfast.pt",
        "operacoes@carfast.pt",
    }
    assert [item.canonical_marker for item in deliveries] == ["canonical", None]
    message = db_session.scalar(select(EmailMessage))
    assert message.recipients_json == [{"Email": "apoio@carfast.pt", "Name": "Apoio"}]
    assert message.cc_json == [
        {"Email": "operacoes@carfast.pt", "Name": "Operações"}
    ]

    preview = authenticated_client.get(f"/v2-clean/email/{first_thread.id}/preview")
    assert preview.status_code == 200
    assert "Para: apoio@carfast.pt" in preview.text
    assert "Cc: operacoes@carfast.pt" in preview.text
    assert "Recebido originalmente em" in preview.text
    assert "Responder a todos" in preview.text


def test_reply_all_excludes_every_internal_address_and_alias(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    payload = _payload("pm-reply-all")
    payload["MailboxHash"] = "hub"
    payload["ToFull"] = [
        {"Email": "hub@carfast.pt"},
        {"Email": "observador@example.net"},
    ]
    payload["CcFull"] = [
        {"Email": "colega@example.org", "Name": "Colega"},
        {"Email": "multas@carfast.pt"},
        {"Email": postmark_inbound_address("oficina")},
    ]
    payload["Headers"] = [
        {"Name": "Message-ID", "Value": "<reply-all-source@example.com>"}
    ]
    thread, _ = ingest_inbound(db_session, payload)
    source = db_session.scalar(
        select(EmailMessage).where(EmailMessage.thread_id == thread.id)
    )

    reply_to, reply_cc = reply_all_recipients(db_session, source, "hub@carfast.pt")
    assert reply_to == [{"Email": "cliente@example.com"}]
    assert {item["Email"] for item in reply_cc} == {
        "observador@example.net",
        "colega@example.org",
    }

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={
            "body": "Resposta para todos os intervenientes externos.",
            "recipient_email": "cliente@example.com",
            "reply_mode": "all",
            "reply_source_message_id": str(source.id),
            "submit": "approval",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    outbound = db_session.scalar(
        select(EmailMessage)
        .where(EmailMessage.thread_id == thread.id, EmailMessage.direction == "outbound")
        .order_by(EmailMessage.id.desc())
    )
    assert outbound.recipients_json == [{"Email": "cliente@example.com"}]
    assert {item["Email"] for item in outbound.cc_json} == {
        "observador@example.net",
        "colega@example.org",
    }
    assert all(
        "carfast" not in item["Email"] and "postmarkapp.com" not in item["Email"]
        for item in [*outbound.recipients_json, *outbound.cc_json]
    )


def test_same_logical_email_remains_isolated_across_functional_channels(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    first = _payload("pm-cross-channel-a")
    first["MailboxHash"] = "multas"
    first["Headers"] = [
        {"Name": "Message-ID", "Value": "<cross-channel@example.com>"}
    ]
    second = dict(first)
    second["MessageID"] = "pm-cross-channel-b"
    second["MailboxHash"] = "oficina"

    first_thread, first_created = ingest_inbound(db_session, first)
    second_thread, second_created = ingest_inbound(db_session, second)

    assert first_created is True
    assert second_created is True
    assert first_thread.id != second_thread.id
    assert first_thread.channel_id != second_thread.channel_id
    assert db_session.scalar(select(func.count()).select_from(EmailMessage)) == 2
    deliveries = list(db_session.scalars(select(EmailMessageDelivery)))
    assert len({item.logical_key for item in deliveries}) == 1
    assert {item.canonical_marker for item in deliveries} == {"canonical"}


def test_fallback_logical_key_merges_only_matching_dated_content(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    first = _payload("pm-fallback-a")
    first["Headers"] = [
        {"Name": "Date", "Value": "Fri, 21 Aug 2026 10:00:03 +0100"}
    ]
    duplicate = dict(first)
    duplicate["MessageID"] = "pm-fallback-b"
    distinct = dict(first)
    distinct["MessageID"] = "pm-fallback-c"
    distinct["TextBody"] = "Conteúdo efetivamente diferente."

    first_thread, first_created = ingest_inbound(db_session, first)
    duplicate_thread, duplicate_created = ingest_inbound(db_session, duplicate)
    distinct_thread, distinct_created = ingest_inbound(db_session, distinct)

    assert first_created is True
    assert duplicate_created is False
    assert distinct_created is True
    assert duplicate_thread.id == first_thread.id
    assert distinct_thread.id != first_thread.id
    assert db_session.scalar(select(func.count()).select_from(EmailMessage)) == 2
    assert db_session.scalar(select(func.count()).select_from(EmailMessageDelivery)) == 3


def test_inbound_subject_rule_overrides_channel_defaults(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    ensure_email_channels(db_session)
    channel = db_session.scalar(select(EmailChannel).where(EmailChannel.code == "test"))
    channel.default_due_days = 10
    db_session.add(
        EmailInboxRule(
            channel_id=channel.id,
            name="Faturas de stock",
            subject_match="fatura stock",
            match_type="contains",
            default_document_type="stock_invoice",
            default_due_days=2,
            auto_task_mode="none",
            sort_order=10,
        )
    )
    db_session.commit()

    payload = _payload("pm-rule-contains")
    payload["Subject"] = "RE: Fatura Stock 2026/123"
    thread, created = ingest_inbound(db_session, payload)

    assert created is True
    assert thread.document_type == "stock_invoice"
    assert 1 <= (thread.due_at.date() - thread.created_at.date()).days <= 2
    assert thread.task_id is None


def test_inbound_exact_rule_does_not_match_partial_subject(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    ensure_email_channels(db_session)
    channel = db_session.scalar(select(EmailChannel).where(EmailChannel.code == "test"))
    channel.default_document_type = "default_document"
    db_session.add(
        EmailInboxRule(
            channel_id=channel.id,
            name="Assunto exato",
            subject_match="Documento mensal",
            match_type="exact",
            default_document_type="monthly_document",
            sort_order=10,
        )
    )
    db_session.commit()

    payload = _payload("pm-rule-exact")
    payload["Subject"] = "RE: Documento mensal"
    thread, _ = ingest_inbound(db_session, payload)

    assert thread.document_type == "default_document"


def test_clean_email_inbox_and_thread_render(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    thread, _ = ingest_inbound(db_session, _payload("pm-ui-1"))

    inbox = authenticated_client.get("/v2-clean/email")
    detail = authenticated_client.get(f"/v2-clean/email/{thread.id}")

    assert inbox.status_code == 200
    assert "Pedido de informação" in inbox.text
    assert thread_reference(thread) in inbox.text
    assert "Responsável" in inbox.text
    assert "Prazo" in inbox.text
    assert "Permissões por caixa" not in inbox.text
    assert detail.status_code == 200
    assert "Responder" in detail.text
    assert "/v2-clean/email/messages/" in detail.text


def test_email_inbox_defaults_to_triage_and_searches_message_content(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    triage_thread, _ = ingest_inbound(db_session, _payload("pm-inbox-triage"))
    archived_payload = _payload("pm-inbox-archived")
    archived_payload["Subject"] = "Conversa arquivada"
    archived_payload["TextBody"] = "Conteúdo reservado para pesquisa alargada."
    archived_thread, _ = ingest_inbound(db_session, archived_payload)
    archived_thread.status = "archived"
    db_session.commit()

    default_inbox = authenticated_client.get("/v2-clean/email")
    all_inbox = authenticated_client.get("/v2-clean/email?status=all")
    body_search = authenticated_client.get("/v2-clean/email?status=all&q=pesquisa+alargada")
    reference_search = authenticated_client.get(
        f"/v2-clean/email?status=all&q={thread_reference(archived_thread)}"
    )

    assert default_inbox.status_code == 200
    assert triage_thread.subject in default_inbox.text
    assert archived_thread.subject not in default_inbox.text
    assert archived_thread.subject in all_inbox.text
    assert archived_thread.subject in body_search.text
    assert archived_thread.subject in reference_search.text


def test_email_preview_sanitizes_html_and_task_uses_operational_queue(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    payload = _payload("pm-ui-safe")
    payload["HtmlBody"] = (
        "<p>Olá <strong>CarFast</strong></p><script>alert(1)</script>"
        '<img src="https://example.com/logo.png" onerror="alert(2)">'
    )
    thread, _ = ingest_inbound(db_session, payload)
    message = db_session.scalar(select(EmailMessage).where(EmailMessage.thread_id == thread.id))

    preview = authenticated_client.get(f"/v2-clean/email/{thread.id}/preview")
    body = authenticated_client.get(f"/v2-clean/email/messages/{message.id}/body")
    authenticated_client.post(f"/v2-clean/email/{thread.id}/task", follow_redirects=False)
    db_session.expire_all()

    assert preview.status_code == 200
    assert "Abrir página completa" in preview.text
    assert body.status_code == 200
    assert "<script" not in body.text
    assert "onerror" not in body.text
    assert 'data-email-src="https://example.com/logo.png"' in body.text
    refreshed = db_session.get(EmailThread, thread.id)
    assert refreshed.task_id is not None
    task = db_session.get(email_web.Task, refreshed.task_id)
    assert task.task_type == "operational_task"


def test_email_triage_is_reused_by_task_and_attachment_is_opened_on_demand(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    thread, _ = ingest_inbound(db_session, _payload("pm-ui-triage"))
    attachment = db_session.scalar(select(EmailAttachment))

    triage = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={
            "content_type": "document",
            "nature": "stock",
            "document_type": "invoice",
            "triage_notes": "Validar entrada de material.",
        },
        follow_redirects=False,
    )
    preview = authenticated_client.get(f"/v2-clean/email/attachments/{attachment.id}/preview")
    task_response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/task", follow_redirects=False
    )
    db_session.expire_all()

    assert triage.status_code == 303
    assert preview.status_code == 200
    assert "Decidir tratamento" in preview.text
    assert task_response.status_code == 303
    refreshed = db_session.get(EmailThread, thread.id)
    task = db_session.get(email_web.Task, refreshed.task_id)
    assert refreshed.nature == "stock"
    assert task.category == "stock"
    assert task.subcategory == "invoice"
    assert "Validar entrada de material" in task.description


def test_pdf_attachment_with_generic_content_type_opens_inline(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    payload = _payload("pm-pdf-preview")
    payload["Attachments"] = [
        {
            "Name": "fatura.PDF",
            "ContentType": "application/octet-stream",
            "Content": base64.b64encode(b"%PDF-1.4\n%test").decode(),
            "ContentID": "",
        }
    ]
    ingest_inbound(db_session, payload)
    attachment = db_session.scalar(select(EmailAttachment))

    response = authenticated_client.get(f"/v2-clean/email/attachments/{attachment.id}/file")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == "inline"
    assert response.content.startswith(b"%PDF")


def test_inbound_reply_is_added_to_existing_thread(db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    thread, _ = ingest_inbound(db_session, _payload("pm-original"))
    outbound = EmailMessage(
        thread_id=thread.id,
        external_message_id="pm-outbound",
        direction="outbound",
        state="sent",
        sender="hub@carfast.pt",
        recipients_json=[{"Email": "cliente@example.com"}],
        subject="Re: Pedido de informação",
    )
    db_session.add(outbound)
    db_session.commit()

    reply = _payload("pm-reply")
    reply["Subject"] = "Re: Pedido de informação"
    reply["Headers"] = [
        {"Name": "In-Reply-To", "Value": "<pm-outbound>"},
        {"Name": "References", "Value": "<pm-original> <pm-outbound>"},
    ]
    reply_thread, created = ingest_inbound(db_session, reply)

    assert created is True
    assert reply_thread.id == thread.id
    assert db_session.scalar(select(func.count()).select_from(EmailThread)) == 1


def test_send_message_uses_hub_sender_and_thread_headers(monkeypatch):
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"MessageID":"pm-sent"}'

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["token"] = request.headers["X-postmark-server-token"]
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(settings, "email_outbound_enabled", True)
    monkeypatch.setattr(settings, "postmark_server_token", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    message = EmailMessage(
        id=42,
        thread_id=7,
        direction="outbound",
        state="pending_approval",
        sender="hub@carfast.pt",
        recipients_json=[{"Email": "cliente@example.com"}],
        subject="Re: Pedido",
        text_body="Resposta de teste",
    )

    result = send_message(
        message,
        "hub@carfast.pt",
        reply_to="hub@carfast.pt",
        parent_message_id="pm-inbound",
        references=["pm-first"],
    )

    assert result["MessageID"] == "pm-sent"
    assert captured["body"]["From"] == "hub@carfast.pt"
    assert captured["body"]["ReplyTo"] == "hub@carfast.pt"
    assert captured["body"]["To"] == "cliente@example.com"
    assert captured["body"]["Headers"] == [
        {"Name": "In-Reply-To", "Value": "<pm-inbound>"},
        {"Name": "References", "Value": "<pm-first> <pm-inbound>"},
    ]
    assert captured["token"] == "test-token"
    assert captured["timeout"] == 20


def test_mailbox_access_requires_explicit_assignment_for_regular_users(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    thread, _ = ingest_inbound(db_session, _payload("pm-access"))
    user = db_session.scalar(select(User).order_by(User.id))

    assert email_web._channel_access(db_session, user.id, {"email.read"}) == {}

    db_session.add(
        EmailChannelUser(
            channel_id=thread.channel_id,
            user_id=user.id,
            can_reply=True,
            can_approve=False,
        )
    )
    db_session.commit()
    access = email_web._channel_access(db_session, user.id, {"email.read"})

    assert thread.channel_id in access
    assert (
        email_web._can_use_channel(db_session, user.id, {"email.read"}, thread.channel_id, "reply")
        is True
    )
    assert (
        email_web._can_use_channel(
            db_session, user.id, {"email.read"}, thread.channel_id, "approve"
        )
        is False
    )


def test_email_modal_submits_the_clicked_action():
    script = (Path(__file__).parents[1] / "app" / "static" / "js" / "email.js").read_text(
        encoding="utf-8"
    )

    assert "const submitter = event.submitter" in script
    assert "payload.set(submitter.name, submitter.value)" in script
    assert "body: payload" in script


def test_email_modal_approval_has_an_explicit_click_handler():
    root = Path(__file__).parents[1]
    script = (root / "app" / "static" / "js" / "email.js").read_text(encoding="utf-8")
    template = (root / "app" / "templates" / "_email_thread_content.html").read_text(
        encoding="utf-8"
    )

    assert 'data-email-approve data-email-thread-id="{{ thread.id }}"' in template
    assert 'querySelectorAll("[data-email-approve]")' in script
    assert 'event.submitter?.matches("[data-email-approve]")' in script
    assert 'resultUrl.searchParams.has("error")' in script


def test_email_reply_can_change_the_reply_recipient(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    thread, _ = ingest_inbound(db_session, _payload("pm-sender-select"))
    preview = authenticated_client.get(f"/v2-clean/email/{thread.id}/preview")
    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={
            "body": "Resposta preparada para outro destinatário.",
            "recipient_email": "gestor.cliente@example.com",
            "submit": "approval",
        },
        follow_redirects=False,
    )

    assert preview.status_code == 200
    assert 'name="recipient_email"' in preview.text
    assert "Responder para" in preview.text
    assert response.status_code == 303
    message = db_session.scalar(
        select(EmailMessage)
        .where(EmailMessage.thread_id == thread.id, EmailMessage.direction == "outbound")
        .order_by(EmailMessage.id.desc())
    )
    assert message.recipients_json == [{"Email": "gestor.cliente@example.com"}]
    assert message.state == "pending_approval"


def test_email_reply_rejects_an_invalid_recipient(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    thread, _ = ingest_inbound(db_session, _payload("pm-invalid-recipient"))

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={
            "body": "Esta resposta não deve ficar guardada.",
            "recipient_email": "endereco-invalido",
            "submit": "approval",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("error=invalid_recipient")
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(EmailMessage)
            .where(EmailMessage.thread_id == thread.id, EmailMessage.direction == "outbound")
        )
        == 0
    )


def test_email_approval_keeps_the_recipient_selected_on_the_reply(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "email_outbound_enabled", True)
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    thread, _ = ingest_inbound(db_session, _payload("pm-sender-approval"))
    authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={
            "body": "Resposta a aprovar.",
            "recipient_email": "decisor@example.com",
            "submit": "approval",
        },
    )
    message = db_session.scalar(
        select(EmailMessage)
        .where(EmailMessage.thread_id == thread.id, EmailMessage.direction == "outbound")
        .order_by(EmailMessage.id.desc())
    )
    captured = {}

    def fake_send_message(message, sender, **kwargs):
        captured["message_id"] = message.id
        captured["sender"] = sender
        captured["reply_to"] = kwargs["reply_to"]
        return {"MessageID": "pm-sender-sent"}

    monkeypatch.setattr(email_web, "send_message", fake_send_message)
    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/messages/{message.id}/approve",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert captured["message_id"] == message.id
    assert message.recipients_json == [{"Email": "decisor@example.com"}]
    db_session.refresh(message)
    assert message.state == "sent"
    assert message.external_message_id == "pm-sender-sent"


def test_five_mailboxes_bootstrap_with_exact_postmark_plus_addresses(db_session):
    seed_email_channels(db_session)
    seed_email_channels(db_session)
    db_session.commit()

    channels = {
        item.code: item for item in db_session.scalars(select(EmailChannel)).all()
    }
    assert set(channels) == {
        "test",
        "multas",
        "oficina",
        "sinistros",
        "vvp",
        "seguradoras",
        "brokers",
        "departamento_financeiro",
        "reports",
        "administrativo",
        "suporte",
        "outros",
    }
    expected = {
        "test": ("hub@carfast.pt", "hub"),
        "multas": ("multas@carfast.pt", "multas"),
        "oficina": ("oficina@carfast.pt", "oficina"),
        "sinistros": ("sinistros@carfast.pt", "sinistros"),
        "vvp": ("vvp@carfast.pt", "vvp"),
    }
    for code, (public_address, mailbox_hash) in expected.items():
        assert channels[code].address == public_address
        assert channels[code].inbound_hash == mailbox_hash
        assert channels[code].inbound_forward_address == postmark_inbound_address(
            mailbox_hash
        )
    for code in {
        "seguradoras",
        "brokers",
        "departamento_financeiro",
        "reports",
        "administrativo",
        "suporte",
        "outros",
    }:
        assert channels[code].address is None
        assert channels[code].default_reply_address is None
        assert channels[code].inbound_hash is None
        assert channels[code].inbound_forward_address is None
    assert channels["outros"].requires_triage is True
    assert channels["outros"].administrative_review_on_unclassified is True


def test_postmark_mailbox_hash_routes_each_forwarded_mailbox_and_preserves_hub(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    public_by_hash = {
        "multas": "multas@carfast.pt",
        "oficina": "oficina@carfast.pt",
        "sinistros": "sinistros@carfast.pt",
        "vvp": "vvp@carfast.pt",
    }
    for mailbox_hash, public_address in public_by_hash.items():
        payload = _payload(f"pm-route-{mailbox_hash}")
        inbound_address = postmark_inbound_address(mailbox_hash)
        payload["To"] = inbound_address
        payload["ToFull"] = [
            {
                "Email": inbound_address,
                "Name": "",
                "MailboxHash": mailbox_hash,
            }
        ]
        payload["MailboxHash"] = mailbox_hash
        thread, created = ingest_inbound(db_session, payload)
        assert created is True
        assert db_session.get(EmailChannel, thread.channel_id).address == public_address

    historical = _payload("pm-route-hub-historical")
    historical_address = (
        f"{POSTMARK_INBOUND_LOCAL_PART}@{POSTMARK_INBOUND_DOMAIN}"
    )
    historical["To"] = historical_address
    historical["ToFull"] = [{"Email": historical_address, "Name": ""}]
    thread, _ = ingest_inbound(db_session, historical)
    channel = db_session.get(EmailChannel, thread.channel_id)
    assert channel.code == "test"
    assert channel.address == "hub@carfast.pt"


def test_postmark_top_level_mailbox_hash_routes_all_five_mailboxes(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    public_by_hash = {
        "hub": "hub@carfast.pt",
        "multas": "multas@carfast.pt",
        "oficina": "oficina@carfast.pt",
        "sinistros": "sinistros@carfast.pt",
        "vvp": "vvp@carfast.pt",
    }
    bare_inbound = f"{POSTMARK_INBOUND_LOCAL_PART}@{POSTMARK_INBOUND_DOMAIN}"
    for mailbox_hash, public_address in public_by_hash.items():
        payload = _payload(f"pm-top-level-{mailbox_hash}")
        payload["To"] = bare_inbound
        payload["ToFull"] = [{"Email": bare_inbound, "Name": ""}]
        payload["MailboxHash"] = mailbox_hash.upper()

        thread, created = ingest_inbound(db_session, payload)

        assert created is True
        assert db_session.get(EmailChannel, thread.channel_id).address == public_address


def test_postmark_tofull_mailbox_hash_routes_all_five_mailboxes(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    public_by_hash = {
        "hub": "hub@carfast.pt",
        "multas": "multas@carfast.pt",
        "oficina": "oficina@carfast.pt",
        "sinistros": "sinistros@carfast.pt",
        "vvp": "vvp@carfast.pt",
    }
    bare_inbound = f"{POSTMARK_INBOUND_LOCAL_PART}@{POSTMARK_INBOUND_DOMAIN}"
    for mailbox_hash, public_address in public_by_hash.items():
        payload = _payload(f"pm-tofull-{mailbox_hash}")
        payload["To"] = bare_inbound
        payload["ToFull"] = [
            {"Email": bare_inbound, "Name": "", "MailboxHash": mailbox_hash}
        ]
        payload.pop("MailboxHash", None)

        thread, created = ingest_inbound(db_session, payload)

        assert created is True
        assert db_session.get(EmailChannel, thread.channel_id).address == public_address


def test_postmark_exact_plus_address_routes_all_five_mailboxes_without_hash_fields(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    public_by_hash = {
        "hub": "hub@carfast.pt",
        "multas": "multas@carfast.pt",
        "oficina": "oficina@carfast.pt",
        "sinistros": "sinistros@carfast.pt",
        "vvp": "vvp@carfast.pt",
    }
    for mailbox_hash, public_address in public_by_hash.items():
        payload = _payload(f"pm-plus-address-{mailbox_hash}")
        inbound_address = postmark_inbound_address(mailbox_hash)
        payload["To"] = inbound_address
        payload["ToFull"] = [{"Email": inbound_address, "Name": ""}]
        payload.pop("MailboxHash", None)

        thread, created = ingest_inbound(db_session, payload)

        assert created is True
        assert db_session.get(EmailChannel, thread.channel_id).address == public_address


def test_postmark_top_level_mailbox_hash_has_priority_and_plus_ingest_is_idempotent(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    payload = _payload("pm-priority-idempotent")
    payload["To"] = postmark_inbound_address("oficina")
    payload["ToFull"] = [
        {
            "Email": postmark_inbound_address("oficina"),
            "Name": "",
            "MailboxHash": "oficina",
        }
    ]
    payload["MailboxHash"] = "multas"

    first_thread, first_created = ingest_inbound(db_session, payload)
    second_thread, second_created = ingest_inbound(db_session, payload)

    assert first_created is True
    assert second_created is False
    assert second_thread.id == first_thread.id
    assert db_session.get(EmailChannel, first_thread.channel_id).address == "multas@carfast.pt"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(EmailWebhookEvent)
            .where(EmailWebhookEvent.event_key == "message:pm-priority-idempotent")
        )
        == 1
    )


def test_postmark_unknown_mailbox_hash_does_not_fall_back_to_hub(
    db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    payload = _payload("pm-unknown-mailbox")
    payload["To"] = "unknown@inbound.postmarkapp.com"
    payload["ToFull"] = [
        {
            "Email": "unknown@inbound.postmarkapp.com",
            "Name": "",
            "MailboxHash": "unknown",
        }
    ]
    payload["MailboxHash"] = "unknown"

    try:
        ingest_inbound(db_session, payload)
    except ValueError as exc:
        assert "configured email channel" in str(exc)
    else:
        raise AssertionError("Unknown MailboxHash must not route to the hub")


def test_email_channel_sla_assignment_and_claim_are_independent(db_session):
    channels = {
        item.code: item for item in db_session.scalars(select(EmailChannel)).all()
    }
    channels["multas"].first_response_minutes = 15
    channels["multas"].resolution_minutes = 120
    channels["oficina"].first_response_minutes = 60
    channels["oficina"].resolution_minutes = 1440
    team = db_session.scalar(select(Team).where(Team.code == "operations"))
    user = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    db_session.add_all(
        [
            TeamMember(team_id=team.id, user_id=user.id),
            EmailExecutorEligibility(channel_id=channels["multas"].id, team_id=team.id),
        ]
    )
    channels["multas"].assignment_mode = "team_claim"
    channels["multas"].default_team_id = team.id
    db_session.flush()

    start = email_web.datetime(2026, 8, 20, 9, 0, tzinfo=email_web.UTC)
    multas_thread = EmailThread(
        channel_id=channels["multas"].id,
        subject="Multa recebida",
        status="triage",
    )
    oficina_thread = EmailThread(
        channel_id=channels["oficina"].id,
        subject="Pedido de oficina",
        status="triage",
    )
    db_session.add_all([multas_thread, oficina_thread])
    db_session.flush()
    initialize_email_operations(
        db_session, multas_thread, channel=channels["multas"], now=start
    )
    initialize_email_operations(
        db_session, oficina_thread, channel=channels["oficina"], now=start
    )

    assert multas_thread.assignment_state == "team_unclaimed"
    assert multas_thread.resolution_due_at != oficina_thread.resolution_due_at
    assert sla_snapshot(multas_thread, now=start).overall == "warning"
    claim_email_thread(db_session, multas_thread, user_id=user.id, now=start)
    assert multas_thread.assigned_to_id == user.id
    assert multas_thread.assignment_state == "assigned_user"


def test_postmark_outbound_uses_public_from_and_reply_to_for_every_mailbox(
    db_session, monkeypatch
):
    captured = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"MessageID":"pm-multi-box"}'

    def fake_urlopen(request, timeout):
        captured.append(json.loads(request.data))
        return Response()

    monkeypatch.setattr(settings, "email_outbound_enabled", True)
    monkeypatch.setattr(settings, "postmark_server_token", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    channels = list(
        db_session.scalars(
            select(EmailChannel)
            .where(EmailChannel.address.is_not(None))
            .order_by(EmailChannel.code)
        )
    )
    for index, channel in enumerate(channels, 1):
        message = EmailMessage(
            id=1000 + index,
            thread_id=2000 + index,
            direction="outbound",
            state="approved",
            sender=channel.address,
            recipients_json=[{"Email": "cliente@example.com"}],
            cc_json=[{"Email": "colega@example.org"}],
            subject="Teste por caixa",
            text_body="Mensagem",
        )
        send_message(message, channel.address, reply_to=channel.address)

    assert {(item["From"], item["ReplyTo"]) for item in captured} == {
        ("hub@carfast.pt", "hub@carfast.pt"),
        ("multas@carfast.pt", "multas@carfast.pt"),
        ("oficina@carfast.pt", "oficina@carfast.pt"),
        ("sinistros@carfast.pt", "sinistros@carfast.pt"),
        ("vvp@carfast.pt", "vvp@carfast.pt"),
    }
    assert {item["Cc"] for item in captured} == {"colega@example.org"}
