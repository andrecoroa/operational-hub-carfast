from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.admin import User
from app.models.email import EmailChannel, EmailChannelTransport
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.services.microsoft365_oauth import (
    authorization_url,
    begin_authorization,
    consume_authorization,
    exchange_authorization_code,
)

microsoft365_router = APIRouter()
CALLBACK_PATH = "/v2-clean/integrations/microsoft/callback"


def _integration_manager(request: Request) -> int | None:
    raw_user_id = request.session.get("user_id")
    if not raw_user_id:
        return None
    with SessionLocal() as db:
        user = db.get(User, int(raw_user_id))
        if not user or not user.active:
            return None
        permissions = get_user_permission_codes(db, user)
    if not permissions.intersection({"admin.integrations.manage", "admin.manage"}):
        return None
    return int(raw_user_id)


@microsoft365_router.get("/v2-clean/integrations/microsoft/connect/{transport_id}")
def microsoft365_connect(request: Request, transport_id: int):
    user_id = _integration_manager(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not settings.microsoft365_oauth_setup_enabled:
        return JSONResponse({"error": "microsoft365_oauth_setup_disabled"}, status_code=503)
    with SessionLocal() as db:
        transport = db.get(EmailChannelTransport, transport_id)
        if not transport or transport.provider != "microsoft365":
            return JSONResponse({"error": "transport_not_found"}, status_code=404)
        if not all(
            (
                transport.tenant_id,
                transport.client_id,
                transport.client_credential_reference,
                transport.token_reference,
                transport.mailbox_address,
            )
        ):
            return JSONResponse({"error": "transport_incomplete"}, status_code=409)
        state, challenge = begin_authorization(user_id=user_id, transport_id=transport.id)
        location = authorization_url(
            tenant_id=str(transport.tenant_id),
            client_id=str(transport.client_id),
            redirect_uri=settings.microsoft365_redirect_uri,
            state=state,
            challenge=challenge,
        )
    return RedirectResponse(location, status_code=303)


@microsoft365_router.get(CALLBACK_PATH)
def microsoft365_callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    if not settings.microsoft365_oauth_setup_enabled:
        return JSONResponse({"error": "microsoft365_oauth_setup_disabled"}, status_code=503)
    if error:
        return JSONResponse({"error": "microsoft_authorization_rejected"}, status_code=400)
    raw_user_id = request.session.get("user_id")
    if not raw_user_id:
        return JSONResponse({"error": "oauth_session_mismatch"}, status_code=403)
    attempt = consume_authorization(state, user_id=int(raw_user_id)) if state else None
    if not attempt or not code:
        return JSONResponse({"error": "invalid_or_expired_oauth_state"}, status_code=400)
    with SessionLocal() as db:
        transport = db.get(EmailChannelTransport, attempt.transport_id)
        if not transport or transport.provider != "microsoft365":
            return JSONResponse({"error": "transport_not_found"}, status_code=404)
        try:
            exchange_authorization_code(
                tenant_id=str(transport.tenant_id),
                client_id=str(transport.client_id),
                client_credential_reference=str(transport.client_credential_reference),
                token_reference=str(transport.token_reference),
                redirect_uri=settings.microsoft365_redirect_uri,
                code=code,
                verifier=attempt.verifier,
            )
        except RuntimeError:
            transport.last_error = "oauth_exchange_failed"
            db.commit()
            return JSONResponse({"error": "oauth_exchange_failed"}, status_code=502)
        transport.connected_at = datetime.now(UTC)
        transport.revoked_at = None
        transport.last_error = None
        db.commit()
    return RedirectResponse(
        "/v2-clean/admin?section=integrations&microsoft=connected", status_code=303
    )


@microsoft365_router.post("/v2-clean/integrations/microsoft/configure-disabled")
def configure_disabled_microsoft365_transport(
    request: Request,
    mailbox_address: str = Form(...),
    tenant_id: str = Form(...),
    client_id: str = Form(...),
    delegated_user_principal_name: str = Form(...),
):
    user_id = _integration_manager(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    mailbox = mailbox_address.strip().lower()
    if mailbox != "email@carfast.pt":
        return JSONResponse({"error": "mailbox_not_allowed"}, status_code=400)
    with SessionLocal() as db:
        channel = db.scalar(select(EmailChannel).where(EmailChannel.address == mailbox))
        if channel is None:
            channel = EmailChannel(
                code="microsoft365_email",
                name="Email CarFast",
                address=mailbox,
                default_reply_address=mailbox,
                from_address=mailbox,
                from_name="CarFast",
                reply_to_address=mailbox,
                active=False,
                approval_required=True,
                assignment_mode="manual",
            )
            db.add(channel)
            db.flush()
        transport = db.scalar(
            select(EmailChannelTransport).where(EmailChannelTransport.channel_id == channel.id)
        )
        if transport is None:
            transport = EmailChannelTransport(channel_id=channel.id)
            db.add(transport)
            db.flush()
        transport.provider = "microsoft365"
        transport.enabled = False
        transport.mailbox_address = mailbox
        transport.tenant_id = tenant_id.strip()
        transport.client_id = client_id.strip()
        transport.client_credential_reference = "env://MICROSOFT365_CLIENT_SECRET"
        transport.token_reference = f"db://microsoft365/transport/{transport.id}/tokens"
        transport.delegated_user_principal_name = delegated_user_principal_name.strip().lower()
        transport.initial_sync_days = 5
        record_audit(
            db,
            "microsoft365.transport.configured_disabled",
            "email_channel_transport",
            transport.id,
            user_id=user_id,
            after_json={
                "mailbox": mailbox,
                "provider": "microsoft365",
                "enabled": False,
                "initial_sync_days": 5,
                "credential_reference": transport.client_credential_reference,
                "token_reference": transport.token_reference,
            },
        )
        db.commit()
        transport_id = transport.id
    return JSONResponse(
        {
            "status": "configured_disabled",
            "transport_id": transport_id,
            "connect_path": f"/v2-clean/integrations/microsoft/connect/{transport_id}",
        }
    )


@microsoft365_router.post("/v2-clean/integrations/microsoft/activate-frota")
def activate_frota_microsoft365_transport(request: Request):
    """Activate only Frota from an already connected protected OAuth transport."""
    user_id = _integration_manager(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        source = db.scalar(
            select(EmailChannelTransport)
            .join(EmailChannel, EmailChannel.id == EmailChannelTransport.channel_id)
            .where(
                EmailChannelTransport.provider == "microsoft365",
                EmailChannelTransport.connected_at.is_not(None),
                EmailChannelTransport.revoked_at.is_(None),
                EmailChannel.address == "email@carfast.pt",
            )
        )
        if source is None or not all(
            (
                source.tenant_id,
                source.client_id,
                source.client_credential_reference,
                source.token_reference,
                source.delegated_user_principal_name,
            )
        ):
            return JSONResponse({"error": "connected_source_not_found"}, status_code=409)
        channel = db.scalar(
            select(EmailChannel).where(EmailChannel.address == "frota@carfast.pt")
        )
        if channel is None:
            return JSONResponse({"error": "frota_channel_not_found"}, status_code=404)
        transport = db.scalar(
            select(EmailChannelTransport).where(EmailChannelTransport.channel_id == channel.id)
        )
        if transport is None:
            transport = EmailChannelTransport(channel_id=channel.id)
            db.add(transport)
            db.flush()
        transport.provider = "microsoft365"
        transport.enabled = True
        transport.mailbox_address = "frota@carfast.pt"
        transport.tenant_id = source.tenant_id
        transport.client_id = source.client_id
        transport.client_credential_reference = source.client_credential_reference
        transport.token_reference = source.token_reference
        transport.delegated_user_principal_name = source.delegated_user_principal_name
        transport.connected_at = source.connected_at
        transport.revoked_at = None
        transport.last_error = None
        channel.active = True
        channel.from_address = "frota@carfast.pt"
        channel.reply_to_address = "frota@carfast.pt"
        record_audit(
            db,
            "microsoft365.transport.frota_activated",
            "email_channel_transport",
            transport.id,
            user_id=user_id,
            after_json={
                "mailbox": "frota@carfast.pt",
                "provider": "microsoft365",
                "enabled": True,
                "credential_reference": transport.client_credential_reference,
                "token_reference": transport.token_reference,
            },
        )
        db.commit()
    return RedirectResponse(
        "/v2-clean/admin/integrations?microsoft=frota_activated", status_code=303
    )
