import base64
import json
import re
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

import app.web.email as email_web
from app.core.config import settings
from app.models.admin import User
from app.models.email import (
    EmailAttachment,
    EmailAuditEvent,
    EmailChannel,
    EmailMessage,
    EmailThread,
)
from app.models.work_hierarchy import WorkCategory, WorkDepartment, WorkQueue
from app.services.email_postmark import ingest_inbound, send_message
from app.services.users import create_user

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
    inbox = (ROOT / "app/templates/clean_email_inbox.html").read_text(encoding="utf-8")
    thread = (ROOT / "app/templates/clean_email_thread.html").read_text(encoding="utf-8")

    assert 'inlinePreviewRow = document.createElement("tr")' in script
    assert "sourceRow.after(inlinePreviewRow)" in script
    assert "await openPreview(shell.dataset.emailThreadId)" in script
    assert 'row.dataset.emailPreview === String(threadId)' in script
    assert 'dialog?.addEventListener("close"' in script
    assert "const restorePreviewFocus" in script
    assert "trigger.focus({preventScroll: true})" in script
    assert "if (trigger) previewTrigger = trigger" in script
    assert "!previewTrigger.isConnected" in script
    assert 'if (event.key !== "Escape") return' in script
    assert "closeActivePreview()" in script
    assert 'dialog?.addEventListener("cancel"' in script
    assert "event.preventDefault();\n    closeActivePreview();" in script
    assert "if (inlinePreviewRow?.dataset.emailInlineThread === String(threadId))" in script
    assert 'row.setAttribute("aria-expanded", String(selected))' in script
    assert 'dialog[open]:not(#email-preview-dialog)' in script
    assert "email.js?v=20260901-email-mobile-focus" in inbox
    assert "email.js?v=20260901-email-mobile-focus" in thread


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


def test_email_work_views_group_without_duplicates_and_mine_stays_scoped(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    _bind_email_session(monkeypatch, db_session)
    admin = db_session.scalar(
        select(User).where(User.email == "admin.tests@carfast.local")
    )
    other_user = create_user(
        db_session,
        name="Outro Executor",
        email="outro.executor.email@carfast.local",
        password="SyntheticOnly123!",
        role_codes=["operator"],
        organizational_unit_codes=["carfast"],
    )
    db_session.flush()
    channels = list(db_session.scalars(select(EmailChannel).order_by(EmailChannel.id)))
    mine_payload = _payload("view-mine")
    mine_payload["Subject"] = "Conversa atribuída ao utilizador"
    mine, _ = ingest_inbound(db_session, mine_payload)
    mine.assigned_to_id = admin.id
    mine.assignment_state = "assigned_user"
    mine.status = "in_progress"
    other_payload = _payload("view-other")
    other_payload["Subject"] = "Conversa atribuída a outra pessoa"
    other, _ = ingest_inbound(db_session, other_payload)
    other.assigned_to_id = other_user.id
    other.assignment_state = "assigned_user"
    unassigned_payload = _payload("view-unassigned")
    unassigned_payload["Subject"] = "Conversa noutra caixa"
    unassigned, _ = ingest_inbound(db_session, unassigned_payload)
    if len(channels) > 1:
        unassigned.channel_id = channels[1].id
    db_session.commit()

    first_access = authenticated_client.get("/v2-clean/email?status=all")
    mailbox = authenticated_client.get(
        "/v2-clean/email?view=mailbox&status=all&q=Conversa"
    )
    mine_view = authenticated_client.get("/v2-clean/email?view=mine&status=all")
    restored = authenticated_client.get("/v2-clean/email?status=all")
    all_view = authenticated_client.get("/v2-clean/email?view=all&status=all")

    assert 'data-email-work-view="mailbox"' in first_access.text
    assert 'aria-current="page">Por caixa</a>' in mailbox.text
    assert f'data-email-preview="{mine.id}"' not in mailbox.text
    assert f'data-email-preview="{other.id}"' not in mailbox.text
    assert f'data-email-preview="{unassigned.id}"' not in mailbox.text
    assert mailbox.text.count("Abrir caixa") >= 1
    assert "novas" in mailbox.text and "por tratar" in mailbox.text
    assert 'data-email-work-view="mine"' in mine_view.text
    assert mine.subject in mine_view.text
    assert other.subject not in mine_view.text
    assert unassigned.subject not in mine_view.text
    assert "Em tratamento" in mine_view.text
    assert 'data-email-work-view="mine"' in restored.text
    assert 'data-email-work-view="all"' in all_view.text
    assert all_view.text.count(f'data-email-preview="{mine.id}"') == 1
    assert 'name="view" value="all"' in all_view.text


def test_email_body_keeps_safe_links_and_removes_active_content(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    payload = _payload("safe-links")
    payload["HtmlBody"] = (
        '<a href="https://example.com/path" onclick="alert(1)">Externo</a>'
        '<a href="mailto:cliente@example.com">Email</a>'
        '<a href="/v2-clean/documents/7">Documento interno</a>'
        '<a href="javascript:alert(2)">Javascript</a>'
        '<a href="data:text/html,bad">Data</a>'
        '<script>segredo-script</script><style>segredo-css</style>'
        '<iframe src="https://example.com">segredo-frame</iframe>'
    )
    thread, _ = ingest_inbound(db_session, payload)
    message = db_session.scalar(
        select(EmailMessage).where(EmailMessage.thread_id == thread.id)
    )
    db_session.commit()

    body = authenticated_client.get(f"/v2-clean/email/messages/{message.id}/body")

    assert body.status_code == 200
    assert (
        'href="https://example.com/path" target="_blank" '
        'rel="noopener noreferrer"' in body.text
    )
    assert 'href="mailto:cliente@example.com"' in body.text
    assert 'href="/v2-clean/documents/7"' in body.text
    assert "onclick" not in body.text
    assert "javascript:" not in body.text
    assert "data:text/html" not in body.text
    assert "segredo-script" not in body.text
    assert "segredo-css" not in body.text
    assert "segredo-frame" not in body.text


def test_embedded_image_classification_uses_persisted_mime_evidence_only():
    message = EmailMessage(
        thread_id=1,
        direction="inbound",
        sender="sender@example.invalid",
        subject="MIME",
        html_body='<p>Olá</p><img src="cid:signature-logo">',
        headers_json=[],
    )
    cid_image = EmailAttachment(
        message_id=1,
        file_name="logo.png",
        content_type="image/png",
        content_id="<signature-logo>",
        storage_path="synthetic/logo.png",
        sha256="a" * 64,
    )
    real_image = EmailAttachment(
        message_id=1,
        file_name="damage.jpg",
        content_type="image/jpeg",
        storage_path="synthetic/damage.jpg",
        sha256="b" * 64,
    )
    document = EmailAttachment(
        message_id=1,
        file_name="invoice.pdf",
        content_type="application/pdf",
        storage_path="synthetic/invoice.pdf",
        sha256="c" * 64,
    )

    assert email_web._is_embedded_email_image(message, cid_image, repeated_hash=False)
    assert not email_web._is_embedded_email_image(message, real_image, repeated_hash=False)
    assert email_web._is_embedded_email_image(message, real_image, repeated_hash=True)
    assert not email_web._is_embedded_email_image(message, document, repeated_hash=True)


def test_embedded_image_classification_honours_persisted_inline_disposition():
    message = EmailMessage(
        thread_id=1,
        direction="inbound",
        sender="sender@example.invalid",
        subject="MIME",
        headers_json=[
            {"Name": "Content-Disposition", "Value": 'inline; filename="footer.png"'}
        ],
    )
    attachment = EmailAttachment(
        message_id=1,
        file_name="footer.png",
        content_type="image/png",
        storage_path="synthetic/footer.png",
        sha256="d" * 64,
    )

    assert email_web._is_embedded_email_image(
        message, attachment, repeated_hash=False
    )


def test_group_views_keep_exact_counts_and_do_not_hide_a_group_after_one_hundred(
    authenticated_client, db_session, monkeypatch
):
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    _bind_email_session(monkeypatch, db_session)
    admin = db_session.scalar(
        select(User).where(User.email == "admin.tests@carfast.local")
    )
    channels = list(db_session.scalars(select(EmailChannel).order_by(EmailChannel.id)))
    assert len(channels) > 1
    bulk_threads = [
        EmailThread(
            channel_id=channels[0].id,
            subject=f"Escala agrupada {index:03d}",
            status="triage",
            assigned_to_id=admin.id,
            assignment_state="assigned_user",
        )
        for index in range(101)
    ]
    other_group = EmailThread(
        channel_id=channels[1].id,
        subject="Escala agrupada noutra caixa",
        status="new_reply",
        assigned_to_id=admin.id,
        assignment_state="assigned_user",
    )
    db_session.add_all([*bulk_threads, other_group])
    db_session.commit()

    mailbox = authenticated_client.get(
        "/v2-clean/email?view=mailbox&status=all&q=Escala+agrupada"
    )
    mine = authenticated_client.get(
        "/v2-clean/email?view=mine&status=all&q=Escala+agrupada"
    )

    assert mailbox.status_code == 200
    assert mailbox.text.count("101 conversa(s) nos filtros atuais") == 1
    assert "100 mais recentes" not in mailbox.text
    assert other_group.subject not in mailbox.text
    assert mailbox.text.count('data-email-preview="') == 0
    assert mine.status_code == 200
    assert mine.text.count("101 total") == 1
    assert "100 mais recentes" in mine.text
    assert "Nova resposta" in mine.text
    assert mine.text.count('data-email-preview="') == 101
    all_view = authenticated_client.get(
        "/v2-clean/email?view=all&status=all&q=Escala+agrupada"
    )
    assert all_view.text.count('data-email-preview="') == 100
    assert "A mostrar as 100 conversas mais recentes." in all_view.text


def test_outbound_off_rejects_send_before_any_durable_mutation(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "email_outbound_enabled", False)
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("outbound-off-atomic"))
    db_session.commit()
    before_threads = len(db_session.scalars(select(email_web.EmailThread)).all())
    before_messages = len(db_session.scalars(select(EmailMessage)).all())

    reply = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={"submit": "send", "body": "Resposta sintética"},
        follow_redirects=False,
    )
    compose = authenticated_client.post(
        "/v2-clean/email/new",
        data={"submit": "send", "channel_id": thread.channel_id},
        follow_redirects=False,
    )

    assert "error=send_disabled" in reply.headers["location"]
    assert "error=send_disabled" in compose.headers["location"]
    assert len(db_session.scalars(select(email_web.EmailThread)).all()) == before_threads
    assert len(db_session.scalars(select(EmailMessage)).all()) == before_messages

    approval_request = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={"submit": "approval", "body": "Resposta sintética a validar"},
        follow_redirects=False,
    )
    assert approval_request.status_code == 303
    pending = db_session.scalar(
        select(EmailMessage)
        .where(EmailMessage.thread_id == thread.id, EmailMessage.direction == "outbound")
        .order_by(EmailMessage.id.desc())
    )
    assert pending is not None and pending.state == "pending_approval"
    before_audits = len(db_session.scalars(select(EmailAuditEvent)).all())

    approve = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/messages/{pending.id}/approve",
        follow_redirects=False,
    )

    assert "error=send_disabled" in approve.headers["location"]
    db_session.refresh(pending)
    assert pending.state == "pending_approval"
    assert pending.postmark_error is None
    assert len(db_session.scalars(select(EmailAuditEvent)).all()) == before_audits


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

    send_message(
        message,
        '"CarFast — HUB" <hub@carfast.pt>',
        reply_to="hub@carfast.pt",
        attachments=[attachment],
    )

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


def test_text_attachment_preview_and_classification_are_safe_and_audited(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    payload = _payload("preview-text-attachment")
    payload["Attachments"] = [
        {
            "Name": "comprovativo-sintetico.txt",
            "ContentType": "text/plain",
            "Content": base64.b64encode(
                b"COMPROVATIVO SINTETICO\nSem dados reais.\n"
            ).decode(),
            "ContentID": "",
        }
    ]
    thread, _ = ingest_inbound(db_session, payload)
    attachment = db_session.scalar(select(EmailAttachment))

    preview = authenticated_client.get(
        f"/v2-clean/email/attachments/{attachment.id}/file"
    )
    preview_panel = authenticated_client.get(
        f"/v2-clean/email/attachments/{attachment.id}/preview"
    )
    forged = authenticated_client.post(
        f"/v2-clean/email/attachments/{attachment.id}/classify",
        data={"status": "forged"},
    )
    db_session.expire_all()
    assert db_session.get(EmailAttachment, attachment.id).status == "pending"
    download = authenticated_client.get(
        f"/v2-clean/email/attachments/{attachment.id}/file?download=true"
    )
    classified = authenticated_client.post(
        f"/v2-clean/email/attachments/{attachment.id}/classify",
        data={
            "document_type": "receipt",
            "nature": "operational",
            "destination": "operational",
            "status": "classified",
            "notes": "Fixture sintética validada.",
        },
    )
    db_session.expire_all()
    stored = db_session.get(EmailAttachment, attachment.id)
    audit = db_session.scalar(
        select(EmailAuditEvent)
        .where(
            EmailAuditEvent.thread_id == thread.id,
            EmailAuditEvent.action == "attachment_classified",
        )
        .order_by(EmailAuditEvent.id.desc())
    )

    assert preview.status_code == 200
    assert "COMPROVATIVO SINTETICO" in preview.text
    assert "default-src 'none'" in preview.headers["content-security-policy"]
    assert "Abrir ficheiro" in preview_panel.text
    assert f"/attachments/{attachment.id}/file?download=true" in preview_panel.text
    assert "Descarregar" in preview_panel.text
    assert forged.status_code == 422
    assert download.status_code == 200
    assert download.content.startswith(b"COMPROVATIVO SINTETICO")
    assert "attachment;" in download.headers["content-disposition"]
    assert classified.status_code == 200
    assert stored.document_type == "receipt"
    assert stored.status == "classified"
    assert stored.notes == "Fixture sintética validada."
    assert audit is not None
    assert audit.details_json["attachment_id"] == attachment.id


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
    labels = [
        "Guardar triagem",
        "Validar classificação",
        "Arquivar",
        "Responder",
        "Criar tarefa",
    ]
    positions = [footer.index(label) for label in labels]
    assert positions == sorted(positions)
    assert preview.text.count("Fechar preview") == 1
    assert 'class="secondary email-modal-close"' in preview.text
    assert "Atribua apenas se a conversa exigir acompanhamento como trabalho" in preview.text
    assert 'name="action" value="save"' in footer
    assert 'name="action" value="validate"' in footer
    assert "Concluir triagem" not in footer
    assert "Marcar como lido" in preview.text
    assert "Texto original" in preview.text
    assert plain.status_code == 200
    assert "Texto original simples." in plain.text
    assert "<strong>formatado</strong>" not in plain.text
    assert marked.status_code == 303
    assert db_session.get(EmailMessage, message.id).state == "read"


def test_triage_actions_fail_closed_before_mutation(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("preview-triage-actions"))
    initial_audits = len(db_session.scalars(select(EmailAuditEvent)).all())

    forged = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={"action": "complete", "triage_notes": "não persistir"},
        follow_redirects=False,
    )
    missing = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={"action": "validate", "triage_notes": "não validar"},
        follow_redirects=False,
    )
    db_session.expire_all()
    stored = db_session.get(EmailThread, thread.id)

    assert "error=action_not_supported" in forged.headers["location"]
    assert "error=missing_classification" in missing.headers["location"]
    assert stored.triage_notes is None
    assert stored.status == "triage"
    assert len(db_session.scalars(select(EmailAuditEvent)).all()) == initial_audits


def test_validate_classification_is_explicit_and_audited(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("preview-validate-classification"))
    queue = WorkQueue(code="email-validate", name="Fila validação", active=True)
    db_session.add(queue)
    db_session.flush()
    department = WorkDepartment(
        queue_id=queue.id,
        code="email-validate-dept",
        name="Departamento validação",
        active=True,
    )
    db_session.add(department)
    db_session.flush()
    category = WorkCategory(
        department_id=department.id,
        code="email-validate-category",
        name="Categoria validada",
        active=True,
    )
    db_session.add(category)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={
            "action": "validate",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
        },
        follow_redirects=False,
    )
    db_session.expire_all()
    stored = db_session.get(EmailThread, thread.id)
    audit = db_session.scalar(
        select(EmailAuditEvent)
        .where(
            EmailAuditEvent.thread_id == thread.id,
            EmailAuditEvent.action == "classification_validated",
        )
        .order_by(EmailAuditEvent.id.desc())
    )

    assert "saved=validate" in response.headers["location"]
    assert stored.classification_status == "classified"
    assert stored.status == "in_progress"
    assert audit is not None

    saved_after_validation = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={
            "action": "save",
            "triage_notes": "alteração posterior à validação",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
        },
        follow_redirects=False,
    )
    stale_archive = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/status",
        data={"status": "archived"},
        follow_redirects=False,
    )
    db_session.expire_all()

    assert "saved=save" in saved_after_validation.headers["location"]
    assert "error=invalid_transition" in stale_archive.headers["location"]
    assert db_session.get(EmailThread, thread.id).status == "in_progress"

    revalidated = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/triage",
        data={
            "action": "validate",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
        },
        follow_redirects=False,
    )
    archived = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/status",
        data={"status": "archived"},
        follow_redirects=False,
    )
    db_session.expire_all()
    archive_audit = db_session.scalar(
        select(EmailAuditEvent)
        .where(
            EmailAuditEvent.thread_id == thread.id,
            EmailAuditEvent.action == "status_changed",
        )
        .order_by(EmailAuditEvent.id.desc())
    )

    assert "saved=validate" in revalidated.headers["location"]
    assert "saved=status" in archived.headers["location"]
    assert db_session.get(EmailThread, thread.id).status == "archived"
    assert archive_audit is not None
    assert archive_audit.details_json["status"] == "archived"


def test_archive_requires_explicit_classification_validation(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "email_storage_root", str(tmp_path))
    _bind_email_session(monkeypatch, db_session)
    thread, _ = ingest_inbound(db_session, _payload("preview-archive-sequence"))
    initial_audits = len(db_session.scalars(select(EmailAuditEvent)).all())

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/status",
        data={"status": "archived"},
        follow_redirects=False,
    )
    db_session.expire_all()
    stored = db_session.get(EmailThread, thread.id)

    assert "error=invalid_transition" in response.headers["location"]
    assert stored.status == "triage"
    assert stored.classification_status != "classified"
    assert len(db_session.scalars(select(EmailAuditEvent)).all()) == initial_audits

    stored.classification_status = "classified"
    stored.status = "waiting_reply"
    db_session.commit()
    bypass = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/status",
        data={"status": "archived"},
        follow_redirects=False,
    )
    db_session.expire_all()

    assert "error=invalid_transition" in bypass.headers["location"]
    assert db_session.get(EmailThread, thread.id).status == "waiting_reply"
    assert len(db_session.scalars(select(EmailAuditEvent)).all()) == initial_audits


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


def test_desktop_preview_is_inline_below_the_selected_row():
    css = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
    app_css = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")
    script = (ROOT / "app/static/js/email.js").read_text(encoding="utf-8")

    assert ".email-inline-preview-row > td" in css
    assert ".email-inline-preview-body" in css
    assert 'inlinePreviewRow = document.createElement("tr")' in script
    assert "sourceRow.after(inlinePreviewRow)" in script
    assert "cell.colSpan = sourceRow.children.length || 7" in script
    assert ".email-attachment-form footer { display:grid; grid-template-columns:repeat(2,minmax(0,1fr));" in app_css
    assert ".email-attachment-form footer > button { grid-column:1/-1; }" in app_css


def test_desktop_email_first_fold_reserves_space_for_message_and_triage():
    css = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")

    assert ".visual-email-heading { height:48px; min-height:48px; padding-block:4px; }" in css
    assert ".visual-email-metrics > a { min-height:48px; height:48px;" in css
    assert ".ui-context-preview .email-body-frame { display:block; height:clamp(96px,18vh,180px); min-height:96px;" in css
    assert ".ui-context-preview .email-triage-pane { height:auto; max-height:none;" in css
    assert ".ui-context-preview .email-modal-footer { position:sticky;" in css
