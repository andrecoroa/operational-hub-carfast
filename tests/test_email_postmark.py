import base64

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import app.web.email as email_web
from app.core.config import settings
from app.models.admin import User
from app.models.email import (
    EmailAttachment,
    EmailChannelUser,
    EmailMessage,
    EmailThread,
    EmailWebhookEvent,
)
from app.services.email_postmark import ingest_inbound, webhook_authorized


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
    attachment = db_session.scalar(select(EmailAttachment))
    assert (
        tmp_path.joinpath(
            str(first_thread.id), str(attachment.message_id), "pedido.txt"
        ).read_bytes()
        == b"conteudo"
    )


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
    assert detail.status_code == 200
    assert "Responder" in detail.text
    assert "/v2-clean/email/messages/" in detail.text


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
        '<p>Olá <strong>CarFast</strong></p><script>alert(1)</script>'
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
