from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.admin import User
from app.models.email import EmailChannelTransport
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
    if not settings.microsoft365_email_enabled:
        return JSONResponse({"error": "microsoft365_email_disabled"}, status_code=503)
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
    if not settings.microsoft365_email_enabled:
        return JSONResponse({"error": "microsoft365_email_disabled"}, status_code=503)
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
