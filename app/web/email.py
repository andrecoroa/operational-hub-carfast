from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from html import escape
from html.parser import HTMLParser
from mimetypes import guess_type
from pathlib import Path
from types import SimpleNamespace
from typing import Annotated
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, File, Form, Header, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.service_desk import EmailOriginCommand, ServiceDeskFacade
from app.models.admin import User, UserRole
from app.models.email import (
    EmailAttachment,
    EmailAuditEvent,
    EmailChannel,
    EmailChannelAlias,
    EmailChannelRole,
    EmailChannelUser,
    EmailMessage,
    EmailMessageDelivery,
    EmailTemplate,
    EmailThread,
    EmailThreadLink,
)
from app.models.organization import Team, TeamMember
from app.models.suppliers import SupplierTypeAssignment
from app.models.tasks import Task
from app.models.work_hierarchy import WorkCategory, WorkDepartment, WorkQueue, WorkSubcategory
from app.partners.compat import StockSupplier
from app.services.authorization import get_user_permission_codes
from app.services.classification_proposals import (
    attach_selection_to_entity,
    detach_entity_proposals,
    validate_proposal_selection,
)
from app.services.email_postmark import (
    ensure_email_channels,
    ingest_inbound,
    reply_all_recipients,
    send_message,
    webhook_authorized,
)
from app.services.service_desk import (
    assignment_label,
    assignment_target_user_allowed,
    claim_email_thread,
    email_eligible_teams,
    email_eligible_users,
    initialize_email_operations,
    local_datetime,
    mark_email_first_response,
    mark_email_resolved,
    sla_snapshot,
    transition_email_waiting,
)
from app.services.supplier_email_templates import (
    email_template_snapshot,
    ranked_supplier_email_templates,
)
from app.services.work_classification import (
    ATTACHMENT_STATUSES,
    CONTENT_TYPES,
    DOCUMENT_TYPES,
    WORK_NATURES,
    attachment_reference,
    message_reference,
    parse_classification_choice,
    task_classification,
    thread_reference,
    user_work_scope_allows,
    validate_work_hierarchy,
    work_hierarchy_context,
)

email_router = APIRouter()
from app.web.template_runtime import configure_visual_template_runtime

templates = configure_visual_template_runtime(Jinja2Templates(directory="app/templates"))
templates.env.filters["lisbon_datetime"] = local_datetime


def _nav_permissions(request: Request) -> set[str]:
    cached = getattr(request.state, "permission_codes", None)
    if cached is not None:
        return set(cached)
    raw_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not raw_id:
        return set()
    with SessionLocal() as db:
        user = db.get(User, int(raw_id))
        result = get_user_permission_codes(db, user) if user and user.active else set()
    request.state.permission_codes = result
    return result


templates.env.globals["nav_permissions"] = _nav_permissions
templates.env.globals["nav_has_permission"] = lambda request, *codes: bool(
    _nav_permissions(request).intersection(codes)
)

STATUS_LABELS = {
    "triage": "Por triar",
    "in_progress": "Em tratamento",
    "waiting_reply": "A aguardar resposta",
    "new_reply": "Nova resposta",
    "waiting_approval": "A aguardar aprovação",
    "returned": "Devolvido",
    "associated": "Associado",
    "task_created": "Convertido em tarefa",
    "resolved": "Resolvido",
    "archived": "Arquivado",
}

EMAIL_ADDRESS_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
EMAIL_LINK_KINDS = {
    "vehicle": "Matrícula",
    "supplier": "Fornecedor",
    "task": "Tarefa",
    "process": "Processo",
    "document": "Documento",
    "entity": "Entidade",
}


class _SafeEmailHTMLParser(HTMLParser):
    allowed_tags = {
        "a",
        "b",
        "blockquote",
        "br",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "tfoot",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
    void_tags = {"br", "hr", "img"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    @staticmethod
    def _safe_url(value: str) -> str | None:
        parsed = urlparse(value.strip())
        return value.strip() if parsed.scheme.lower() in {"http", "https", "mailto"} else None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag not in self.allowed_tags:
            return
        safe_attrs: list[str] = []
        for name, value in attrs:
            name, value = name.lower(), value or ""
            if tag == "a" and name == "href":
                safe = self._safe_url(value)
                if safe:
                    safe_attrs.extend(
                        [
                            f'href="{escape(safe, quote=True)}"',
                            'target="_blank"',
                            'rel="noopener noreferrer"',
                        ]
                    )
            elif tag == "img" and name == "src":
                safe = self._safe_url(value)
                if safe:
                    safe_attrs.append(f'data-email-src="{escape(safe, quote=True)}"')
            elif tag == "img" and name in {"alt", "title", "width", "height"}:
                safe_attrs.append(f'{name}="{escape(value, quote=True)}"')
            elif name in {"colspan", "rowspan"}:
                safe_attrs.append(f'{name}="{escape(value, quote=True)}"')
        suffix = f" {' '.join(safe_attrs)}" if safe_attrs else ""
        self.parts.append(f"<{tag}{suffix}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.allowed_tags and tag not in self.void_tags:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(escape(data))


def _safe_email_document(message: EmailMessage, *, plain_text: bool = False) -> str:
    if message.html_body and not plain_text:
        parser = _SafeEmailHTMLParser()
        parser.feed(message.html_body)
        body = "".join(parser.parts)
    else:
        body = f'<div class="plain">{escape(message.text_body or "Mensagem sem conteúdo.")}</div>'
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "body{margin:0;color:#13213a;font:14px/1.55 Arial,sans-serif;overflow-wrap:anywhere}"
        "img{display:none;max-width:100%;height:auto}table{max-width:100%;border-collapse:collapse}"
        "td,th{padding:4px 6px}"
        "blockquote{margin-left:0;padding-left:14px;border-left:3px solid #d8e0ea}"
        ".plain{white-space:pre-wrap}</style></head><body>"
        f"{body}</body></html>"
    )


def _attachment_media_type(attachment: EmailAttachment) -> str:
    guessed_type = guess_type(attachment.file_name or "")[0]
    stored_type = (attachment.content_type or "").split(";", 1)[0].strip().lower()
    if stored_type in {"", "application/octet-stream", "binary/octet-stream"}:
        return guessed_type or "application/octet-stream"
    return stored_type


def _attachment_can_preview(attachment: EmailAttachment) -> bool:
    media_type = _attachment_media_type(attachment)
    return (
        media_type == "application/pdf"
        or media_type.startswith("image/")
        or media_type.startswith("text/")
    )


def _store_outbound_attachments(
    db,
    *,
    thread: EmailThread,
    message: EmailMessage,
    uploads: list[UploadFile],
) -> list[EmailAttachment]:
    stored: list[EmailAttachment] = []
    prepared: list[tuple[str, str | None, bytes]] = []
    folder = Path(settings.email_storage_root or "var/email") / str(thread.id) / str(message.id)
    for upload in uploads:
        if not upload.filename:
            continue
        content = upload.file.read()
        if len(content) > settings.email_max_attachment_bytes:
            raise ValueError("attachment_too_large")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(upload.filename).name)
        prepared.append((safe_name, upload.content_type, content))
    for position, (safe_name, content_type, content) in enumerate(prepared, 1):
        path = folder / f"out-{position:02d}-{safe_name}"
        folder.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        attachment = EmailAttachment(
            message_id=message.id,
            file_name=safe_name,
            content_type=content_type,
            size=len(content),
            storage_path=str(path),
            sha256=hashlib.sha256(content).hexdigest(),
            status="associated",
        )
        db.add(attachment)
        stored.append(attachment)
    return stored


def _auth(request: Request, *required: str):
    raw_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not raw_id:
        return None
    with SessionLocal() as db:
        user = db.get(User, int(raw_id))
        permissions = get_user_permission_codes(db, user) if user and user.active else set()
    return (int(raw_id), permissions) if permissions.intersection(required) else None


def _channel_access(db, user_id: int, permissions: set[str]) -> dict[int, object | None]:
    channels = list(db.scalars(select(EmailChannel)))
    if "admin.manage" in permissions:
        return {channel.id: None for channel in channels}
    user_grants = list(
        db.scalars(select(EmailChannelUser).where(EmailChannelUser.user_id == user_id))
    )
    role_ids = list(
        db.scalars(select(UserRole.role_id).where(UserRole.user_id == user_id))
    )
    role_grants = list(
        db.scalars(
            select(EmailChannelRole).where(
                EmailChannelRole.role_id.in_(role_ids or [-1]),
                EmailChannelRole.can_read.is_(True),
            )
        )
    )
    merged: dict[int, object] = {}
    visibility_rank = {"consult": 0, "direct_only": 1, "scope_all": 2}

    def merge_visibility(current, incoming: str) -> None:
        if visibility_rank.get(incoming, 0) > visibility_rank.get(
            current.visibility_mode, 0
        ):
            current.visibility_mode = incoming

    for grant in role_grants:
        current = merged.setdefault(
            grant.channel_id,
            SimpleNamespace(
                can_reply=False,
                can_send_direct=False,
                can_approve=False,
                can_manage=False,
                can_assume=False,
                can_assign=False,
                can_manage_sla=False,
                can_change_sender=False,
                can_edit_recipients=False,
                can_use_cc_bcc=False,
                visibility_mode="consult",
            ),
        )
        current.can_reply = current.can_reply or grant.can_reply
        current.can_send_direct = current.can_send_direct or grant.can_send_direct
        current.can_approve = current.can_approve or grant.can_approve
        current.can_manage = current.can_manage or grant.can_manage
        current.can_assume = current.can_assume or grant.can_assume
        current.can_assign = current.can_assign or grant.can_assign
        current.can_manage_sla = current.can_manage_sla or grant.can_manage_sla
        current.can_change_sender = current.can_change_sender or grant.can_change_sender
        current.can_edit_recipients = (
            current.can_edit_recipients or grant.can_edit_recipients
        )
        current.can_use_cc_bcc = current.can_use_cc_bcc or grant.can_use_cc_bcc
        merge_visibility(current, grant.visibility_mode)
    for grant in user_grants:
        current = merged.setdefault(
            grant.channel_id,
            SimpleNamespace(
                can_reply=False,
                can_send_direct=False,
                can_approve=False,
                can_manage=False,
                can_assume=False,
                can_assign=False,
                can_manage_sla=False,
                can_change_sender=False,
                can_edit_recipients=False,
                can_use_cc_bcc=False,
                visibility_mode="consult",
            ),
        )
        current.can_reply = current.can_reply or grant.can_reply
        current.can_approve = current.can_approve or grant.can_approve
        current.can_assume = current.can_assume or grant.can_assume
        current.can_assign = current.can_assign or grant.can_assign
        current.can_manage_sla = current.can_manage_sla or grant.can_manage_sla
        current.can_change_sender = current.can_change_sender or grant.can_change_sender
        current.can_edit_recipients = (
            current.can_edit_recipients or grant.can_edit_recipients
        )
        current.can_use_cc_bcc = current.can_use_cc_bcc or grant.can_use_cc_bcc
        merge_visibility(current, grant.visibility_mode)
    return merged


def _can_use_channel(
    db,
    user_id: int,
    permissions: set[str],
    channel_id: int,
    action: str = "read",
    thread: EmailThread | None = None,
) -> bool:
    access = _channel_access(db, user_id, permissions)
    if channel_id not in access:
        return False
    grant = access[channel_id]
    if grant is None:
        return True
    if grant.visibility_mode == "consult" and action != "read":
        return False
    if thread is not None and grant.visibility_mode == "direct_only":
        team_relation = bool(
            thread.executor_team_id
            and db.scalar(
                select(TeamMember.id).where(
                    TeamMember.team_id == thread.executor_team_id,
                    TeamMember.user_id == user_id,
                )
            )
        )
        if not (
            thread.assigned_to_id == user_id
            or thread.created_by_id == user_id
            or team_relation
        ):
            return False
    if action == "read":
        return True
    if action == "alter":
        return True
    if action == "reply":
        return bool(grant.can_reply)
    if action == "approve":
        return bool(grant.can_approve)
    if action == "send_direct":
        return bool(grant.can_send_direct)
    if action == "manage":
        return bool(grant.can_manage)
    if action == "assume":
        return bool(grant.can_assume)
    if action == "assign":
        return bool(grant.can_assign)
    if action == "manage_sla":
        return bool(grant.can_manage_sla)
    if action == "change_sender":
        return bool(grant.can_change_sender)
    if action == "edit_recipients":
        return bool(grant.can_edit_recipients)
    if action == "use_cc_bcc":
        return bool(grant.can_use_cc_bcc)
    return False


def _email_visibility_filter(db, user_id: int, access: dict[int, object | None]):
    member_team_ids = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    conditions = []
    for channel_id, grant in access.items():
        base = EmailThread.channel_id == channel_id
        if grant is None or grant.visibility_mode in {"scope_all", "consult"}:
            conditions.append(base)
        else:
            conditions.append(
                base
                & or_(
                    EmailThread.assigned_to_id == user_id,
                    EmailThread.created_by_id == user_id,
                    EmailThread.executor_team_id.in_(member_team_ids),
                )
            )
    return or_(*conditions) if conditions else EmailThread.id == -1


def _reply_channel_context(
    db, user_id: int, permissions: set[str]
) -> tuple[list[EmailChannel], dict[int, bool]]:
    access = _channel_access(db, user_id, permissions)
    channels = list(
        db.scalars(
            select(EmailChannel)
            .where(
                EmailChannel.active.is_(True),
                EmailChannel.id.in_(list(access) or [-1]),
                or_(
                    EmailChannel.default_reply_address.is_not(None),
                    EmailChannel.address.is_not(None),
                ),
            )
            .order_by(EmailChannel.name)
        )
    )
    reply_channels = [
        channel
        for channel in channels
        if _can_use_channel(db, user_id, permissions, channel.id, "reply")
    ]
    return reply_channels, {
        channel.id: _can_use_channel(
            db, user_id, permissions, channel.id, "send_direct"
        )
        for channel in reply_channels
    }


def _sender_channel(db, message: EmailMessage) -> EmailChannel | None:
    sender = (message.sender or "").strip().lower()
    if not sender:
        return None
    channel = db.scalar(
        select(EmailChannel).where(
            EmailChannel.active.is_(True),
            or_(
                func.lower(EmailChannel.address) == sender,
                func.lower(EmailChannel.default_reply_address) == sender,
            ),
        )
    )
    if channel:
        return channel
    alias = db.scalar(
        select(EmailChannelAlias).where(
            EmailChannelAlias.active.is_(True),
            func.lower(EmailChannelAlias.address) == sender,
        )
    )
    return db.get(EmailChannel, alias.channel_id) if alias else None


def _channel_sender_address(
    db, thread: EmailThread, channel: EmailChannel
) -> str | None:
    original = (thread.original_recipient_address or "").strip().lower()
    if channel.reply_policy == "original" and original:
        configured_original = db.scalar(
            select(EmailChannelAlias.id).where(
                EmailChannelAlias.channel_id == channel.id,
                EmailChannelAlias.active.is_(True),
                func.lower(EmailChannelAlias.address) == original,
            )
        ) or (
            channel.address
            and channel.address.casefold() == original.casefold()
        )
        if configured_original:
            return original
    return (channel.default_reply_address or channel.address or "").strip().lower() or None


def _channel_sender_options(db, channel: EmailChannel) -> list[str]:
    values = [channel.default_reply_address, channel.address]
    values.extend(
        db.scalars(
            select(EmailChannelAlias.address).where(
                EmailChannelAlias.channel_id == channel.id,
                EmailChannelAlias.active.is_(True),
            )
        )
    )
    return list(dict.fromkeys(item.casefold() for item in values if item))


def _address_values(raw: str) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in re.split(r"[,;]", raw or ""):
        address = value.strip().lower()
        if not address or address in seen:
            continue
        if not EMAIL_ADDRESS_PATTERN.fullmatch(address):
            raise ValueError("invalid_recipient")
        seen.add(address)
        result.append(address)
    return result


def _recipient_json(addresses: list[str]) -> list[dict[str, str]]:
    return [{"Email": item} for item in addresses]


def _internal_email_addresses(db) -> set[str]:
    result = {
        value.casefold()
        for row in db.scalars(select(EmailChannel)).all()
        for value in (
            row.address,
            row.default_reply_address,
            row.inbound_forward_address,
        )
        if value
    }
    for alias in db.scalars(
        select(EmailChannelAlias).where(EmailChannelAlias.active.is_(True))
    ):
        for value in (alias.address, alias.inbound_forward_address):
            if value:
                result.add(value.casefold())
    internal_domains = {item.rsplit("@", 1)[-1] for item in result if "@" in item}
    for domain in internal_domains:
        result.add(f"*@{domain}")
    return result


def _is_internal_address(address: str, internal: set[str]) -> bool:
    address = address.casefold()
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    return address in internal or f"*@{domain}" in internal


def _reply_defaults(db, thread: EmailThread) -> dict[str, object]:
    latest = db.scalar(
        select(EmailMessage)
        .where(
            EmailMessage.thread_id == thread.id,
            EmailMessage.direction == "inbound",
        )
        .order_by(EmailMessage.id.desc())
    )
    sender = (latest.sender if latest else thread.sender_email or "").strip().lower()
    internal = _internal_email_addresses(db)
    all_candidates = [sender]
    if latest:
        all_candidates.extend(
            str(item.get("Email") or "").strip().lower()
            for item in [*(latest.recipients_json or []), *(latest.cc_json or [])]
            if isinstance(item, dict)
        )
    reply_all: list[str] = []
    seen: set[str] = set()
    for address in all_candidates:
        if (
            not address
            or address in seen
            or not EMAIL_ADDRESS_PATTERN.fullmatch(address)
            or _is_internal_address(address, internal)
        ):
            continue
        seen.add(address)
        reply_all.append(address)
    return {
        "reply_to": sender,
        "reply_all_to": reply_all[:1],
        "reply_all_cc": reply_all[1:],
        "latest_message": latest,
    }


def _message_fingerprint(message: EmailMessage) -> str:
    canonical = {
        "sender": message.sender,
        "to": message.recipients_json or [],
        "cc": message.cc_json or [],
        "bcc": message.bcc_json or [],
        "subject": message.subject,
        "text": message.text_body or "",
        "html": message.html_body or "",
        "template_id": message.template_id,
        "template_version": message.template_version,
    }
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


TEMPLATE_VARIABLE_PATTERN = re.compile(r"{{\s*([a-zA-Z][a-zA-Z0-9_]*)\s*}}")
SAFE_TEMPLATE_VARIABLES = {
    "recipient_name",
    "sender_email",
    "subject",
    "thread_reference",
}


def _render_email_template(value: str | None, context: dict[str, str]) -> str:
    raw = value or ""
    variables = set(TEMPLATE_VARIABLE_PATTERN.findall(raw))
    unsupported = variables - SAFE_TEMPLATE_VARIABLES
    missing = {item for item in variables if not context.get(item)}
    if unsupported or missing:
        raise ValueError("template_variables_missing")
    return TEMPLATE_VARIABLE_PATTERN.sub(lambda match: context[match.group(1)], raw)


def _ranked_email_templates(db, thread: EmailThread) -> list[EmailTemplate]:
    candidates = list(
        db.scalars(
            select(EmailTemplate).where(
                EmailTemplate.active.is_(True),
                or_(
                    EmailTemplate.channel_id.is_(None),
                    EmailTemplate.channel_id == thread.channel_id,
                ),
            )
        )
    )
    templates_list = [
        item
        for item in candidates
        if item.supplier_id is None
        and item.supplier_type_id is None
        and (not item.category_id or item.category_id == thread.work_category_id)
        and (
            not item.subcategory_id
            or item.subcategory_id == thread.work_subcategory_id
        )
    ]

    def rank(item: EmailTemplate) -> tuple[int, str]:
        if thread.work_subcategory_id and item.subcategory_id == thread.work_subcategory_id:
            return (0, item.name.casefold())
        if thread.work_category_id and item.category_id == thread.work_category_id:
            return (1, item.name.casefold())
        if (
            item.channel_id == thread.channel_id
            and not item.category_id
            and not item.subcategory_id
        ):
            return (2, item.name.casefold())
        if item.channel_id is None and not item.category_id and not item.subcategory_id:
            return (3, item.name.casefold())
        return (4, item.name.casefold())

    return sorted(templates_list, key=rank)


def _thread_view_data(db, thread: EmailThread) -> dict:
    messages = list(
        db.scalars(
            select(EmailMessage)
            .where(EmailMessage.thread_id == thread.id)
            .order_by(EmailMessage.created_at, EmailMessage.id)
        )
    )
    message_ids = [message.id for message in messages]
    attachments = list(
        db.scalars(
            select(EmailAttachment)
            .where(EmailAttachment.message_id.in_(message_ids or [-1]))
            .order_by(EmailAttachment.message_id, EmailAttachment.id)
        )
    )
    message_positions = {message.id: pos for pos, message in enumerate(messages, 1)}
    grouped: dict[int, list[dict]] = {message.id: [] for message in messages}
    for attachment in attachments:
        position = len(grouped[attachment.message_id]) + 1
        grouped[attachment.message_id].append(
            {
                "item": attachment,
                "reference": attachment_reference(
                    thread, message_positions[attachment.message_id], position
                ),
            }
        )
    deliveries = list(
        db.scalars(
            select(EmailMessageDelivery)
            .where(EmailMessageDelivery.message_id.in_(message_ids or [-1]))
            .order_by(EmailMessageDelivery.message_id, EmailMessageDelivery.id)
        )
    )
    deliveries_by_message: dict[int, list[EmailMessageDelivery]] = {
        message.id: [] for message in messages
    }
    received_originally_by_message: dict[int, list[str]] = {
        message.id: [] for message in messages
    }
    for delivery in deliveries:
        deliveries_by_message[delivery.message_id].append(delivery)
        label = delivery.original_recipient or delivery.inbound_address
        if label and label.casefold() not in {
            item.casefold() for item in received_originally_by_message[delivery.message_id]
        }:
            received_originally_by_message[delivery.message_id].append(label)
    latest_inbound = next(
        (message for message in reversed(messages) if message.direction == "inbound"),
        None,
    )
    return {
        "messages": messages,
        "message_refs": {
            message.id: message_reference(thread, position)
            for position, message in enumerate(messages, 1)
        },
        "attachments_by_message": grouped,
        "deliveries_by_message": deliveries_by_message,
        "origins_by_message": deliveries_by_message,
        "received_originally_by_message": received_originally_by_message,
        "latest_inbound_message": latest_inbound,
        "has_unread": any(
            message.direction == "inbound" and message.state == "received"
            for message in messages
        ),
        "thread_links": list(
            db.scalars(
                select(EmailThreadLink)
                .where(EmailThreadLink.thread_id == thread.id)
                .order_by(EmailThreadLink.created_at, EmailThreadLink.id)
            )
        ),
        "thread_reference": thread_reference(thread),
    }


def _reply_all_context(db, view_data: dict, channel: EmailChannel) -> dict:
    source = view_data["latest_inbound_message"]
    if not source:
        return {
            "reply_source_message_id": None,
            "reply_all_to": [],
            "reply_all_cc": [],
        }
    reply_to, reply_cc = reply_all_recipients(db, source, channel.address)
    return {
        "reply_source_message_id": source.id,
        "reply_all_to": reply_to,
        "reply_all_cc": reply_cc,
    }


def _classification_context() -> dict:
    return {
        "content_types": CONTENT_TYPES,
        "work_natures": WORK_NATURES,
        "document_types": DOCUMENT_TYPES,
        "attachment_statuses": ATTACHMENT_STATUSES,
    }


def _optional_datetime(value: str) -> datetime | None:
    if not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Lisbon"))
    return parsed.astimezone(UTC)


@email_router.post("/api/webhooks/postmark/inbound")
async def postmark_inbound(request: Request, authorization: str | None = Header(default=None)):
    if not settings.email_inbound_enabled:
        return JSONResponse({"detail": "Email inbound disabled"}, status_code=503)
    if not webhook_authorized(authorization):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    payload = await request.json()
    with SessionLocal() as db:
        try:
            thread, created = ingest_inbound(db, payload)
        except ValueError as exc:
            return JSONResponse({"detail": str(exc)}, status_code=422)
        return {"ok": True, "created": created, "thread_id": thread.id}


@email_router.post("/api/webhooks/postmark/events")
async def postmark_events(request: Request, authorization: str | None = Header(default=None)):
    if not settings.email_inbound_enabled:
        return JSONResponse({"detail": "Email events disabled"}, status_code=503)
    if not webhook_authorized(authorization):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return {"ok": True}


@email_router.get("/v2-clean/email", response_class=HTMLResponse)
def email_inbox(
    request: Request,
    status: str = "triage",
    channel: str = "",
    q: str = "",
    responsible: str = "",
    due: str = "",
    supplier_id: int | None = None,
    module_code: str = "",
    compose: str = "",
    context_code: str = "",
):
    auth = _auth(request, "email.read", "email.triage", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse("/login?next=/v2-clean/email", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        ensure_email_channels(db)
        db.commit()
        channel_access = _channel_access(db, user_id, permissions)
        selected_status = status if status in STATUS_LABELS or status == "all" else "triage"
        query = (
            select(EmailThread, EmailChannel)
            .join(EmailChannel, EmailChannel.id == EmailThread.channel_id)
            .where(_email_visibility_filter(db, user_id, channel_access))
        )
        if selected_status != "all":
            query = query.where(EmailThread.status == selected_status)
        if channel:
            query = query.where(EmailChannel.code == channel)
        if responsible == "mine":
            query = query.where(EmailThread.assigned_to_id == user_id)
        elif responsible == "unassigned":
            query = query.where(
                EmailThread.assigned_to_id.is_(None),
                EmailThread.executor_team_id.is_(None),
            )
        elif responsible.startswith("team:") and responsible[5:].isdigit():
            query = query.where(EmailThread.executor_team_id == int(responsible[5:]))
        elif responsible.isdigit():
            query = query.where(EmailThread.assigned_to_id == int(responsible))
        now = datetime.now(UTC)
        if due == "overdue":
            query = query.where(
                EmailThread.resolution_due_at < now,
                EmailThread.status.not_in({"resolved", "archived"}),
            )
        elif due == "today":
            tomorrow = now + timedelta(days=1)
            query = query.where(
                EmailThread.resolution_due_at >= now.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
                EmailThread.resolution_due_at < tomorrow.replace(
                    hour=0, minute=0, second=0, microsecond=0
                ),
            )
        elif due == "no_sla":
            query = query.where(EmailThread.resolution_due_at.is_(None))
        clean_query = q.strip()
        if clean_query:
            pattern = f"%{clean_query}%"
            message_match = select(EmailMessage.thread_id).where(
                EmailMessage.thread_id == EmailThread.id,
                or_(
                    EmailMessage.subject.ilike(pattern),
                    EmailMessage.sender.ilike(pattern),
                    EmailMessage.text_body.ilike(pattern),
                    EmailMessage.html_body.ilike(pattern),
                    EmailMessage.external_message_id.ilike(pattern),
                ),
            )
            search_terms = [
                EmailThread.subject.ilike(pattern),
                EmailThread.sender_name.ilike(pattern),
                EmailThread.sender_email.ilike(pattern),
                EmailThread.external_conversation_id.ilike(pattern),
                EmailThread.id.in_(message_match),
            ]
            reference_tail = clean_query.upper().split(".", 1)[0].rsplit("-", 1)[-1]
            if reference_tail.isdigit():
                search_terms.append(EmailThread.id == int(reference_tail))
            query = query.where(or_(*search_terms))
        rows = db.execute(query.order_by(EmailThread.last_message_at.desc()).limit(100)).all()

        def facet_count(*, facet_status: str | None = None, facet_responsible: str | None = None, facet_due: str | None = None) -> int:
            statement = select(func.count()).select_from(EmailThread).join(EmailChannel, EmailChannel.id == EmailThread.channel_id).where(_email_visibility_filter(db, user_id, channel_access))
            effective_status = selected_status if facet_status is None else facet_status
            effective_responsible = responsible if facet_responsible is None else facet_responsible
            effective_due = due if facet_due is None else facet_due
            if effective_status != "all": statement = statement.where(EmailThread.status == effective_status)
            if channel: statement = statement.where(EmailChannel.code == channel)
            if effective_responsible == "mine": statement = statement.where(EmailThread.assigned_to_id == user_id)
            elif effective_responsible == "unassigned": statement = statement.where(EmailThread.assigned_to_id.is_(None), EmailThread.executor_team_id.is_(None))
            elif effective_responsible.startswith("team:") and effective_responsible[5:].isdigit(): statement = statement.where(EmailThread.executor_team_id == int(effective_responsible[5:]))
            elif effective_responsible.isdigit(): statement = statement.where(EmailThread.assigned_to_id == int(effective_responsible))
            if effective_due == "overdue": statement = statement.where(EmailThread.resolution_due_at < now, EmailThread.status.not_in({"resolved", "archived"}))
            elif effective_due == "today":
                tomorrow = now + timedelta(days=1)
                statement = statement.where(EmailThread.resolution_due_at >= now.replace(hour=0, minute=0, second=0, microsecond=0), EmailThread.resolution_due_at < tomorrow.replace(hour=0, minute=0, second=0, microsecond=0))
            elif effective_due == "no_sla": statement = statement.where(EmailThread.resolution_due_at.is_(None))
            if clean_query:
                pattern = f"%{clean_query}%"
                message_match = select(EmailMessage.thread_id).where(EmailMessage.thread_id == EmailThread.id, or_(EmailMessage.subject.ilike(pattern), EmailMessage.sender.ilike(pattern), EmailMessage.text_body.ilike(pattern), EmailMessage.html_body.ilike(pattern), EmailMessage.external_message_id.ilike(pattern)))
                terms = [EmailThread.subject.ilike(pattern), EmailThread.sender_name.ilike(pattern), EmailThread.sender_email.ilike(pattern), EmailThread.external_conversation_id.ilike(pattern), EmailThread.id.in_(message_match)]
                reference_tail = clean_query.upper().split(".", 1)[0].rsplit("-", 1)[-1]
                if reference_tail.isdigit(): terms.append(EmailThread.id == int(reference_tail))
                statement = statement.where(or_(*terms))
            return db.scalar(statement) or 0

        counts = {code: facet_count(facet_status=code) for code in STATUS_LABELS}
        all_status_count = facet_count(facet_status="all")
        filtered_total_count = facet_count()
        operational_counters = {"triage": facet_count(facet_status="triage"), "mine": facet_count(facet_responsible="mine"), "unassigned": facet_count(facet_responsible="unassigned"), "overdue": facet_count(facet_due="overdue"), "waiting": facet_count(facet_status="waiting_reply")}
        channels = list(
            db.scalars(
                select(EmailChannel)
                .where(EmailChannel.id.in_(list(channel_access) or [-1]))
                .order_by(EmailChannel.name)
            )
        )
        users = list(db.scalars(select(User).order_by(User.name)))
        users_by_id = {item.id: item for item in users}
        teams_by_id = {
            item.id: item for item in db.scalars(select(Team).order_by(Team.name))
        }
        inbox_rows = []
        for thread, thread_channel in rows:
            due_at = thread.due_at
            comparable_due_at = due_at
            if comparable_due_at and comparable_due_at.tzinfo is None:
                comparable_due_at = comparable_due_at.replace(tzinfo=UTC)
            due_state = ""
            if comparable_due_at:
                if comparable_due_at < now:
                    due_state = "overdue"
                elif comparable_due_at.date() == now.date():
                    due_state = "today"
                else:
                    due_state = "planned"
            inbox_rows.append(
                SimpleNamespace(
                    thread=thread,
                    channel=thread_channel,
                    reference=thread_reference(thread),
                    assignee=users_by_id.get(thread.assigned_to_id),
                    functional_owner=users_by_id.get(thread.functional_owner_user_id),
                    assignment_label=assignment_label(
                        state=thread.assignment_state,
                        user_name=(
                            users_by_id[thread.assigned_to_id].name
                            if thread.assigned_to_id in users_by_id
                            else None
                        ),
                        team_name=(
                            teams_by_id[thread.executor_team_id].name
                            if thread.executor_team_id in teams_by_id
                            else None
                        ),
                    ),
                    sla=sla_snapshot(thread),
                    due_state=due_state,
                )
            )
        compose_channels = [
            item
            for item in channels
            if _can_use_channel(db, user_id, permissions, item.id, "reply")
        ]
        compose_supplier = db.get(StockSupplier, supplier_id) if supplier_id else None
        if compose_supplier and not compose_supplier.active:
            compose_supplier = None
        supplier_type_ids = (
            set(
                db.scalars(
                    select(SupplierTypeAssignment.supplier_type_id).where(
                        SupplierTypeAssignment.supplier_id == compose_supplier.id
                    )
                )
            )
            if compose_supplier
            else set()
        )
        email_templates = [
            item
            for item in ranked_supplier_email_templates(
                db,
                supplier_id=compose_supplier.id if compose_supplier else None,
                supplier_type_ids=supplier_type_ids,
                module_code=module_code.strip().lower() or None,
                context_code=context_code.strip().lower() or None,
            )
            if item.channel_id is None or item.channel_id in channel_access
        ]
        return templates.TemplateResponse(
            request,
            "clean_email_inbox.html",
            {
                "active_menu": "email",
                "current_user": db.get(User, user_id),
                "permission_codes": permissions,
                "rows": inbox_rows,
                "channels": channels,
                "counts": counts,
                "operational_counters": operational_counters,
                "total_count": all_status_count,
                "filtered_total_count": filtered_total_count,
                "status_labels": STATUS_LABELS,
                "filters": {
                    "status": selected_status,
                    "channel": channel,
                    "q": clean_query,
                    "responsible": responsible,
                    "due": due,
                },
                "filter_users": [item for item in users if item.active],
                "filter_teams": list(teams_by_id.values()),
                "compose_channels": compose_channels,
                "email_templates": email_templates,
                "channel_send_direct": {
                    item.id: _can_use_channel(
                        db, user_id, permissions, item.id, "send_direct"
                    )
                    for item in compose_channels
                },
                "compose_supplier": compose_supplier,
                "compose_module_code": module_code.strip().lower(),
                "compose_context_code": context_code.strip().lower(),
                "compose_open": compose == "1" and compose_supplier is not None,
                "foundation_ui_enabled": settings.visual_foundation_enabled,
            },
        )


@email_router.post("/v2-clean/email/new")
def email_new_message(
    request: Request,
    channel_id: int = Form(...),
    recipients: str = Form(""),
    cc: str = Form(""),
    bcc: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    template_id: str = Form(""),
    submit: str = Form("draft"),
    supplier_id: int | None = Form(None),
    supplier_type_id: int | None = Form(None),
    module_code: str = Form(""),
    context_code: str = Form(""),
):
    auth = _auth(request, "email.reply", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)
    if submit not in {"draft", "approval", "send"}:
        return RedirectResponse("/v2-clean/email?error=invalid_action", status_code=303)
    user_id, permissions = auth
    recipient_list = [
        item.strip()
        for item in recipients.replace(";", ",").split(",")
        if item.strip()
    ]
    if not recipient_list or any(
        "@" not in item or item.startswith("@") or item.endswith("@")
        for item in recipient_list
    ):
        return RedirectResponse("/v2-clean/email?error=invalid_recipient", status_code=303)
    try:
        cc_list = _address_values(cc)
        bcc_list = _address_values(bcc)
    except ValueError:
        return RedirectResponse("/v2-clean/email?error=invalid_recipient", status_code=303)
    with SessionLocal() as db:
        channel = db.get(EmailChannel, channel_id)
        if (
            not channel
            or not channel.active
            or not _can_use_channel(db, user_id, permissions, channel.id, "reply")
        ):
            return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)
        supplier = db.get(StockSupplier, supplier_id) if supplier_id else None
        if supplier and not supplier.active:
            return RedirectResponse("/v2-clean/email?error=inactive_supplier", status_code=303)
        supplier_type_ids = (
            set(db.scalars(select(SupplierTypeAssignment.supplier_type_id).where(SupplierTypeAssignment.supplier_id == supplier.id)))
            if supplier else set()
        )
        if supplier_type_id not in supplier_type_ids:
            supplier_type_id = next(iter(sorted(supplier_type_ids)), None)
        applicable_templates = ranked_supplier_email_templates(
            db,
            supplier_id=supplier.id if supplier else None,
            supplier_type_ids=supplier_type_ids,
            module_code=module_code.strip().lower() or None,
            context_code=context_code.strip().lower() or None,
            channel_id=channel.id,
        )
        applicable_ids = {item.id for item in applicable_templates}
        template = db.get(EmailTemplate, int(template_id)) if template_id.isdigit() else None
        if template and template.id not in applicable_ids:
            template = None
        if (cc_list or bcc_list) and not _can_use_channel(
            db, user_id, permissions, channel.id, "use_cc_bcc"
        ):
            return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)
        sender_address = channel.default_reply_address or channel.address
        if not sender_address:
            return RedirectResponse(
                "/v2-clean/email?error=sender_not_configured", status_code=303
            )
        template_context = {
            "recipient_name": recipient_list[0].split("@", 1)[0],
            "sender_email": recipient_list[0],
            "subject": subject.strip(),
            "thread_reference": "",
        }
        try:
            clean_subject = _render_email_template(
                subject.strip() or (template.subject_template if template else ""),
                template_context,
            )
            clean_body = _render_email_template(
                body.strip() or (template.body_template if template else ""),
                template_context,
            )
        except ValueError:
            return RedirectResponse(
                "/v2-clean/email?error=template_variables_missing", status_code=303
            )
        if not clean_subject or not clean_body:
            return RedirectResponse("/v2-clean/email?error=missing_message", status_code=303)
        if submit == "send" and not _can_use_channel(
            db, user_id, permissions, channel.id, "send_direct"
        ):
            return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)

        queue_id = channel.default_queue_id
        department_id = channel.default_department_id
        category_id = channel.default_category_id
        subcategory_id = channel.default_subcategory_id
        if template and template.category_id:
            category_item = db.get(WorkCategory, template.category_id)
            department_item = (
                db.get(WorkDepartment, category_item.department_id) if category_item else None
            )
            queue_item = db.get(WorkQueue, department_item.queue_id) if department_item else None
            if category_item and department_item and queue_item:
                queue_id = queue_item.id
                department_id = department_item.id
                category_id = category_item.id
                subcategory_item = (
                    db.get(WorkSubcategory, template.subcategory_id)
                    if template.subcategory_id
                    else None
                )
                subcategory_id = (
                    subcategory_item.id
                    if subcategory_item
                    and subcategory_item.category_id == category_item.id
                    else None
                )

        now = datetime.now(UTC)
        state = {
            "approval": "pending_approval",
            "send": "approved",
        }.get(submit, "draft")
        thread = EmailThread(
            channel_id=channel.id,
            subject=clean_subject[:500],
            status="waiting_approval" if state == "pending_approval" else "in_progress",
            sender_email=recipient_list[0][:255],
            sender_name=recipient_list[0][:255],
            work_queue_id=queue_id,
            work_department_id=department_id,
            work_category_id=category_id,
            work_subcategory_id=subcategory_id,
            classification_status=(
                "classified" if queue_id and department_id else "unclassified"
            ),
            document_type=channel.default_document_type,
            functional_owner_user_id=channel.functional_owner_user_id,
            administrative_review_required=(
                channel.administrative_review_on_unclassified
            ),
            created_by_id=user_id,
            waiting_until=(
                now + timedelta(days=channel.default_wait_days)
                if channel.default_wait_days is not None
                else None
            ),
            last_message_at=now,
        )
        db.add(thread)
        db.flush()
        initialize_email_operations(db, thread, channel=channel, now=now)
        message = EmailMessage(
            thread_id=thread.id,
            direction="outbound",
            state=state,
            sender=sender_address,
            recipients_json=[{"Email": item} for item in recipient_list],
            cc_json=_recipient_json(cc_list),
            bcc_json=_recipient_json(bcc_list),
            subject=clean_subject[:500],
            text_body=clean_body,
            compose_mode="new",
            template_id=template.id if template else None,
            template_version=template.version if template else None,
            template_snapshot_json=email_template_snapshot(
                template, rendered_subject=clean_subject, rendered_body=clean_body
            ),
            supplier_id=supplier.id if supplier else None,
            supplier_type_id=supplier_type_id,
            context_module=module_code.strip().lower() or None,
            context_code=context_code.strip().lower() or None,
            created_by_id=user_id,
        )
        message.approval_fingerprint = _message_fingerprint(message)
        db.add(message)
        db.flush()
        audit_action = state
        if submit == "send":
            try:
                result = send_message(message, sender_address, reply_to=sender_address)
            except RuntimeError as exc:
                message.postmark_error = str(exc)
                db.commit()
                return RedirectResponse(
                    f"/v2-clean/email/{thread.id}?error=send_disabled", status_code=303
                )
            message.state = "sent"
            message.sent_at = now
            message.approved_by_id = user_id
            message.approved_at = now
            message.external_message_id = result.get("MessageID") or None
            thread.status = "waiting_reply"
            mark_email_first_response(db, thread, user_id=user_id, now=now)
            transition_email_waiting(
                db,
                thread,
                waiting=True,
                user_id=user_id,
                reason="A aguardar resposta externa",
                now=now,
            )
            audit_action = "sent"
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                user_id=user_id,
                action=f"new_message_{audit_action}",
                details_json={
                    "template_id": template.id if template else None,
                    "template_version": template.version if template else None,
                    "sender": sender_address,
                    "to": recipient_list,
                    "cc": cc_list,
                    "bcc": bcc_list,
                },
            )
        )
        db.commit()
        thread_id = thread.id
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved={audit_action}", status_code=303)


@email_router.get("/v2-clean/email/{thread_id}", response_class=HTMLResponse)
def email_thread(request: Request, thread_id: int):
    auth = _auth(
        request,
        "email.read",
        "email.triage",
        "email.reply",
        "email.approve",
        "email.manage",
        "admin.manage",
    )
    if not auth:
        return RedirectResponse("/login?next=/v2-clean/email", status_code=303)
    user_id, permissions = auth
    return_context = request.query_params.get("return_context", "")
    if not return_context.startswith("/v2-clean/email") or return_context.startswith("//"):
        return_context = "/v2-clean/email"
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, thread=thread
        ):
            return RedirectResponse("/v2-clean/email?error=not_found", status_code=303)
        channel = db.get(EmailChannel, thread.channel_id)
        view_data = _thread_view_data(db, thread)
        reply_channels, reply_channel_send_direct = _reply_channel_context(
            db, user_id, permissions
        )
        eligible_users = [
            item
            for item in email_eligible_users(
                db, thread.channel_id, thread.work_category_id
            )
            if assignment_target_user_allowed(
                db, actor_user_id=user_id, target_user_id=item.id
            )
        ]
        eligible_teams = email_eligible_teams(db, thread.channel_id, thread.work_category_id)
        thread_assignee = db.get(User, thread.assigned_to_id) if thread.assigned_to_id else None
        thread_team = db.get(Team, thread.executor_team_id) if thread.executor_team_id else None
        if thread_assignee and all(item.id != thread_assignee.id for item in eligible_users):
            eligible_users.append(thread_assignee)
        if thread_team and all(item.id != thread_team.id for item in eligible_teams):
            eligible_teams.append(thread_team)
        can_alter = bool(
            permissions.intersection({"email.triage", "email.manage", "admin.manage"})
        ) and _can_use_channel(
            db, user_id, permissions, thread.channel_id, "alter", thread=thread
        )
        workflow_context = {
            **work_hierarchy_context(db),
            **_reply_all_context(db, view_data, channel),
            "can_propose_classification": "classification.propose" in permissions,
            "can_use_provisional_classification": "classification.provisional.use"
            in permissions,
            "email_users": eligible_users,
            "email_teams": eligible_teams,
            "email_assignment_label": assignment_label(
                state=thread.assignment_state,
                user_name=thread_assignee.name if thread_assignee else None,
                team_name=thread_team.name if thread_team else None,
            ),
            "email_sla": sla_snapshot(thread),
            "functional_owner": (
                db.get(User, thread.functional_owner_user_id)
                if thread.functional_owner_user_id
                else None
            ),
            "can_claim": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "assume", thread=thread
            ),
            "can_assign": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "assign", thread=thread
            ),
            "can_manage_sla": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "manage_sla", thread=thread
            ),
            "can_alter": can_alter,
            "can_create_task": can_alter
            and bool(
                permissions.intersection(
                    {
                        "tasks.write",
                        "tasks.operational.write",
                        "tasks.administration.write",
                        "admin.manage",
                    }
                )
            ),
            "email_templates": _ranked_email_templates(db, thread),
            "reply_defaults": _reply_defaults(db, thread),
            "reply_sender_address": _channel_sender_address(db, thread, channel),
            "reply_sender_options": _channel_sender_options(db, channel),
            "can_change_sender": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "change_sender", thread=thread
            ),
            "can_edit_recipients": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "edit_recipients", thread=thread
            ),
            "can_use_cc_bcc": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "use_cc_bcc", thread=thread
            ),
            "reply_channels": reply_channels,
            "reply_channel_send_direct": reply_channel_send_direct,
            "approvable_message_ids": {
                message.id
                for message in view_data["messages"]
                if permissions.intersection(
                    {"email.approve", "email.manage", "admin.manage"}
                )
                and message.state == "pending_approval"
                and message.approval_fingerprint == _message_fingerprint(message)
                and (sender_channel := _sender_channel(db, message)) is not None
                and _can_use_channel(
                    db, user_id, permissions, sender_channel.id, "approve"
                )
            },
        }
        return templates.TemplateResponse(
            request,
            "clean_email_thread.html",
            {
                "active_menu": "email",
                "current_user": db.get(User, user_id),
                "permission_codes": permissions,
                "thread": thread,
                "channel": channel,
                **view_data,
                **_classification_context(),
                **workflow_context,
                "status_labels": STATUS_LABELS,
                "can_triage": can_alter,
                "can_reply": bool(
                    permissions.intersection({"email.reply", "email.manage", "admin.manage"})
                )
                and _can_use_channel(
                    db, user_id, permissions, thread.channel_id, "reply", thread=thread
                ),
                "outbound_enabled": settings.email_outbound_enabled,
                "embedded": False,
                "foundation_ui_enabled": settings.visual_foundation_enabled,
                "return_context": return_context,
            },
        )


@email_router.get("/v2-clean/email/{thread_id}/preview", response_class=HTMLResponse)
def email_thread_preview(request: Request, thread_id: int):
    auth = _auth(
        request,
        "email.read",
        "email.triage",
        "email.reply",
        "email.approve",
        "email.manage",
        "admin.manage",
    )
    if not auth:
        return HTMLResponse("Sessão sem acesso a esta conversa.", status_code=403)
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, thread=thread
        ):
            return HTMLResponse("Conversa não encontrada.", status_code=404)
        channel = db.get(EmailChannel, thread.channel_id)
        view_data = _thread_view_data(db, thread)
        reply_channels, reply_channel_send_direct = _reply_channel_context(
            db, user_id, permissions
        )
        eligible_users = [
            item
            for item in email_eligible_users(
                db, thread.channel_id, thread.work_category_id
            )
            if assignment_target_user_allowed(
                db, actor_user_id=user_id, target_user_id=item.id
            )
        ]
        eligible_teams = email_eligible_teams(db, thread.channel_id, thread.work_category_id)
        thread_assignee = db.get(User, thread.assigned_to_id) if thread.assigned_to_id else None
        thread_team = db.get(Team, thread.executor_team_id) if thread.executor_team_id else None
        if thread_assignee and all(item.id != thread_assignee.id for item in eligible_users):
            eligible_users.append(thread_assignee)
        if thread_team and all(item.id != thread_team.id for item in eligible_teams):
            eligible_teams.append(thread_team)
        can_alter = bool(
            permissions.intersection({"email.triage", "email.manage", "admin.manage"})
        ) and _can_use_channel(
            db, user_id, permissions, thread.channel_id, "alter", thread=thread
        )
        workflow_context = {
            **work_hierarchy_context(db),
            **_reply_all_context(
                db,
                view_data,
                db.get(EmailChannel, thread.channel_id),
            ),
            "can_propose_classification": "classification.propose" in permissions,
            "can_use_provisional_classification": "classification.provisional.use"
            in permissions,
            "email_users": eligible_users,
            "email_teams": eligible_teams,
            "email_assignment_label": assignment_label(
                state=thread.assignment_state,
                user_name=thread_assignee.name if thread_assignee else None,
                team_name=thread_team.name if thread_team else None,
            ),
            "email_sla": sla_snapshot(thread),
            "functional_owner": (
                db.get(User, thread.functional_owner_user_id)
                if thread.functional_owner_user_id
                else None
            ),
            "can_claim": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "assume", thread=thread
            ),
            "can_assign": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "assign", thread=thread
            ),
            "can_manage_sla": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "manage_sla", thread=thread
            ),
            "can_alter": can_alter,
            "can_create_task": can_alter
            and bool(
                permissions.intersection(
                    {
                        "tasks.write",
                        "tasks.operational.write",
                        "tasks.administration.write",
                        "admin.manage",
                    }
                )
            ),
            "email_templates": _ranked_email_templates(db, thread),
            "reply_defaults": _reply_defaults(db, thread),
            "reply_sender_address": _channel_sender_address(db, thread, channel),
            "reply_sender_options": _channel_sender_options(db, channel),
            "can_change_sender": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "change_sender", thread=thread
            ),
            "can_edit_recipients": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "edit_recipients", thread=thread
            ),
            "can_use_cc_bcc": _can_use_channel(
                db, user_id, permissions, thread.channel_id, "use_cc_bcc", thread=thread
            ),
            "reply_channels": reply_channels,
            "reply_channel_send_direct": reply_channel_send_direct,
            "approvable_message_ids": {
                message.id
                for message in view_data["messages"]
                if permissions.intersection(
                    {"email.approve", "email.manage", "admin.manage"}
                )
                and message.state == "pending_approval"
                and message.approval_fingerprint == _message_fingerprint(message)
                and (sender_channel := _sender_channel(db, message)) is not None
                and _can_use_channel(
                    db, user_id, permissions, sender_channel.id, "approve"
                )
            },
        }
        return templates.TemplateResponse(
            request,
            "_email_thread_content.html",
            {
                "thread": thread,
                "channel": db.get(EmailChannel, thread.channel_id),
                **view_data,
                **_classification_context(),
                **workflow_context,
                "status_labels": STATUS_LABELS,
                "can_triage": can_alter,
                "can_reply": bool(
                    permissions.intersection({"email.reply", "email.manage", "admin.manage"})
                )
                and _can_use_channel(
                    db, user_id, permissions, thread.channel_id, "reply", thread=thread
                ),
                "outbound_enabled": settings.email_outbound_enabled,
                "embedded": True,
            },
        )


@email_router.get("/v2-clean/email/messages/{message_id}/body", response_class=HTMLResponse)
def email_message_body(request: Request, message_id: int, view: str = "html"):
    auth = _auth(
        request,
        "email.read",
        "email.triage",
        "email.reply",
        "email.approve",
        "email.manage",
        "admin.manage",
    )
    if not auth:
        return HTMLResponse("Sem acesso.", status_code=403)
    user_id, permissions = auth
    with SessionLocal() as db:
        message = db.get(EmailMessage, message_id)
        if not message:
            return HTMLResponse("Mensagem não encontrada.", status_code=404)
        thread = db.get(EmailThread, message.thread_id)
        if not _can_use_channel(
            db, user_id, permissions, thread.channel_id, thread=thread
        ):
            return HTMLResponse("Sem acesso.", status_code=403)
        return HTMLResponse(
            _safe_email_document(message, plain_text=view == "text"),
            headers={
                "Content-Security-Policy": (
                    "default-src 'none'; img-src https: http:; "
                    "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"
                )
            },
        )


@email_router.post("/v2-clean/email/{thread_id}/triage")
def email_triage(
    request: Request,
    thread_id: int,
    content_type: str = Form(""),
    nature: str = Form(""),
    document_type: str = Form(""),
    triage_notes: str = Form(""),
    work_queue_id: str = Form(""),
    work_department_id: str = Form(""),
    work_category_id: str = Form(""),
    work_subcategory_id: str = Form(""),
    classification_other_text: str = Form(""),
    assigned_to_id: str = Form(""),
    executor_team_id: str = Form(""),
    team_requires_claim: str = Form(""),
    due_at: str = Form(""),
    waiting_until: str = Form(""),
):
    auth = _auth(request, "email.triage", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, permissions = auth
    if (
        content_type
        and content_type not in CONTENT_TYPES
        or nature
        and nature not in WORK_NATURES
        or document_type
        and document_type not in DOCUMENT_TYPES
    ):
        return RedirectResponse(
            f"/v2-clean/email/{thread_id}?error=invalid_classification", status_code=303
        )
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "alter", thread=thread
        ):
            return RedirectResponse("/v2-clean/email?error=not_found", status_code=303)
        hierarchy_selection = None
        proposal_selection = None
        if work_queue_id.strip() or work_department_id.strip():
            official_category_id, category_proposal_id = parse_classification_choice(
                work_category_id
            )
            official_subcategory_id, subcategory_proposal_id = parse_classification_choice(
                work_subcategory_id
            )
            uses_provisional = bool(category_proposal_id or subcategory_proposal_id)
            required_permission = (
                "classification.provisional.use"
                if uses_provisional
                else "classification.active.use"
            )
            if required_permission not in permissions:
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
                )
            hierarchy_selection = validate_work_hierarchy(
                db,
                queue_id=int(work_queue_id) if work_queue_id.isdigit() else None,
                department_id=(
                    int(work_department_id) if work_department_id.isdigit() else None
                ),
                category_id=official_category_id,
                subcategory_id=official_subcategory_id,
                other_text=classification_other_text,
            )
            if not hierarchy_selection:
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=invalid_hierarchy",
                    status_code=303,
                )
            try:
                proposal_selection = validate_proposal_selection(
                    db,
                    department_id=hierarchy_selection.department.id,
                    official_category_id=official_category_id,
                    category_proposal_id=category_proposal_id,
                    subcategory_proposal_id=subcategory_proposal_id,
                )
            except ValueError:
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=invalid_hierarchy",
                    status_code=303,
                )
        assignee = (
            db.get(User, int(assigned_to_id)) if assigned_to_id.isdigit() else None
        )
        executor_team = (
            db.get(Team, int(executor_team_id)) if executor_team_id.isdigit() else None
        )
        if assignee and executor_team:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=assignment_not_allowed",
                status_code=303,
            )
        target_category_id = (
            hierarchy_selection.category.id
            if hierarchy_selection and hierarchy_selection.category
            else thread.work_category_id
        )
        eligible_user_ids = {
            item.id for item in email_eligible_users(db, thread.channel_id, target_category_id)
        }
        eligible_team_ids = {
            item.id for item in email_eligible_teams(db, thread.channel_id, target_category_id)
        }
        new_user_id = assignee.id if assignee and assignee.active else None
        new_team_id = executor_team.id if executor_team and executor_team.active else None
        assignment_changed = (
            thread.assigned_to_id != new_user_id
            or thread.executor_team_id != new_team_id
            or (
                new_team_id is not None
                and (thread.assignment_state == "team_unclaimed")
                != (team_requires_claim == "on")
            )
        )
        if assignment_changed and not _can_use_channel(
            db,
            user_id,
            permissions,
            thread.channel_id,
            "assign",
            thread=thread,
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        if new_user_id and new_user_id not in eligible_user_ids:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=assignment_not_allowed",
                status_code=303,
            )
        if new_user_id and not assignment_target_user_allowed(
            db, actor_user_id=user_id, target_user_id=new_user_id
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=assignment_not_allowed",
                status_code=303,
            )
        if new_team_id and new_team_id not in eligible_team_ids:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=assignment_not_allowed",
                status_code=303,
            )
        parsed_due_at = _optional_datetime(due_at)
        if parsed_due_at != thread.resolution_due_at and not _can_use_channel(
            db,
            user_id,
            permissions,
            thread.channel_id,
            "manage_sla",
            thread=thread,
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        thread.content_type = content_type or None
        thread.nature = nature or None
        thread.document_type = document_type or None
        thread.triage_notes = triage_notes.strip() or None
        if assignment_changed:
            previous = {
                "user_id": thread.assigned_to_id,
                "team_id": thread.executor_team_id,
                "state": thread.assignment_state,
            }
            thread.assigned_to_id = new_user_id
            thread.executor_team_id = new_team_id
            thread.assignment_state = (
                "assigned_user"
                if new_user_id
                else "team_unclaimed"
                if new_team_id and team_requires_claim == "on"
                else "assigned_team"
                if new_team_id
                else "waiting_assignment"
            )
            thread.assignment_mode = (
                "auto_user"
                if new_user_id
                else "team_claim"
                if new_team_id and team_requires_claim == "on"
                else "auto_team"
                if new_team_id
                else "manual"
            )
            thread.assigned_by_id = user_id
            thread.assigned_at = datetime.now(UTC) if new_user_id or new_team_id else None
            db.add(
                EmailAuditEvent(
                    thread_id=thread.id,
                    user_id=user_id,
                    action=(
                        "reassigned"
                        if previous["user_id"] or previous["team_id"]
                        else "assigned"
                    ),
                    details_json={
                        "before": previous,
                        "user_id": new_user_id,
                        "team_id": new_team_id,
                        "state": thread.assignment_state,
                    },
                )
            )
        thread.due_at = parsed_due_at
        thread.resolution_due_at = parsed_due_at
        thread.waiting_until = _optional_datetime(waiting_until)
        if hierarchy_selection:
            detach_entity_proposals(db, entity=thread, actor_user_id=user_id)
            thread.work_queue_id = hierarchy_selection.queue.id
            thread.work_department_id = hierarchy_selection.department.id
            thread.work_category_id = (
                hierarchy_selection.category.id if hierarchy_selection.category else None
            )
            thread.work_subcategory_id = (
                hierarchy_selection.subcategory.id
                if hierarchy_selection.subcategory
                else None
            )
            thread.classification_status = hierarchy_selection.status
            thread.classification_other_text = hierarchy_selection.other_text
            channel_policy = db.get(EmailChannel, thread.channel_id)
            thread.administrative_review_required = bool(
                channel_policy
                and channel_policy.administrative_review_on_unclassified
                and hierarchy_selection.status != "classified"
            )
            thread.classification_updated_by_id = user_id
            thread.classification_updated_at = datetime.now(UTC)
            if proposal_selection and (
                proposal_selection.category or proposal_selection.subcategory
            ):
                attach_selection_to_entity(
                    db,
                    entity=thread,
                    selection=proposal_selection,
                    actor_user_id=user_id,
                    module="email",
                    origin_url=str(request.url),
                )
        thread.status = "in_progress" if thread.status == "triage" else thread.status
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                user_id=user_id,
                action="triage_saved",
                details_json={
                    "content_type": thread.content_type,
                    "nature": thread.nature,
                    "document_type": thread.document_type,
                    "work_queue_id": thread.work_queue_id,
                    "work_department_id": thread.work_department_id,
                    "work_category_id": thread.work_category_id,
                    "work_subcategory_id": thread.work_subcategory_id,
                    "assigned_to_id": thread.assigned_to_id,
                },
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=triage", status_code=303)


@email_router.get(
    "/v2-clean/email/attachments/{attachment_id}/preview", response_class=HTMLResponse
)
def email_attachment_preview(request: Request, attachment_id: int):
    auth = _auth(request, "email.read", "email.triage", "email.manage", "admin.manage")
    if not auth:
        return HTMLResponse("Sem acesso.", status_code=403)
    user_id, permissions = auth
    with SessionLocal() as db:
        attachment = db.get(EmailAttachment, attachment_id)
        message = db.get(EmailMessage, attachment.message_id) if attachment else None
        thread = db.get(EmailThread, message.thread_id) if message else None
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, thread=thread
        ):
            return HTMLResponse("Anexo não encontrado.", status_code=404)
        view_data = _thread_view_data(db, thread)
        reference = next(
            (
                row["reference"]
                for rows in view_data["attachments_by_message"].values()
                for row in rows
                if row["item"].id == attachment.id
            ),
            f"A-{attachment.id}",
        )
        return templates.TemplateResponse(
            request,
            "_email_attachment_preview.html",
            {
                "attachment": attachment,
                "thread": thread,
                "reference": reference,
                "can_preview": _attachment_can_preview(attachment),
                "can_alter": bool(
                    permissions.intersection(
                        {"email.triage", "email.manage", "admin.manage"}
                    )
                )
                and _can_use_channel(
                    db,
                    user_id,
                    permissions,
                    thread.channel_id,
                    "alter",
                    thread=thread,
                ),
                **_classification_context(),
            },
        )


@email_router.get("/v2-clean/email/attachments/{attachment_id}/file")
def email_attachment_file(request: Request, attachment_id: int, download: bool = False):
    auth = _auth(request, "email.read", "email.triage", "email.manage", "admin.manage")
    if not auth:
        return HTMLResponse("Sem acesso.", status_code=403)
    user_id, permissions = auth
    with SessionLocal() as db:
        attachment = db.get(EmailAttachment, attachment_id)
        message = db.get(EmailMessage, attachment.message_id) if attachment else None
        thread = db.get(EmailThread, message.thread_id) if message else None
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, thread=thread
        ):
            return HTMLResponse("Anexo não encontrado.", status_code=404)
        path = Path(attachment.storage_path)
        if not path.is_file():
            return HTMLResponse("Ficheiro indisponível.", status_code=404)

        media_type = _attachment_media_type(attachment)
        can_preview = _attachment_can_preview(attachment)
        if not can_preview and not download:
            return HTMLResponse(
                "Este formato não tem pré-visualização segura. Usa a ação Descarregar.",
                status_code=415,
            )

        return FileResponse(
            path,
            media_type=media_type,
            filename=attachment.file_name if download else None,
            headers={"Content-Disposition": "inline"} if can_preview and not download else None,
        )


@email_router.post("/v2-clean/email/attachments/{attachment_id}/classify")
def email_attachment_classify(
    request: Request,
    attachment_id: int,
    document_type: str = Form(""),
    nature: str = Form(""),
    destination: str = Form(""),
    status: str = Form("classified"),
    notes: str = Form(""),
):
    auth = _auth(request, "email.triage", "email.manage", "admin.manage")
    if not auth:
        return HTMLResponse("Sem acesso.", status_code=403)
    user_id, permissions = auth
    if (
        document_type
        and document_type not in DOCUMENT_TYPES
        or nature
        and nature not in WORK_NATURES
        or destination
        and destination not in WORK_NATURES
        or status not in ATTACHMENT_STATUSES
    ):
        return HTMLResponse("Classificação inválida.", status_code=422)
    with SessionLocal() as db:
        attachment = db.get(EmailAttachment, attachment_id)
        message = db.get(EmailMessage, attachment.message_id) if attachment else None
        thread = db.get(EmailThread, message.thread_id) if message else None
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "alter", thread=thread
        ):
            return HTMLResponse("Anexo não encontrado.", status_code=404)
        attachment.document_type = document_type or None
        attachment.nature = nature or None
        attachment.destination = destination or nature or None
        attachment.status = status
        attachment.notes = notes.strip() or None
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                user_id=user_id,
                action="attachment_classified",
                details_json={
                    "attachment_id": attachment.id,
                    "document_type": attachment.document_type,
                    "nature": attachment.nature,
                    "destination": attachment.destination,
                    "status": attachment.status,
                },
            )
        )
        db.commit()
    return HTMLResponse("<div class='email-notice'>Classificação do anexo guardada.</div>")


@email_router.post("/v2-clean/email/channel-access")
def email_channel_access(
    request: Request,
    channel_id: int = Form(...),
    user_id: int = Form(...),
    enabled: bool = Form(False),
    can_reply: bool = Form(False),
    can_approve: bool = Form(False),
):
    auth = _auth(request, "admin.manage")
    if not auth:
        return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)
    # Legacy form target kept as a safe redirect. Mailbox permissions are now
    # managed exclusively in Administração > Operações e Service Desk > Email.
    return RedirectResponse(
        "/v2-clean/admin/work-classification?view=channels", status_code=303
    )


@email_router.post("/v2-clean/email/{thread_id}/status")
def email_status(request: Request, thread_id: int, status: str = Form(...)):
    auth = _auth(request, "email.triage", "email.manage", "admin.manage")
    if not auth or status not in STATUS_LABELS:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, _ = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        action = (
            "manage_sla"
            if status in {"waiting_reply", "resolved"}
            or thread and thread.status == "resolved"
            else "alter"
        )
        if thread and _can_use_channel(
            db, user_id, auth[1], thread.channel_id, action, thread=thread
        ):
            prior_status = thread.status
            thread.status = status
            if status == "resolved":
                mark_email_resolved(db, thread, user_id=user_id)
            elif prior_status == "resolved":
                reopened_at = datetime.now(UTC)
                thread.resolved_at = None
                thread.resolution_due_at = (
                    reopened_at + timedelta(minutes=thread.sla_resolution_minutes)
                    if thread.sla_resolution_minutes is not None
                    else None
                )
                thread.due_at = thread.resolution_due_at
                db.add(
                    EmailAuditEvent(
                        thread_id=thread.id,
                        user_id=user_id,
                        action="sla_reopened",
                        details_json={"resolution_due_at": (
                            thread.resolution_due_at.isoformat()
                            if thread.resolution_due_at
                            else None
                        )},
                    )
                )
            if prior_status == "waiting_reply" and status != "waiting_reply":
                transition_email_waiting(
                    db,
                    thread,
                    waiting=False,
                    user_id=user_id,
                    reason="Conversa retomada",
                )
            if status == "waiting_reply" and prior_status != "waiting_reply":
                transition_email_waiting(
                    db,
                    thread,
                    waiting=True,
                    user_id=user_id,
                    reason="A aguardar resposta externa",
                )
            db.add(
                EmailAuditEvent(
                    thread_id=thread.id,
                    user_id=user_id,
                    action="status_changed",
                    details_json={"status": status},
                )
            )
            db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=status", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/read")
def email_mark_read(request: Request, thread_id: int):
    auth = _auth(request, "email.triage", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(
            f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
        )
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "alter", thread=thread
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        messages = db.scalars(
            select(EmailMessage).where(
                EmailMessage.thread_id == thread.id,
                EmailMessage.direction == "inbound",
                EmailMessage.state == "received",
            )
        ).all()
        for message in messages:
            message.state = "read"
        if messages:
            db.add(
                EmailAuditEvent(
                    thread_id=thread.id,
                    user_id=user_id,
                    action="marked_read",
                    details_json={"message_ids": [message.id for message in messages]},
                )
            )
            db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=read", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/claim")
def email_claim(request: Request, thread_id: int):
    auth = _auth(request, "email.assume", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(
            f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
        )
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db,
            user_id,
            permissions,
            thread.channel_id,
            "assume",
            thread=thread,
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        try:
            claim_email_thread(db, thread, user_id=user_id)
        except ValueError:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=assignment_not_allowed",
                status_code=303,
            )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=claimed", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/reply")
def email_reply(
    request: Request,
    thread_id: int,
    body: str = Form(""),
    recipient_email: str = Form(""),
    reply_mode: str = Form("sender"),
    reply_source_message_id: int | None = Form(None),
    recipients: str = Form(""),
    cc: str = Form(""),
    bcc: str = Form(""),
    subject: str = Form(""),
    mode: str = Form("reply"),
    sender_address: str = Form(""),
    template_id: str = Form(""),
    submit: str = Form("draft"),
    attachments: Annotated[list[UploadFile] | None, File()] = None,
):
    auth = _auth(request, "email.reply", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    if submit not in {"draft", "approval", "send"}:
        return RedirectResponse(
            f"/v2-clean/email/{thread_id}?error=invalid_action", status_code=303
        )
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db,
            user_id,
            permissions,
            thread.channel_id,
            "reply",
            thread=thread,
        ):
            return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
        sender_channel = db.get(EmailChannel, thread.channel_id)
        if (
            not sender_channel
            or not sender_channel.active
            or not _can_use_channel(
                db, user_id, permissions, sender_channel.id, "reply"
            )
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        if submit == "send" and not _can_use_channel(
            db, user_id, permissions, sender_channel.id, "send_direct"
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        if reply_mode == "all" and mode == "reply":
            mode = "reply_all"
        if mode not in {"reply", "reply_all", "forward"}:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=invalid_mode", status_code=303
            )
        defaults = _reply_defaults(db, thread)
        can_edit_recipients = _can_use_channel(
            db, user_id, permissions, thread.channel_id, "edit_recipients", thread=thread
        )
        can_use_cc_bcc = _can_use_channel(
            db, user_id, permissions, thread.channel_id, "use_cc_bcc", thread=thread
        )
        try:
            requested_to = _address_values(recipients or recipient_email)
            requested_cc = _address_values(cc)
            requested_bcc = _address_values(bcc)
        except ValueError:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=invalid_recipient", status_code=303
            )
        default_to = (
            list(defaults["reply_all_to"])
            if mode == "reply_all"
            else [str(defaults["reply_to"])]
            if mode == "reply" and defaults["reply_to"]
            else []
        )
        default_cc = list(defaults["reply_all_cc"]) if mode == "reply_all" else []
        if mode == "forward" and not can_edit_recipients:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        if can_edit_recipients:
            to_list = requested_to or default_to
        else:
            to_list = default_to
            if requested_to and requested_to != default_to:
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
                )
        if can_use_cc_bcc:
            cc_list = requested_cc or default_cc
            bcc_list = requested_bcc
        else:
            cc_list = default_cc
            bcc_list = []
            if requested_bcc or requested_cc and requested_cc != default_cc:
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
                )
        if not to_list:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=invalid_recipient", status_code=303
            )
        policy_sender = _channel_sender_address(db, thread, sender_channel)
        requested_sender = sender_address.strip().lower() or policy_sender
        configured_senders = {
            item
            for item in (sender_channel.address, sender_channel.default_reply_address)
            if item
        }
        configured_senders.update(
            db.scalars(
                select(EmailChannelAlias.address).where(
                    EmailChannelAlias.channel_id == sender_channel.id,
                    EmailChannelAlias.active.is_(True),
                )
            )
        )
        configured_senders = {item.casefold() for item in configured_senders}
        if not requested_sender or requested_sender not in configured_senders:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=sender_not_configured", status_code=303
            )
        if requested_sender != policy_sender and not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "change_sender", thread=thread
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        template = db.get(EmailTemplate, int(template_id)) if template_id.isdigit() else None
        if template and (
            not template.active
            or template.channel_id not in {None, thread.channel_id}
            or template.category_id not in {None, thread.work_category_id}
            or template.subcategory_id not in {None, thread.work_subcategory_id}
            or template.supplier_id is not None
            or template.supplier_type_id is not None
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=invalid_template", status_code=303
            )
        prefix = "Fwd" if mode == "forward" else "Re"
        clean_subject = subject.strip() or f"{prefix}: {thread.subject}"
        template_context = {
            "recipient_name": thread.sender_name or thread.sender_email or "",
            "sender_email": thread.sender_email or "",
            "subject": thread.subject,
            "thread_reference": thread_reference(thread),
        }
        try:
            clean_subject = _render_email_template(clean_subject, template_context)
            clean_body = _render_email_template(
                body.strip() or (template.body_template if template else ""),
                template_context,
            )
        except ValueError:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=template_variables_missing",
                status_code=303,
            )
        if not clean_body:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=missing_message", status_code=303
            )
        state = {
            "approval": "pending_approval",
            "send": "approved",
        }.get(submit, "draft")
        message = EmailMessage(
            thread_id=thread.id,
            direction="outbound",
            state=state,
            sender=requested_sender,
            recipients_json=_recipient_json(to_list),
            cc_json=_recipient_json(cc_list),
            bcc_json=_recipient_json(bcc_list),
            subject=clean_subject[:500],
            text_body=clean_body,
            compose_mode=mode,
            template_id=template.id if template else None,
            template_version=template.version if template else None,
            template_snapshot_json=email_template_snapshot(
                template, rendered_subject=clean_subject, rendered_body=clean_body
            ),
            created_by_id=user_id,
        )
        message.approval_fingerprint = _message_fingerprint(message)
        db.add(message)
        db.flush()
        try:
            outbound_attachments = _store_outbound_attachments(
                db,
                thread=thread,
                message=message,
                uploads=attachments or [],
            )
        except ValueError:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=attachment_too_large",
                status_code=303,
            )
        thread.status = "waiting_approval" if state == "pending_approval" else "in_progress"
        if submit == "send":
            prior_messages = db.scalars(
                select(EmailMessage)
                .where(
                    EmailMessage.thread_id == thread.id,
                    EmailMessage.external_message_id.is_not(None),
                )
                .order_by(EmailMessage.id)
            ).all()
            parent_message_id = prior_messages[-1].external_message_id if prior_messages else None
            references = [
                item.external_message_id for item in prior_messages if item.external_message_id
            ]
            try:
                result = send_message(
                    message,
                    requested_sender,
                    reply_to=requested_sender,
                    parent_message_id=parent_message_id,
                    references=references,
                    attachments=outbound_attachments,
                )
            except RuntimeError as exc:
                message.postmark_error = str(exc)
                db.commit()
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=send_disabled", status_code=303
                )
            now = datetime.now(UTC)
            message.state = "sent"
            message.sent_at = now
            message.approved_by_id = user_id
            message.approved_at = now
            message.approved_revision = message.content_revision
            message.external_message_id = result.get("MessageID") or message.external_message_id
            thread.status = "waiting_reply"
            mark_email_first_response(db, thread, user_id=user_id, now=now)
            transition_email_waiting(
                db,
                thread,
                waiting=True,
                user_id=user_id,
                reason="A aguardar resposta externa",
                now=now,
            )
            state = "sent"
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                user_id=user_id,
                action=state,
                details_json={
                    "sender_channel_id": sender_channel.id,
                    "sender": requested_sender,
                    "reply_policy": sender_channel.reply_policy,
                    "mode": mode,
                    "to": to_list,
                    "cc": cc_list,
                    "bcc": bcc_list,
                    "template_id": template.id if template else None,
                    "template_version": template.version if template else None,
                    "content_revision": message.content_revision,
                    "source_message_id": reply_source_message_id,
                },
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved={state}", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/messages/{message_id}/draft")
def email_update_draft(
    request: Request,
    thread_id: int,
    message_id: int,
    body: str = Form(...),
    recipients: str = Form(""),
    cc: str = Form(""),
    bcc: str = Form(""),
    subject: str = Form(""),
):
    auth = _auth(request, "email.reply", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        message = db.get(EmailMessage, message_id)
        if (
            not thread
            or not message
            or message.thread_id != thread.id
            or message.direction != "outbound"
            or message.state not in {"draft", "pending_approval"}
            or not _can_use_channel(
                db, user_id, permissions, thread.channel_id, "reply", thread=thread
            )
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        try:
            to_list = _address_values(recipients)
            cc_list = _address_values(cc)
            bcc_list = _address_values(bcc)
        except ValueError:
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=invalid_recipient", status_code=303
            )
        if not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "edit_recipients", thread=thread
        ) and (
            to_list != [item.get("Email") for item in message.recipients_json or []]
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        if not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "use_cc_bcc", thread=thread
        ) and (cc_list or bcc_list):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        prior_state = message.state
        message.subject = (subject.strip() or message.subject)[:500]
        message.text_body = body.strip()
        message.recipients_json = _recipient_json(to_list) if to_list else message.recipients_json
        message.cc_json = _recipient_json(cc_list)
        message.bcc_json = _recipient_json(bcc_list)
        message.content_revision += 1
        message.state = "draft"
        message.approval_fingerprint = None
        message.approved_by_id = None
        message.approved_at = None
        message.approved_revision = None
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                user_id=user_id,
                action=(
                    "approval_invalidated_by_edit"
                    if prior_state == "pending_approval"
                    else "outbound_draft_edited"
                ),
                details_json={
                    "content_revision": message.content_revision,
                    "to": message.recipients_json or [],
                    "cc": message.cc_json or [],
                    "bcc": message.bcc_json or [],
                },
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=draft", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/messages/{message_id}/approve")
def email_approve(request: Request, thread_id: int, message_id: int):
    auth = _auth(request, "email.approve", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, _ = auth
    with SessionLocal() as db:
        message = db.get(EmailMessage, message_id)
        thread = db.get(EmailThread, thread_id)
        sender_channel = _sender_channel(db, message) if message else None
        if (
            not thread
            or not message
            or message.thread_id != thread.id
            or not _can_use_channel(
                db, user_id, auth[1], thread.channel_id, thread=thread
            )
            or not sender_channel
            or not _can_use_channel(
                db, user_id, auth[1], sender_channel.id, "approve"
            )
        ):
            return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
        if (
            message.state != "pending_approval"
            or not message.approval_fingerprint
            or message.approval_fingerprint != _message_fingerprint(message)
        ):
            message.state = "draft"
            message.approved_by_id = None
            message.approved_at = None
            message.approved_revision = None
            db.add(
                EmailAuditEvent(
                    thread_id=thread.id,
                    message_id=message.id,
                    user_id=user_id,
                    action="approval_invalidated",
                    details_json={"content_revision": message.content_revision},
                )
            )
            db.commit()
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=approval_invalidated",
                status_code=303,
            )
        prior_messages = db.scalars(
            select(EmailMessage)
            .where(
                EmailMessage.thread_id == thread.id,
                EmailMessage.external_message_id.is_not(None),
            )
            .order_by(EmailMessage.id)
        ).all()
        parent_message_id = (
            prior_messages[-1].external_message_id if prior_messages else None
        )
        references = [
            item.external_message_id for item in prior_messages if item.external_message_id
        ]
        outbound_attachments = list(
            db.scalars(
                select(EmailAttachment)
                .where(EmailAttachment.message_id == message.id)
                .order_by(EmailAttachment.id)
            )
        )
        try:
            result = send_message(
                message,
                message.sender,
                reply_to=message.sender,
                parent_message_id=parent_message_id,
                references=references,
                attachments=outbound_attachments,
            )
            message.state, message.sent_at, message.approved_by_id, message.approved_at = (
                "sent",
                datetime.now(UTC),
                user_id,
                datetime.now(UTC),
            )
            message.external_message_id = result.get("MessageID") or message.external_message_id
            message.approved_revision = message.content_revision
            thread.status = "waiting_reply"
            mark_email_first_response(db, thread, user_id=user_id)
            transition_email_waiting(
                db,
                thread,
                waiting=True,
                user_id=user_id,
                reason="A aguardar resposta externa",
            )
        except RuntimeError as exc:
            message.postmark_error = str(exc)
            db.commit()
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=send_disabled", status_code=303
            )
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                user_id=user_id,
                action="approved_and_sent",
                details_json={
                    "sender_channel_id": sender_channel.id,
                    "sender": message.sender,
                    "to": message.recipients_json or [],
                    "cc": message.cc_json or [],
                    "bcc": message.bcc_json or [],
                    "template_id": message.template_id,
                    "template_version": message.template_version,
                    "content_revision": message.content_revision,
                },
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=sent", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/links")
def email_add_link(
    request: Request,
    thread_id: int,
    link_type: str = Form(...),
    link_kind: str = Form(""),
    label: str = Form(...),
    reference: str = Form(""),
    url: str = Form(""),
):
    auth = _auth(request, "email.triage", "email.manage", "admin.manage")
    resolved_link_kind = link_kind or link_type
    if (
        not auth
        or link_type not in {"process", "entity"}
        or resolved_link_kind not in EMAIL_LINK_KINDS
        or (resolved_link_kind == "process") != (link_type == "process")
        or not label.strip()
    ):
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "alter", thread=thread
        ):
            return RedirectResponse(
                f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
            )
        link = EmailThreadLink(
            thread_id=thread.id,
            link_type=link_type,
            label=f"{EMAIL_LINK_KINDS[resolved_link_kind]} · {label.strip()}"[:200],
            reference=reference.strip()[:255] or None,
            url=url.strip() or None,
            created_by_id=user_id,
        )
        db.add(link)
        db.flush()
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                user_id=user_id,
                action=f"{link_type}_linked",
                details_json={
                    "link_id": link.id,
                    "link_kind": resolved_link_kind,
                    "label": link.label,
                    "reference": link.reference,
                    "url": link.url,
                },
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=linked", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/task")
def email_create_task(request: Request, thread_id: int):
    auth = _auth(
        request,
        "tasks.write",
        "tasks.operational.write",
        "tasks.administration.write",
        "email.manage",
        "admin.manage",
    )
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(
            db, user_id, permissions, thread.channel_id, "alter", thread=thread
        ):
            return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
        if not thread.task_id:
            proposal_selection = None
            if thread.provisional_category_id or thread.provisional_subcategory_id:
                if "classification.provisional.use" not in permissions:
                    return RedirectResponse(
                        f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
                    )
                try:
                    proposal_selection = validate_proposal_selection(
                        db,
                        department_id=thread.work_department_id,
                        official_category_id=thread.work_category_id,
                        category_proposal_id=thread.provisional_category_id,
                        subcategory_proposal_id=thread.provisional_subcategory_id,
                    )
                except ValueError:
                    return RedirectResponse(
                        f"/v2-clean/email/{thread_id}?error=invalid_hierarchy",
                        status_code=303,
                    )
            hierarchy = validate_work_hierarchy(
                db,
                queue_id=thread.work_queue_id,
                department_id=thread.work_department_id,
                category_id=thread.work_category_id,
                subcategory_id=thread.work_subcategory_id,
                other_text=thread.classification_other_text or "",
            ) if thread.work_queue_id and thread.work_department_id else None
            task_type, category = task_classification(thread.nature)
            if hierarchy:
                task_type = (
                    "administration_task"
                    if hierarchy.queue.code == "administration"
                    else "operational_task"
                )
            workspace_permission = (
                "tasks.administration.write"
                if task_type == "administration_task"
                else "tasks.operational.write"
            )
            if not permissions.intersection(
                {"admin.manage", "tasks.write", workspace_permission}
            ):
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
                )
            if hierarchy and not user_work_scope_allows(
                db,
                user_id=user_id,
                queue_id=hierarchy.queue.id,
                department_id=hierarchy.department.id,
                category_id=hierarchy.category.id if hierarchy.category else None,
                subcategory_id=(
                    hierarchy.subcategory.id if hierarchy.subcategory else None
                ),
                action="create",
            ):
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303
                )
            task = Task(
                title=thread.subject[:200],
                description=(
                    f"Criada a partir da conversa {thread_reference(thread)}.\n\n"
                    f"{thread.triage_notes or ''}"
                ).strip(),
                task_type=task_type,
                category=category,
                subcategory=thread.document_type or thread.content_type,
                work_queue_id=thread.work_queue_id,
                work_department_id=thread.work_department_id,
                work_category_id=thread.work_category_id,
                work_subcategory_id=thread.work_subcategory_id,
                classification_status=thread.classification_status,
                classification_other_text=thread.classification_other_text,
                classification_updated_by_id=user_id,
                classification_updated_at=datetime.now(UTC),
                source="email",
                status="new",
                priority="normal",
                customer_email=thread.sender_email,
                assigned_to_id=None,
                team_id=None,
                due_on=thread.due_at.date() if thread.due_at else None,
                created_by_id=user_id,
            )
            service_desk = ServiceDeskFacade(db)
            service_desk.persist_task(task)
            if proposal_selection and (
                proposal_selection.category or proposal_selection.subcategory
            ):
                attach_selection_to_entity(
                    db,
                    entity=task,
                    selection=proposal_selection,
                    actor_user_id=user_id,
                    module="service_desk",
                    origin_url=f"/v2-clean/email/{thread.id}",
                )
            try:
                service_desk.initialize_task(
                    task,
                    actor_user_id=user_id,
                    requested_user_id=thread.assigned_to_id,
                    requested_team_id=thread.executor_team_id,
                )
            except ValueError:
                service_desk.initialize_task(task, actor_user_id=user_id)
                db.add(
                    EmailAuditEvent(
                        thread_id=thread.id,
                        user_id=user_id,
                        action="task_assignment_not_carried",
                        details_json={
                            "email_user_id": thread.assigned_to_id,
                            "email_team_id": thread.executor_team_id,
                        },
                    )
                )
            first = db.scalar(
                select(EmailMessage)
                .where(EmailMessage.thread_id == thread.id)
                .order_by(EmailMessage.id)
            )
            service_desk.link_email_origin(
                task.id,
                EmailOriginCommand(
                    message_id=first.external_message_id if first else f"email-thread:{thread.id}",
                    sender=first.sender if first else thread.sender_email,
                    recipients=first.recipients_json if first else None,
                    subject=first.subject if first else thread.subject,
                    received_at=first.received_at if first else thread.created_at,
                    mailbox=(
                        thread.original_recipient_address
                        or db.get(EmailChannel, thread.channel_id).default_reply_address
                        or db.get(EmailChannel, thread.channel_id).address
                        or db.get(EmailChannel, thread.channel_id).name
                    ),
                    source_url=f"/v2-clean/email/{thread.id}",
                ),
            )
            thread.task_id, thread.status = task.id, "task_created"
            db.add(
                EmailAuditEvent(
                    thread_id=thread.id,
                    message_id=first.id if first else None,
                    user_id=user_id,
                    action="task_created",
                    details_json={"task_id": task.id},
                )
            )
            db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=task", status_code=303)
