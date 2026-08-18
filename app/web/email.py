from __future__ import annotations

from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

from fastapi import APIRouter, Form, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.admin import User
from app.models.email import EmailAuditEvent, EmailChannel, EmailMessage, EmailThread
from app.models.tasks import Task, TaskEmailOrigin
from app.services.authorization import get_user_permission_codes
from app.services.email_postmark import (
    ensure_email_channels,
    ingest_inbound,
    send_message,
    webhook_authorized,
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
        "a", "b", "blockquote", "br", "div", "em", "h1", "h2", "h3", "h4",
        "hr", "i", "img", "li", "ol", "p", "pre", "span", "strong", "table",
        "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul",
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
                    safe_attrs.extend([f'href="{escape(safe, quote=True)}"', 'target="_blank"', 'rel="noopener noreferrer"'])
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
        "td,th{padding:4px 6px}blockquote{margin-left:0;padding-left:14px;border-left:3px solid #d8e0ea}"
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
def email_inbox(request: Request, status: str = "", channel: str = "", q: str = ""):
    auth = _auth(request, "email.read", "email.triage", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse("/login?next=/v2-clean/email", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        ensure_email_channels(db)
        db.commit()
        query = select(EmailThread, EmailChannel).join(
            EmailChannel, EmailChannel.id == EmailThread.channel_id
        )
        if status:
            query = query.where(EmailThread.status == status)
        if channel:
            query = query.where(EmailChannel.code == channel)
        if q:
            query = query.where(EmailThread.subject.ilike(f"%{q}%"))
        rows = db.execute(query.order_by(EmailThread.last_message_at.desc()).limit(100)).all()
        counts = dict(
            db.execute(select(EmailThread.status, func.count()).group_by(EmailThread.status)).all()
        )
        channels = list(
            db.scalars(
                select(EmailChannel)
                .where(EmailChannel.active.is_(True))
                .order_by(EmailChannel.name)
            )
        )
        return templates.TemplateResponse(
            request,
            "clean_email_inbox.html",
            {
                "active_menu": "email",
                "current_user": db.get(User, user_id),
                "permission_codes": permissions,
                "rows": rows,
                "channels": channels,
                "counts": counts,
                "status_labels": STATUS_LABELS,
                "filters": {"status": status, "channel": channel, "q": q},
            },
        )


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
        if not thread:
            return RedirectResponse("/v2-clean/email?error=not_found", status_code=303)
        channel = db.get(EmailChannel, thread.channel_id)
        messages = list(
            db.scalars(
                select(EmailMessage)
                .where(EmailMessage.thread_id == thread.id)
                .order_by(EmailMessage.created_at)
            )
        )
        return templates.TemplateResponse(
            request,
            "clean_email_thread.html",
            {
                "active_menu": "email",
                "current_user": db.get(User, user_id),
                "permission_codes": permissions,
                "thread": thread,
                "channel": channel,
                "messages": messages,
                "status_labels": STATUS_LABELS,
                "can_reply": bool(
                    permissions.intersection({"email.reply", "email.manage", "admin.manage"})
                ),
                "can_approve": bool(
                    permissions.intersection({"email.approve", "email.manage", "admin.manage"})
                ),
                "outbound_enabled": settings.email_outbound_enabled,
                "embedded": False,
            },
        )


@email_router.get("/v2-clean/email/{thread_id}/preview", response_class=HTMLResponse)
def email_thread_preview(request: Request, thread_id: int):
    auth = _auth(request, "email.read", "email.triage", "email.reply", "email.approve", "email.manage", "admin.manage")
    if not auth:
        return HTMLResponse("Sessão sem acesso a esta conversa.", status_code=403)
    _, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread:
            return HTMLResponse("Conversa não encontrada.", status_code=404)
        messages = list(db.scalars(select(EmailMessage).where(EmailMessage.thread_id == thread.id).order_by(EmailMessage.created_at)))
        return templates.TemplateResponse(request, "_email_thread_content.html", {
            "thread": thread,
            "channel": db.get(EmailChannel, thread.channel_id),
            "messages": messages,
            "status_labels": STATUS_LABELS,
            "can_reply": bool(permissions.intersection({"email.reply", "email.manage", "admin.manage"})),
            "can_approve": bool(permissions.intersection({"email.approve", "email.manage", "admin.manage"})),
            "outbound_enabled": settings.email_outbound_enabled,
            "embedded": True,
        })


@email_router.get("/v2-clean/email/messages/{message_id}/body", response_class=HTMLResponse)
def email_message_body(request: Request, message_id: int):
    if not _auth(request, "email.read", "email.triage", "email.reply", "email.approve", "email.manage", "admin.manage"):
        return HTMLResponse("Sem acesso.", status_code=403)
    with SessionLocal() as db:
        message = db.get(EmailMessage, message_id)
        if not message:
            return HTMLResponse("Mensagem não encontrada.", status_code=404)
        return HTMLResponse(
            _safe_email_document(message),
            headers={"Content-Security-Policy": "default-src 'none'; img-src https: http:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"},
        )


@email_router.post("/v2-clean/email/{thread_id}/status")
def email_status(request: Request, thread_id: int, status: str = Form(...)):
    auth = _auth(request, "email.triage", "email.manage", "admin.manage")
    if not auth or status not in STATUS_LABELS:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, _ = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if thread:
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
    request: Request, thread_id: int, body: str = Form(...), submit: str = Form("draft")
):
    auth = _auth(request, "email.reply", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, permissions = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        channel = db.get(EmailChannel, thread.channel_id)
        state = "pending_approval" if submit == "approval" else "draft"
        message = EmailMessage(
            thread_id=thread.id,
            direction="outbound",
            state=state,
            sender=channel.address,
            recipients_json=[{"Email": thread.sender_email}],
            subject=f"Re: {thread.subject}",
            text_body=body,
            created_by_id=user_id,
        )
        db.add(message)
        thread.status = "waiting_approval" if state == "pending_approval" else "in_progress"
        db.flush()
        db.add(
            EmailAuditEvent(
                thread_id=thread.id, message_id=message.id, user_id=user_id, action=state
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
        channel = db.get(EmailChannel, thread.channel_id)
        try:
            result = send_message(message, channel.address)
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
            )
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/email/{thread_id}?saved=sent", status_code=303)


@email_router.post("/v2-clean/email/{thread_id}/task")
def email_create_task(request: Request, thread_id: int):
    auth = _auth(request, "tasks.write", "email.manage", "admin.manage")
    if not auth:
        return RedirectResponse(f"/v2-clean/email/{thread_id}?error=forbidden", status_code=303)
    user_id, _ = auth
    with SessionLocal() as db:
        thread = db.get(EmailThread, thread_id)
        if not thread.task_id:
            task = Task(
                title=thread.subject[:200],
                description="Criada a partir da conversa de email.",
                task_type="operational_task",
                category="operations",
                source="email",
                status="new",
                priority="normal",
                customer_email=thread.sender_email,
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
