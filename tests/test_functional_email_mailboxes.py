from copy import deepcopy

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from app.models.admin import Role, User, UserRole
from app.models.email import (
    EmailChannel,
    EmailChannelAlias,
    EmailChannelRole,
    EmailChannelTransport,
    EmailMessage,
    EmailMessageDelivery,
    EmailTemplate,
    EmailThread,
)
from app.models.work_hierarchy import (
    WorkCategory,
    WorkDepartment,
    WorkQueue,
    WorkSubcategory,
)
from app.services.bootstrap import seed_email_channels
from app.services.email_postmark import ingest_inbound
from app.services.email_transport import (
    OutboundIdentityError,
    resolve_outbound_identity,
    send_channel_message,
)
from app.web import email as email_web
from app.web.email import (
    _channel_access,
    _message_fingerprint,
    _ranked_email_templates,
    _render_email_template,
    _reply_defaults,
)

FUNCTIONAL_CODES = {
    "seguradoras",
    "brokers",
    "departamento_financeiro",
    "reports",
    "administrativo",
    "suporte",
    "outros",
}


def _identity_channel(db_session, code: str, *, policy: str = "original") -> EmailChannel:
    channel = EmailChannel(
        code=code,
        name=code.title(),
        from_name="CarFast",
        from_address=f"{code}@example.test",
        reply_to_address=f"{code}@example.test",
        reply_policy=policy,
        active=True,
    )
    db_session.add(channel)
    db_session.flush()
    return channel


def test_original_reply_identity_uses_only_active_alias_of_same_channel(db_session):
    channel = _identity_channel(db_session, "functional-original")
    other = _identity_channel(db_session, "functional-other")
    db_session.add_all(
        [
            EmailChannelAlias(
                channel_id=channel.id,
                address="received@example.test",
                inbound_forward_address="technical@inbound.example.test",
                active=True,
            ),
            EmailChannelAlias(
                channel_id=other.id,
                address="other@example.test",
                active=True,
            ),
        ]
    )
    db_session.flush()

    thread = EmailThread(
        channel_id=channel.id,
        subject="Alias",
        original_recipient_address="RECEIVED@example.test",
    )
    identity = resolve_outbound_identity(db_session, channel, thread)
    assert identity.sender_address == "received@example.test"
    assert identity.reply_to_address == "received@example.test"
    assert identity.transport_sender == '"CarFast" <received@example.test>'

    for invalid in (
        None,
        "technical@inbound.example.test",
        "other@example.test",
        "arbitrary@example.test",
    ):
        thread.original_recipient_address = invalid
        try:
            resolve_outbound_identity(db_session, channel, thread)
        except OutboundIdentityError as exc:
            assert exc.code in {
                "original_sender_unavailable",
                "original_sender_not_authorized",
            }
        else:
            raise AssertionError(f"Expected {invalid!r} to be rejected")


def test_original_reply_identity_rejects_inactive_alias_and_new_message(db_session):
    channel = _identity_channel(db_session, "functional-inactive")
    alias = EmailChannelAlias(
        channel_id=channel.id,
        address="inactive@example.test",
        active=False,
    )
    db_session.add(alias)
    db_session.flush()
    thread = EmailThread(
        channel_id=channel.id,
        subject="Alias inativo",
        original_recipient_address=alias.address,
    )

    for candidate in (thread, None):
        try:
            resolve_outbound_identity(db_session, channel, candidate)
        except OutboundIdentityError as exc:
            assert exc.code in {
                "original_sender_unavailable",
                "original_sender_not_authorized",
            }
        else:
            raise AssertionError("Expected original policy to fail closed")


def test_mailbox_reply_identity_preserves_configured_sender(db_session):
    channel = _identity_channel(db_session, "mailbox-policy", policy="mailbox")
    identity = resolve_outbound_identity(db_session, channel, None)
    assert identity.sender_address == "mailbox-policy@example.test"
    assert identity.reply_to_address == "mailbox-policy@example.test"


def test_microsoft365_original_alias_is_explicit_sender(db_session, monkeypatch):
    from app.services import email_transport

    monkeypatch.setattr(email_transport.settings, "microsoft365_email_enabled", True)
    channel = _identity_channel(db_session, "m365-original")
    alias = EmailChannelAlias(
        channel_id=channel.id,
        address="alias@example.test",
        active=True,
    )
    db_session.add_all(
        [
            alias,
            EmailChannelTransport(
                channel_id=channel.id,
                provider="microsoft365",
                enabled=True,
                mailbox_address="technical-mailbox@example.test",
                tenant_id="tenant",
                client_id="client",
                client_credential_reference="env://secret",
                token_reference="db://token",
            ),
        ]
    )
    db_session.flush()
    thread = EmailThread(
        channel_id=channel.id,
        subject="M365 alias",
        original_recipient_address=alias.address,
    )
    identity = resolve_outbound_identity(db_session, channel, thread)
    calls = []
    message = EmailMessage(
        thread_id=thread.id,
        direction="outbound",
        state="approved",
        sender=identity.sender_address,
        recipients_json=[{"Email": "external@example.test"}],
        subject="Resposta",
    )
    result = send_channel_message(
        db_session,
        channel,
        message,
        identity.transport_sender,
        reply_to=identity.reply_to_address,
        microsoft365_sender=lambda supplied, **kwargs: calls.append(kwargs)
        or {"Provider": "microsoft365"},
    )
    assert result["Provider"] == "microsoft365"
    assert calls[0]["mailbox_address"] == "technical-mailbox@example.test"
    assert calls[0]["sender_address"] == "alias@example.test"
    assert calls[0]["reply_to"] == "alias@example.test"


def test_microsoft365_original_sender_selects_matching_physical_transport(
    db_session, monkeypatch
):
    from app.services import email_transport

    monkeypatch.setattr(email_transport.settings, "microsoft365_email_enabled", True)
    channel = _identity_channel(db_session, "multi-m365")
    channel.reply_policy = "original"
    aliases = [
        EmailChannelAlias(channel_id=channel.id, address=address, active=True)
        for address in ("backoffice@example.test", "contratos@example.test")
    ]
    transports = [
        EmailChannelTransport(
            channel_id=channel.id,
            provider="microsoft365",
            enabled=True,
            mailbox_address=address,
            tenant_id="tenant",
            client_id="client",
            client_credential_reference="env://secret",
            token_reference=f"db://{address}",
        )
        for address in ("backoffice@example.test", "contratos@example.test")
    ]
    db_session.add_all([*aliases, *transports])
    db_session.flush()
    thread = EmailThread(
        channel_id=channel.id,
        subject="Contrato",
        original_recipient_address="contratos@example.test",
    )
    identity = resolve_outbound_identity(db_session, channel, thread)
    calls = []
    message = EmailMessage(
        thread_id=thread.id,
        direction="outbound",
        state="approved",
        sender=identity.sender_address,
        recipients_json=[{"Email": "external@example.test"}],
        subject="Resposta",
    )

    send_channel_message(
        db_session,
        channel,
        message,
        identity.transport_sender,
        reply_to=identity.reply_to_address,
        microsoft365_sender=lambda supplied, **kwargs: calls.append(kwargs)
        or {"Provider": "microsoft365"},
    )

    assert calls[0]["mailbox_address"] == "contratos@example.test"
    assert calls[0]["sender_address"] == "contratos@example.test"


def test_reply_route_persists_original_alias_and_blocks_arbitrary_sender(
    authenticated_client, db_session, monkeypatch
):
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    thread, _ = ingest_inbound(db_session, _payload("original-route"))
    channel = db_session.get(EmailChannel, thread.channel_id)
    channel.reply_policy = "original"
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={"body": "Resposta em rascunho.", "submit": "draft"},
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("saved=draft")
    draft = db_session.scalar(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == "outbound",
        )
        .order_by(EmailMessage.id.desc())
    )
    assert draft.sender == "multas@carfast.pt"

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={
            "body": "Tentativa inválida.",
            "sender_address": "arbitrary@example.test",
            "submit": "draft",
        },
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("error=forbidden")

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={"body": "Resposta para aprovação.", "submit": "approval"},
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("saved=pending_approval")
    pending = db_session.scalar(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.state == "pending_approval",
        )
        .order_by(EmailMessage.id.desc())
    )
    sent = []

    def fake_send_channel_message(*args, **kwargs):
        sent.append((args[3], kwargs["reply_to"]))
        return {"MessageID": "test-message-id"}

    monkeypatch.setattr(email_web, "send_channel_message", fake_send_channel_message)
    monkeypatch.setattr(email_web, "outbound_enabled_for_channel", lambda *args: True)
    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/messages/{pending.id}/approve",
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("saved=sent")
    assert len(sent) == 1
    assert sent[0][0].endswith("<multas@carfast.pt>")
    assert sent[0][1] == "multas@carfast.pt"


def test_new_message_is_blocked_for_original_alias_policy(
    authenticated_client, db_session, monkeypatch
):
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    channel = db_session.scalar(
        select(EmailChannel).where(EmailChannel.code == "multas")
    )
    channel.reply_policy = "original"
    db_session.commit()

    response = authenticated_client.post(
        "/v2-clean/email/new",
        data={
            "channel_id": channel.id,
            "recipients": "external@example.test",
            "subject": "Nova mensagem",
            "body": "Não deve criar conversa.",
            "submit": "draft",
        },
        follow_redirects=False,
    )
    assert response.headers["location"].endswith("error=sender_not_configured")


def _payload(delivery_id: str, mailbox_hash: str = "multas") -> dict:
    return {
        "MessageID": delivery_id,
        "MailboxHash": mailbox_hash,
        "From": "cliente@example.com",
        "FromName": "Cliente",
        "To": "multas@carfast.pt",
        "ToFull": [{"Email": "multas@carfast.pt", "Name": "", "MailboxHash": mailbox_hash}],
        "CcFull": [],
        "Subject": "Pedido lógico",
        "TextBody": "A mesma mensagem encaminhada mais do que uma vez.",
        "HtmlBody": "",
        "Headers": [{"Name": "Message-ID", "Value": "<logical@example.com>"}],
        "Attachments": [],
    }


def test_functional_mailbox_bootstrap_is_idempotent_and_preserves_admin_changes(db_session):
    seed_email_channels(db_session)
    channel = db_session.scalar(
        select(EmailChannel).where(EmailChannel.code == "seguradoras")
    )
    channel.name = "Seguradoras configurada"
    channel.default_reply_address = "insurance@example.test"
    channel.reply_policy = "original"
    db_session.commit()

    seed_email_channels(db_session)
    seed_email_channels(db_session)
    db_session.commit()
    channels = {
        item.code: item for item in db_session.scalars(select(EmailChannel)).all()
    }

    assert FUNCTIONAL_CODES.issubset(channels)
    assert channels["seguradoras"].name == "Seguradoras configurada"
    assert channels["seguradoras"].default_reply_address == "insurance@example.test"
    assert channels["seguradoras"].reply_policy == "original"
    assert db_session.scalar(
        select(func.count()).select_from(EmailChannel).where(
            EmailChannel.code == "seguradoras"
        )
    ) == 1


def test_admin_creates_edits_inactivates_and_adds_alias(
    authenticated_client, db_session
):
    response = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-channels",
        data={
            "code": "quality_ops",
            "name": "Qualidade",
            "from_address": "quality@example.test",
            "default_reply_address": "quality@example.test",
            "from_name": "CarFast — Qualidade",
            "reply_policy": "mailbox",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    channel = db_session.scalar(
        select(EmailChannel).where(EmailChannel.code == "quality_ops")
    )
    assert channel.address is None
    assert channel.inbound_hash is None

    response = authenticated_client.post(
        f"/v2-clean/admin/work-classification/email-channels/{channel.id}",
        data={
            "name": "Qualidade e Auditoria",
            "from_address": "quality-sender@example.test",
            "default_reply_address": "quality@example.test",
            "from_name": "CarFast — Qualidade e Auditoria",
            "reply_policy": "original",
            "requires_triage": "on",
            "administrative_review_on_unclassified": "on",
            "assignment_mode": "manual",
            "auto_task_mode": "none",
            "warning_minutes": "60",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(channel)
    assert channel.active is False
    assert channel.name == "Qualidade e Auditoria"
    assert channel.from_address == "quality-sender@example.test"
    assert channel.reply_policy == "original"

    response = authenticated_client.post(
        "/v2-clean/admin/work-classification/email-channel-aliases",
        data={
            "channel_id": channel.id,
            "address": "quality-intake@example.test",
            "inbound_hash": "quality-real-hash",
            "inbound_forward_address": "real-destination@inbound.example.test",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    alias = db_session.scalar(
        select(EmailChannelAlias).where(EmailChannelAlias.channel_id == channel.id)
    )
    assert alias.address == "quality-intake@example.test"
    assert alias.inbound_hash == "quality-real-hash"
    response = authenticated_client.post(
        f"/v2-clean/admin/work-classification/email-channel-aliases/{alias.id}",
        data={
            "address": "quality-intake-v2@example.test",
            "label": "Alias confirmado",
            "inbound_hash": "quality-real-hash-v2",
            "inbound_forward_address": "real-destination-v2@inbound.example.test",
            "active": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(alias)
    assert alias.address == "quality-intake-v2@example.test"
    assert alias.label == "Alias confirmado"


def test_channel_permission_isolation_and_sender_permissions(db_session):
    role = Role(code="functional_email_test", name="Functional email test", active=True)
    user = User(
        name="Scoped user",
        email="scoped@example.test",
        password_hash="not-used",
        active=True,
    )
    db_session.add_all([role, user])
    db_session.flush()
    db_session.add(UserRole(user_id=user.id, role_id=role.id))
    allowed = db_session.scalar(
        select(EmailChannel).where(EmailChannel.code == "seguradoras")
    )
    denied = db_session.scalar(select(EmailChannel).where(EmailChannel.code == "brokers"))
    db_session.add(
        EmailChannelRole(
            channel_id=allowed.id,
            role_id=role.id,
            can_read=True,
            can_reply=True,
            can_change_sender=True,
            can_edit_recipients=False,
            can_use_cc_bcc=False,
        )
    )
    db_session.commit()

    access = _channel_access(db_session, user.id, {"email.read"})
    assert allowed.id in access
    assert denied.id not in access
    assert access[allowed.id].can_change_sender is True
    assert access[allowed.id].can_edit_recipients is False


def test_rfc_message_id_deduplicates_delivery_and_preserves_origins(db_session):
    first, created = ingest_inbound(db_session, _payload("delivery-one"))
    second_payload = deepcopy(_payload("delivery-two"))
    second_payload["CcFull"] = [{"Email": "financeiro@example.org", "Name": "Financeiro"}]
    second, second_created = ingest_inbound(db_session, second_payload)

    assert created is True
    assert second_created is False
    assert second.id == first.id
    messages = list(
        db_session.scalars(select(EmailMessage).where(EmailMessage.thread_id == first.id))
    )
    assert len(messages) == 1
    assert {item["Email"] for item in messages[0].cc_json} == {
        "financeiro@example.org"
    }
    origins = list(
        db_session.scalars(
            select(EmailMessageDelivery).where(
                EmailMessageDelivery.message_id == messages[0].id
            )
        )
    )
    assert len({item.logical_key for item in origins}) == 1
    assert origins[0].logical_key.startswith("rfc:")
    assert {item.postmark_message_id for item in origins} == {
        "delivery-one",
        "delivery-two",
    }


def test_same_logical_message_is_not_merged_across_functional_boxes(db_session):
    first, _ = ingest_inbound(db_session, _payload("delivery-multas", "multas"))
    second_payload = deepcopy(_payload("delivery-oficina", "oficina"))
    second_payload["To"] = "oficina@carfast.pt"
    second_payload["ToFull"] = [
        {"Email": "oficina@carfast.pt", "Name": "", "MailboxHash": "oficina"}
    ]
    second, created = ingest_inbound(db_session, second_payload)

    assert created is True
    assert second.id != first.id
    assert second.channel_id != first.channel_id


def test_fallback_dedup_and_reply_all_remove_internal_aliases(db_session):
    first_payload = _payload("fallback-one")
    first_payload["Headers"] = []
    second_payload = deepcopy(first_payload)
    second_payload["MessageID"] = "fallback-two"
    thread, _ = ingest_inbound(db_session, first_payload)
    duplicate, created = ingest_inbound(db_session, second_payload)
    assert created is False
    assert duplicate.id == thread.id

    message = db_session.scalar(
        select(EmailMessage).where(EmailMessage.thread_id == thread.id)
    )
    message.recipients_json = [
        {"Email": "multas@carfast.pt"},
        {"Email": "external-one@example.org"},
    ]
    message.cc_json = [
        {"Email": "oficina@carfast.pt"},
        {"Email": "external-two@example.org"},
        {"Email": "cliente@example.com"},
    ]
    db_session.commit()
    defaults = _reply_defaults(db_session, thread)
    assert defaults["reply_all_to"] == ["cliente@example.com"]
    assert defaults["reply_all_cc"] == [
        "external-one@example.org",
        "external-two@example.org",
    ]


def test_reply_never_targets_the_functional_mailbox(db_session):
    thread, _ = ingest_inbound(db_session, _payload("internal-sender"))
    message = db_session.scalar(
        select(EmailMessage).where(EmailMessage.thread_id == thread.id)
    )
    message.sender = "multas@carfast.pt"
    message.recipients_json = [{"Email": "cliente@example.org"}]
    db_session.commit()

    defaults = _reply_defaults(db_session, thread)

    assert defaults["reply_to"] == "cliente@example.org"
    assert defaults["reply_all_to"] == ["cliente@example.org"]


def test_outbound_only_conversation_replies_to_external_recipient(db_session):
    channel = db_session.scalar(select(EmailChannel).where(EmailChannel.code == "multas"))
    thread = EmailThread(
        channel_id=channel.id,
        subject="Teste",
        sender_email="multas@carfast.pt",
        status="waiting_reply",
    )
    db_session.add(thread)
    db_session.flush()
    db_session.add(
        EmailMessage(
            thread_id=thread.id,
            direction="outbound",
            sender="multas@carfast.pt",
            recipients_json=[{"Email": "cliente@example.org"}],
            subject="Teste",
            state="sent",
        )
    )
    db_session.commit()

    defaults = _reply_defaults(db_session, thread)

    assert defaults["reply_to"] == "cliente@example.org"
    assert defaults["reply_all_to"] == ["cliente@example.org"]


def test_approval_is_invalidated_when_message_changes(
    authenticated_client, db_session, monkeypatch, tmp_path
):
    monkeypatch.setattr(email_web.settings, "email_storage_root", str(tmp_path))
    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    thread, _ = ingest_inbound(db_session, _payload("approval-delivery"))
    channel = db_session.get(EmailChannel, thread.channel_id)
    channel.from_address = "multas@carfast.pt"
    channel.reply_to_address = "multas@carfast.pt"
    db_session.commit()
    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/reply",
        data={
            "body": "Texto aprovado inicialmente.",
            "recipients": "cliente@example.com",
            "submit": "approval",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    draft = db_session.scalar(
        select(EmailMessage).where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == "outbound",
        )
    )
    assert draft.approval_fingerprint == _message_fingerprint(draft)
    draft.text_body = "Conteúdo alterado depois do pedido de aprovação."
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/email/{thread.id}/messages/{draft.id}/approve",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "approval_invalidated" in response.headers["location"]
    db_session.refresh(draft)
    assert draft.state == "draft"


def test_template_priority_version_context_and_missing_placeholders(db_session):
    channel = db_session.scalar(select(EmailChannel).where(EmailChannel.code == "multas"))
    queue = WorkQueue(code="template_queue", name="Template queue", active=True)
    db_session.add(queue)
    db_session.flush()
    department = WorkDepartment(
        queue_id=queue.id,
        code="template_department",
        name="Template department",
        active=True,
    )
    db_session.add(department)
    db_session.flush()
    category = WorkCategory(
        department_id=department.id,
        code="template_category",
        name="Template category",
        active=True,
    )
    db_session.add(category)
    db_session.flush()
    subcategory = WorkSubcategory(
        category_id=category.id,
        code="template_test",
        name="Template test",
        active=True,
    )
    db_session.add(subcategory)
    db_session.flush()
    templates = [
        EmailTemplate(code="global_test", name="Global", body_template="Global", version=1),
        EmailTemplate(
            code="channel_test",
            name="Channel",
            body_template="Channel",
            channel_id=channel.id,
            version=2,
        ),
        EmailTemplate(
            code="category_test",
            name="Category",
            body_template="Category",
            category_id=category.id,
            version=3,
        ),
        EmailTemplate(
            code="subcategory_test",
            name="Subcategory",
            body_template="Olá {{ recipient_name }}",
            subcategory_id=subcategory.id,
            version=4,
        ),
    ]
    db_session.add_all(templates)
    thread = EmailThread(
        channel_id=channel.id,
        subject="Template",
        status="triage",
        work_category_id=category.id,
        work_subcategory_id=subcategory.id,
    )
    db_session.add(thread)
    db_session.commit()

    ranked = _ranked_email_templates(db_session, thread)
    assert [item.code for item in ranked[:4]] == [
        "subcategory_test",
        "category_test",
        "channel_test",
        "global_test",
    ]
    assert _render_email_template(
        templates[-1].body_template, {"recipient_name": "Ana"}
    ) == "Olá Ana"
    try:
        _render_email_template("Olá {{ recipient_name }}", {"recipient_name": ""})
    except ValueError as exc:
        assert str(exc) == "template_variables_missing"
    else:
        raise AssertionError("Missing template variables must block the send path")
