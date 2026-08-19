from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape
from html.parser import HTMLParser
from mimetypes import guess_type
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.admin import User, UserRole
from app.models.email import (
    EmailAttachment,
    EmailAuditEvent,
    EmailChannel,
    EmailChannelRole,
    EmailChannelUser,
    EmailMessage,
    EmailTemplate,
    EmailThread,
)
from app.models.tasks import Task, TaskEmailOrigin
from app.models.work_hierarchy import WorkCategory, WorkDepartment, WorkQueue, WorkSubcategory
from app.services.authorization import get_user_permission_codes
from app.services.email_postmark import (
    ensure_email_channels,
    ingest_inbound,
    send_message,
    webhook_authorized,
)
from app.services.work_classification import (
    ATTACHMENT_STATUSES,
    CONTENT_TYPES,
    DOCUMENT_TYPES,
    WORK_NATURES,
    attachment_reference,
    message_reference,
    task_classification,
    thread_reference,
    validate_work_hierarchy,
    work_hierarchy_context,
)

email_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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


def _safe_email_document(message: EmailMessage) -> str:
    if message.html_body:
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


def _auth(request: Request, *required: str):
    raw_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not raw_id:
        return None
    with SessionLocal() as db:
        user = db.get(User, int(raw_id))
        permissions = get_user_permission_codes(db, user) if user and user.active else set()
    return (int(raw_id), permissions) if permissions.intersection(required) else None


def _channel_access(db, user_id: int, permissions: set[str]) -> dict[int, object | None]:
    channels = list(db.scalars(select(EmailChannel).where(EmailChannel.active.is_(True))))
    if permissions.intersection({"email.manage", "admin.manage"}):
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
    for grant in role_grants:
        current = merged.setdefault(
            grant.channel_id,
            SimpleNamespace(
                can_reply=False,
                can_send_direct=False,
                can_approve=False,
                can_manage=False,
            ),
        )
        current.can_reply = current.can_reply or grant.can_reply
        current.can_send_direct = current.can_send_direct or grant.can_send_direct
        current.can_approve = current.can_approve or grant.can_approve
        current.can_manage = current.can_manage or grant.can_manage
    for grant in user_grants:
        current = merged.setdefault(
            grant.channel_id,
            SimpleNamespace(
                can_reply=False,
                can_send_direct=False,
                can_approve=False,
                can_manage=False,
            ),
        )
        current.can_reply = current.can_reply or grant.can_reply
        current.can_approve = current.can_approve or grant.can_approve
    return merged


def _can_use_channel(
    db, user_id: int, permissions: set[str], channel_id: int, action: str = "read"
) -> bool:
    access = _channel_access(db, user_id, permissions)
    if channel_id not in access:
        return False
    grant = access[channel_id]
    if grant is None or action == "read":
        return True
    if action == "reply":
        return bool(grant.can_reply)
    if action == "approve":
        return bool(grant.can_approve)
    if action == "send_direct":
        return bool(grant.can_send_direct)
    if action == "manage":
        return bool(grant.can_manage)
    return False


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
            )
            .order_by(EmailChannel.name, EmailChannel.address)
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
    return db.scalar(
        select(EmailChannel).where(
            EmailChannel.active.is_(True),
            func.lower(EmailChannel.address) == sender,
        )
    )


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
    return {
        "messages": messages,
        "message_refs": {
            message.id: message_reference(thread, position)
            for position, message in enumerate(messages, 1)
        },
        "attachments_by_message": grouped,
        "thread_reference": thread_reference(thread),
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
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


@email_router.post("/api/webhooks/postmark/inbound")
async def postmark_inbound(request: Request, authorization: str | None = Header(default=None)):
    if not settings.email_inbound_enabled:
        return JSONResponse({"detail": "Email inbound disabled"}, status_code=503)
    if not webhook_authorized(authorization):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    payload = await request.json()
    with SessionLocal() as db:
        thread, created = ingest_inbound(db, payload)
        return {"ok": True, "created": created, "thread_id": thread.id}


@email_router.post("/api/webhooks/postmark/events")
async def postmark_events(request: Request, authorization: str | None = Header(default=None)):
    if not settings.email_inbound_enabled:
        return JSONResponse({"detail": "Email events disabled"}, status_code=503)
    if not webhook_authorized(authorization):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return {"ok": True}


@email_router.get("/v2-clean/email", response_class=HTMLResponse)
def email_inbox(request: Request, status: str = "triage", channel: str = "", q: str = ""):
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
            .where(EmailThread.channel_id.in_(list(channel_access) or [-1]))
        )
        if selected_status != "all":
            query = query.where(EmailThread.status == selected_status)
        if channel:
            query = query.where(EmailChannel.code == channel)
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
        counts = dict(
            db.execute(
                select(EmailThread.status, func.count())
                .where(EmailThread.channel_id.in_(list(channel_access) or [-1]))
                .group_by(EmailThread.status)
            ).all()
        )
        channels = list(
            db.scalars(
                select(EmailChannel)
                .where(EmailChannel.id.in_(list(channel_access) or [-1]))
                .order_by(EmailChannel.name)
            )
        )
        users = list(db.scalars(select(User).order_by(User.name)))
        users_by_id = {item.id: item for item in users}
        now = datetime.now(UTC)
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
                    due_state=due_state,
                )
            )
        compose_channels = [
            item
            for item in channels
            if _can_use_channel(db, user_id, permissions, item.id, "reply")
        ]
        email_templates = list(
            db.scalars(
                select(EmailTemplate)
                .where(EmailTemplate.active.is_(True))
                .order_by(EmailTemplate.name)
            )
        )
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
                "total_count": sum(counts.values()),
                "status_labels": STATUS_LABELS,
                "filters": {
                    "status": selected_status,
                    "channel": channel,
                    "q": clean_query,
                },
                "compose_channels": compose_channels,
                "email_templates": email_templates,
                "channel_send_direct": {
                    item.id: _can_use_channel(
                        db, user_id, permissions, item.id, "send_direct"
                    )
                    for item in compose_channels
                },
            },
        )


@email_router.post("/v2-clean/email/new")
def email_new_message(
    request: Request,
    channel_id: int = Form(...),
    recipients: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    template_id: str = Form(""),
    submit: str = Form("draft"),
):
    auth = _auth(request, "email.reply", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)
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
    with SessionLocal() as db:
        channel = db.get(EmailChannel, channel_id)
        if (
            not channel
            or not channel.active
            or not _can_use_channel(db, user_id, permissions, channel.id, "reply")
        ):
            return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)
        template = db.get(EmailTemplate, int(template_id)) if template_id.isdigit() else None
        if template and (
            not template.active
            or template.channel_id not in {None, channel.id}
        ):
            template = None
        clean_subject = subject.strip() or (template.subject_template if template else "") or ""
        clean_body = body.strip() or (template.body_template if template else "") or ""
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
            assigned_to_id=channel.default_assignee_id,
            due_at=(
                now + timedelta(days=channel.default_due_days)
                if channel.default_due_days is not None
                else None
            ),
            waiting_until=(
                now + timedelta(days=channel.default_wait_days)
                if channel.default_wait_days is not None
                else None
            ),
            last_message_at=now,
        )
        db.add(thread)
        db.flush()
        message = EmailMessage(
            thread_id=thread.id,
            direction="outbound",
            state=state,
            sender=channel.address,
            recipients_json=[{"Email": item} for item in recipient_list],
            subject=clean_subject[:500],
            text_body=clean_body,
            created_by_id=user_id,
        )
        db.add(message)
        db.flush()
        audit_action = state
        if submit == "send":
            try:
                result = send_message(message, channel.address, reply_to=channel.address)
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
            audit_action = "sent"
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                user_id=user_id,
                action=f"new_message_{audit_action}",
                details_json={"template_id": template.id if template else None},
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
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id):
            return RedirectResponse("/v2-clean/email?error=not_found", status_code=303)
        channel = db.get(EmailChannel, thread.channel_id)
        view_data = _thread_view_data(db, thread)
        reply_channels, reply_channel_send_direct = _reply_channel_context(
            db, user_id, permissions
        )
        workflow_context = {
            **work_hierarchy_context(db),
            "email_users": list(
                db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))
            ),
            "email_templates": list(
                db.scalars(
                    select(EmailTemplate)
                    .where(
                        EmailTemplate.active.is_(True),
                        (EmailTemplate.channel_id.is_(None))
                        | (EmailTemplate.channel_id == thread.channel_id),
                    )
                    .order_by(EmailTemplate.name)
                )
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
                "can_triage": bool(
                    permissions.intersection({"email.triage", "email.manage", "admin.manage"})
                ),
                "can_reply": bool(
                    permissions.intersection({"email.reply", "email.manage", "admin.manage"})
                )
                and _can_use_channel(db, user_id, permissions, thread.channel_id, "reply"),
                "outbound_enabled": settings.email_outbound_enabled,
                "embedded": False,
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
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id):
            return HTMLResponse("Conversa não encontrada.", status_code=404)
        view_data = _thread_view_data(db, thread)
        reply_channels, reply_channel_send_direct = _reply_channel_context(
            db, user_id, permissions
        )
        workflow_context = {
            **work_hierarchy_context(db),
            "email_users": list(
                db.scalars(select(User).where(User.active.is_(True)).order_by(User.name))
            ),
            "email_templates": list(
                db.scalars(
                    select(EmailTemplate)
                    .where(
                        EmailTemplate.active.is_(True),
                        (EmailTemplate.channel_id.is_(None))
                        | (EmailTemplate.channel_id == thread.channel_id),
                    )
                    .order_by(EmailTemplate.name)
                )
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
                "can_triage": bool(
                    permissions.intersection({"email.triage", "email.manage", "admin.manage"})
                ),
                "can_reply": bool(
                    permissions.intersection({"email.reply", "email.manage", "admin.manage"})
                )
                and _can_use_channel(db, user_id, permissions, thread.channel_id, "reply"),
                "outbound_enabled": settings.email_outbound_enabled,
                "embedded": True,
            },
        )


@email_router.get("/v2-clean/email/messages/{message_id}/body", response_class=HTMLResponse)
def email_message_body(request: Request, message_id: int):
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
        if not _can_use_channel(db, user_id, permissions, thread.channel_id):
            return HTMLResponse("Sem acesso.", status_code=403)
        return HTMLResponse(
            _safe_email_document(message),
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
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id):
            return RedirectResponse("/v2-clean/email?error=not_found", status_code=303)
        hierarchy_selection = None
        if work_queue_id.strip() or work_department_id.strip():
            hierarchy_selection = validate_work_hierarchy(
                db,
                queue_id=int(work_queue_id) if work_queue_id.isdigit() else None,
                department_id=(
                    int(work_department_id) if work_department_id.isdigit() else None
                ),
                category_id=int(work_category_id) if work_category_id.isdigit() else None,
                subcategory_id=(
                    int(work_subcategory_id) if work_subcategory_id.isdigit() else None
                ),
                other_text=classification_other_text,
            )
            if not hierarchy_selection:
                return RedirectResponse(
                    f"/v2-clean/email/{thread_id}?error=invalid_hierarchy",
                    status_code=303,
                )
        assignee = (
            db.get(User, int(assigned_to_id)) if assigned_to_id.isdigit() else None
        )
        thread.content_type = content_type or None
        thread.nature = nature or None
        thread.document_type = document_type or None
        thread.triage_notes = triage_notes.strip() or None
        thread.assigned_to_id = assignee.id if assignee and assignee.active else None
        thread.due_at = _optional_datetime(due_at)
        thread.waiting_until = _optional_datetime(waiting_until)
        if hierarchy_selection:
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
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id):
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
                **_classification_context(),
            },
        )


@email_router.get("/v2-clean/email/attachments/{attachment_id}/file")
def email_attachment_file(request: Request, attachment_id: int):
    auth = _auth(request, "email.read", "email.triage", "email.manage", "admin.manage")
    if not auth:
        return HTMLResponse("Sem acesso.", status_code=403)
    user_id, permissions = auth
    with SessionLocal() as db:
        attachment = db.get(EmailAttachment, attachment_id)
        message = db.get(EmailMessage, attachment.message_id) if attachment else None
        thread = db.get(EmailThread, message.thread_id) if message else None
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id):
            return HTMLResponse("Anexo não encontrado.", status_code=404)
        path = Path(attachment.storage_path)
        if not path.is_file():
            return HTMLResponse("Ficheiro indisponível.", status_code=404)

        guessed_type = guess_type(attachment.file_name or path.name)[0]
        stored_type = (attachment.content_type or "").split(";", 1)[0].strip().lower()
        if stored_type in {"", "application/octet-stream", "binary/octet-stream"}:
            media_type = guessed_type or "application/octet-stream"
        else:
            media_type = stored_type
        can_preview = (
            media_type == "application/pdf"
            or media_type.startswith("image/")
            or media_type.startswith("text/")
        )

        return FileResponse(
            path,
            media_type=media_type,
            filename=None if can_preview else attachment.file_name,
            headers={"Content-Disposition": "inline"} if can_preview else None,
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
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id):
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
    auth = _auth(request, "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse("/v2-clean/email?error=forbidden", status_code=303)
    with SessionLocal() as db:
        grant = db.scalar(
            select(EmailChannelUser).where(
                EmailChannelUser.channel_id == channel_id, EmailChannelUser.user_id == user_id
            )
        )
        if enabled:
            if not grant:
                grant = EmailChannelUser(channel_id=channel_id, user_id=user_id)
                db.add(grant)
            grant.can_reply = can_reply
            grant.can_approve = can_approve
        elif grant:
            db.delete(grant)
        db.commit()
    return RedirectResponse("/v2-clean/email?saved=access", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/status")
def email_status(request: Request, thread_id: int, status: str = Form(...)):
    auth = _auth(request, "email.triage", "email.manage", "admin.manage")
    if not auth or status not in STATUS_LABELS:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, _ = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if thread and _can_use_channel(db, user_id, auth[1], thread.channel_id):
            thread.status = status
            thread.resolved_at = datetime.now(UTC) if status == "resolved" else None
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


@email_router.post("/v2-clean/email/{thread_id}/reply")
def email_reply(
    request: Request,
    thread_id: int,
    body: str = Form(...),
    sender_channel_id: int | None = Form(None),
    submit: str = Form("draft"),
):
    auth = _auth(request, "email.reply", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id, "reply"):
            return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
        sender_channel = db.get(
            EmailChannel, sender_channel_id or thread.channel_id
        )
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
        state = {
            "approval": "pending_approval",
            "send": "approved",
        }.get(submit, "draft")
        message = EmailMessage(
            thread_id=thread.id,
            direction="outbound",
            state=state,
            sender=sender_channel.address,
            recipients_json=[{"Email": thread.sender_email}],
            subject=f"Re: {thread.subject}",
            text_body=body,
            created_by_id=user_id,
        )
        db.add(message)
        thread.status = "waiting_approval" if state == "pending_approval" else "in_progress"
        db.flush()
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
                    sender_channel.address,
                    reply_to=sender_channel.address,
                    parent_message_id=parent_message_id,
                    references=references,
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
            message.external_message_id = result.get("MessageID") or message.external_message_id
            thread.status = "waiting_reply"
            state = "sent"
        db.add(
            EmailAuditEvent(
                thread_id=thread.id,
                message_id=message.id,
                user_id=user_id,
                action=state,
                details_json={
                    "sender_channel_id": sender_channel.id,
                    "sender": sender_channel.address,
                },
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved={state}", status_code=303)


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
            or not _can_use_channel(db, user_id, auth[1], thread.channel_id)
            or not sender_channel
            or not _can_use_channel(
                db, user_id, auth[1], sender_channel.id, "approve"
            )
        ):
            return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
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
        try:
            result = send_message(
                message,
                sender_channel.address,
                reply_to=sender_channel.address,
                parent_message_id=parent_message_id,
                references=references,
            )
            message.state, message.sent_at, message.approved_by_id, message.approved_at = (
                "sent",
                datetime.now(UTC),
                user_id,
                datetime.now(UTC),
            )
            message.external_message_id = result.get("MessageID") or message.external_message_id
            thread.status = "waiting_reply"
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
                    "sender": sender_channel.address,
                },
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=sent", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/task")
def email_create_task(request: Request, thread_id: int):
    auth = _auth(request, "tasks.write", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread or not _can_use_channel(db, user_id, permissions, thread.channel_id):
            return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
        if not thread.task_id:
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
                assigned_to_id=thread.assigned_to_id,
                due_on=thread.due_at.date() if thread.due_at else None,
                created_by_id=user_id,
            )
            db.add(task)
            db.flush()
            first = db.scalar(
                select(EmailMessage)
                .where(EmailMessage.thread_id == thread.id, EmailMessage.direction == "inbound")
                .order_by(EmailMessage.id)
            )
            db.add(
                TaskEmailOrigin(
                    task_id=task.id,
                    message_id=first.external_message_id,
                    sender=first.sender,
                    recipients_json=first.recipients_json,
                    subject=first.subject,
                    received_at=first.received_at,
                    mailbox=db.get(EmailChannel, thread.channel_id).address,
                    source_url=f"/v2-clean/email/{thread.id}",
                )
            )
            thread.task_id, thread.status = task.id, "task_created"
            db.add(
                EmailAuditEvent(
                    thread_id=thread.id,
                    message_id=first.id,
                    user_id=user_id,
                    action="task_created",
                    details_json={"task_id": task.id},
                )
            )
            db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=task", status_code=303)
