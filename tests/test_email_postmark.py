import base64

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

import app.web.email as email_web
from app.core.config import settings
from app.models.email import EmailAttachment, EmailMessage, EmailThread, EmailWebhookEvent
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
    assert "Preparar resposta" in detail.text
