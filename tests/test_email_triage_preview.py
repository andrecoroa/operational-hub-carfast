import base64
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.web.email as email_web
from app.core.config import settings
from app.models.admin import User
from app.models.email import EmailAttachment, EmailMessage
from app.models.work_hierarchy import WorkDepartment, WorkQueue
from app.services.email_postmark import ingest_inbound, send_message

ROOT = Path(__file__).parents[1]


def _payload(message_id: str, *, attachment_name: str | None = None) -> dict:
    attachments = []
    if attachment_name:
        attachments.append(
            {
                "Name": attachment_name,
                "ContentType": "application/zip",
                "Content": base64.b64encode(b"not-a-preview").decode(),
                "ContentID": "",
            }
        )
    return {
        "MessageID": message_id,
        "MailboxHash": "hub",
        "OriginalRecipient": "apoio@carfast.pt",
        "From": "Cliente <cliente@example.com>",
        "FromName": "Cliente",
        "To": "hub@carfast.pt",
        "ToFull": [{"Email": "hub@carfast.pt", "Name": "CarFast"}],
        "CcFull": [{"Email": "externo@example.org", "Name": "Externo"}],
        "Subject": "Preview de triagem",
        "TextBody": "Texto original simples.",
        "HtmlBody": "<p>Texto <strong>formatado</strong>.</p>",
        "Headers": [],
        "Attachments": attachments,
    }


def _bind_email_session(monkeypatch, db_session) -> None:
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )


def test_preview_actions_refresh_without_closing_or_losing_selected_thread():
    script = (ROOT / "app/static/js/email.js").read_text(encoding="utf-8")

    assert "if (!dialog.open) dialog.showModal()" in script
    assert "await openPreview(shell.dataset.emailThreadId)" in script
    assert 'row.dataset.emailPreview === String(threadId)' in script
    assert 'dialog?.addEventListener("close"' in script


def test_inbox_facets_apply_remaining_filters_server_side(authenticated_client, db_session, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    _bind_email_session(monkeypatch, db_session)
    admin = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    first_payload = _payload("facet-triage-assigned")
    first_payload["Subject"] = "Facet assigned"
    second_payload = _payload("facet-triage-unassigned")
    second_payload["Subject"] = "Facet unassigned"
    waiting_payload = _payload("facet-waiting-unassigned")
    waiting_payload["Subject"] = "Facet waiting"
    first, _ = ingest_inbound(db_session, first_payload)
    second, _ = ingest_inbound(db_session, second_payload)
    waiting, _ = ingest_inbound(db_session, waiting_payload)
    first.assigned_to_id = admin.id
    first.assignment_state = "assigned_user"
    second.executor_team_id = None
    second.assignment_state = "waiting_assignment"
    waiting.executor_team_id = None
    waiting.assignment_state = "waiting_assignment"
    waiting.status = "waiting_reply"
    db_session.commit()

    response = authenticated_client.get("/v2-clean/email?status=all&responsible=unassigned")

    assert response.status_code == 200
    assert re.findall(r"\d+ resultado\(s\) com todos os filtros ativos", response.text) == [
        "2 resultado(s) com todos os filtros ativos"
    ]
    assert '<strong>1</strong><span>Por triar</span>' in response.text
    assert '<strong>1</strong><span>Resposta pendente</span>' in response.text
    assert 'class="email-secondary-filters"' in response.text
    assert 'aria-label="Estados das conversas"' not in response.text


def test_hierarchy_only_renders_active_options_and_server_rejects_cross_branch_selection(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("preview-hierarchy"))
    active_queue = WorkQueue(code="preview-active", name="Fila ativa preview", active=True)
    other_queue = WorkQueue(code="preview-other", name="Fila alternativa preview", active=True)
    inactive_queue = WorkQueue(
        code="preview-inactive", name="Fila inativa escondida", active=False
    )
    db_session.add_all([active_queue, other_queue, inactive_queue])
    db_session.flush()
    other_department = WorkDepartment(
        queue_id=other_queue.id,
        code="preview-other-dept",
        name="Departamento de outra fila",
        active=True,
    )
    db_session.add(other_department)
    db_session.commit()

    preview = authenticated_client.get(f"/v2-clean/email/{thread.id}/preview")
    rejected = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={
            "work_queue_id": str(active_queue.id),
            "work_department_id": str(other_department.id),
        },
        follow_redirects=False,
    )

    assert preview.status_code == 200
    assert "Fila ativa preview" in preview.text
    assert "Fila inativa escondida" not in preview.text
    assert 'data-work-level="queue"' in preview.text
    assert 'data-work-level="subcategory"' in preview.text
    assert "error=invalid_hierarchy" in rejected.headers["location"]


def test_ineligible_executor_is_rejected_by_server(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("preview-eligibility"))
    outsider = User(
        name="Executor não elegível",
        email="not-eligible@example.test",
        password_hash="unused",
        active=True,
    )
    db_session.add(outsider)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={"assigned_to_id": str(outsider.id)},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=assignment_not_allowed" in response.headers["location"]
    db_session.refresh(thread)
    assert thread.assigned_to_id is None


def test_reply_all_mode_and_mailbox_policy_controls_are_present():
    template = (ROOT / "app/templates/_email_thread_content.html").read_text(
        encoding="utf-8"
    )
    script = (ROOT / "app/static/js/email.js").read_text(encoding="utf-8")

    assert 'data-email-compose-mode="reply_all"' in template
    assert "data-reply-all-to" in template and "data-reply-all-cc" in template
    assert 'mode === "reply_all" ? replyAllTo.join(", ")' in script
    assert "can_change_sender" in template
    assert "can_edit_recipients" in template
    assert "can_use_cc_bcc" in template


def test_reply_attachment_is_stored_with_draft(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("preview-reply-attachment"))

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={
            "body": "Segue o documento pedido.",
            "recipients": "cliente@example.com",
            "submit": "draft",
        },
        files={"attachments": ("resposta.txt", b"conteudo", "text/plain")},
        follow_redirects=False,
    )
    db_session.expire_all()
    outbound = db_session.scalar(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == "outbound",
        )
    )
    attachment = db_session.scalar(
        select(EmailAttachment).where(EmailAttachment.message_id == outbound.id)
    )

    assert response.status_code == 303
    assert outbound.state == "draft"
    assert attachment.file_name == "resposta.txt"
    assert Path(attachment.storage_path).read_bytes() == b"conteudo"


def test_postmark_payload_includes_stored_reply_attachment(tmp_path, monkeypatch):
    captured = {}
    stored_file = tmp_path / "resposta.txt"
    stored_file.write_bytes(b"conteudo")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"MessageID":"pm-with-attachment"}'

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr(settings, "email_outbound_enabled", True)
    monkeypatch.setattr(settings, "postmark_server_token", "test-token")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    message = EmailMessage(
        id=101,
        thread_id=202,
        direction="outbound",
        state="approved",
        sender="hub@carfast.pt",
        recipients_json=[{"Email": "cliente@example.com"}],
        subject="Resposta com anexo",
        text_body="Segue em anexo.",
    )
    attachment = EmailAttachment(
        id=303,
        message_id=101,
        file_name="resposta.txt",
        content_type="text/plain",
        size=8,
        storage_path=str(stored_file),
        sha256="0" * 64,
    )

    send_message(message, message.sender, attachments=[attachment])

    assert captured["timeout"] == 20
    assert captured["body"]["Attachments"] == [
        {
            "Name": "resposta.txt",
            "Content": base64.b64encode(b"conteudo").decode(),
            "ContentType": "text/plain",
        }
    ]


def test_attachment_preview_is_explicit_and_unsupported_file_does_not_auto_download(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(
        db_session, _payload("preview-attachment", attachment_name="arquivo.zip")
    )
    attachment = db_session.scalar(select(EmailAttachment))

    conversation = authenticated_client.get(f"/v2-clean/email/{thread.id}/preview")
    attachment_preview = authenticated_client.get(
        f"/v2-clean/email/attachments/{attachment.id}/preview"
    )
    implicit_file = authenticated_client.get(
        f"/v2-clean/email/attachments/{attachment.id}/file"
    )

    assert f'data-email-attachment-preview="{attachment.id}"' in conversation.text
    assert f'/attachments/{attachment.id}/file"' not in conversation.text
    assert f'/attachments/{attachment.id}/file?download=true' in attachment_preview.text
    iframe_source = f'<iframe src="/v2-clean/email/attachments/{attachment.id}/file"'
    assert iframe_source not in attachment_preview.text
    assert implicit_file.status_code == 415


def test_header_footer_order_read_action_and_original_text(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("preview-actions"))
    message = db_session.scalar(select(EmailMessage).where(EmailMessage.thread_id == thread.id))

    preview = authenticated_client.get(f"/v2-clean/email/{thread.id}/preview")
    plain = authenticated_client.get(
        f"/v2-clean/email/messages/{message.id}/body?view=text"
    )
    marked = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/read", follow_redirects=False
    )
    db_session.expire_all()

    footer = preview.text.split('<footer class="email-modal-footer">', 1)[1]
    labels = ["Arquivar", "Criar tarefa", "Guardar triagem", "Responder", "Concluir triagem"]
    positions = [footer.index(label) for label in labels]
    assert positions == sorted(positions)
    assert "Marcar como lido" in preview.text
    assert "Texto original" in preview.text
    assert plain.status_code == 200
    assert "Texto original simples." in plain.text
    assert "<strong>formatado</strong>" not in plain.text
    assert marked.status_code == 303
    assert db_session.get(EmailMessage, message.id).state == "read"


def test_mobile_layout_is_single_column_without_body_overflow():
    css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")

    assert "body:has(.email-preview-dialog[open]) { overflow: hidden; }" in css
    assert ".email-preview-dialog { width:100vw; height:100dvh" in css
    mobile_grid = (
        ".email-reader-grid,.email-modal-shell.is-composing .email-reader-grid "
        "{ display:grid; grid-template-columns:1fr; overflow:auto; }"
    )
    assert mobile_grid in css
    assert ".email-modal-footer { position:relative;" in css
