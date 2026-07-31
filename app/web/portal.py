from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

import app.web.router as base_router
from app.core.config import settings
from app.core.security import hash_password, verify_password
from app.models import (
    PortalInvitation,
    PortalOrganization,
    PortalUser,
    VehicleSaleLead,
    VehicleSalePublication,
)
from app.services.audit import record_audit
from app.services.portal_access import (
    DEFAULT_TRADE_PERMISSIONS,
    PORTAL_PERMISSION_CATALOG,
    clear_portal_session,
    invitation_token_hash,
    new_invitation_token,
    normalize_portal_permissions,
    portal_context,
    portal_csrf_token,
    publication_allowed_for_portal,
    utc_datetime,
    valid_portal_csrf,
)
from app.services.vehicle_sales import LEAD_KIND_LABELS, LEAD_STATUS_LABELS, money

portal_router = APIRouter(include_in_schema=False)


def _available(publication: VehicleSalePublication | None) -> bool:
    return bool(
        publication
        and publication.status == "published"
        and (not publication.expires_on or publication.expires_on >= date.today())
    )


def _portal_login_redirect(request: Request) -> RedirectResponse:
    target = request.url.path
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(f"/portal/entrar?next={quote(target, safe='')}", status_code=303)


def _safe_portal_next(value: str | None) -> str:
    clean = (value or "/portal").strip()
    allowed = (
        clean == "/portal"
        or clean.startswith("/portal/viaturas")
        or clean.startswith("/portal/interacoes")
        or clean.startswith("/portal/pedido")
    )
    return clean if allowed and not clean.startswith("//") else "/portal"


def _portal_base_url(request: Request) -> str:
    configured = (settings.vehicle_sales_public_base_url or "").strip().rstrip("/")
    return configured or str(request.base_url).rstrip("/")


def _internal_access_denied(request: Request):
    denied = base_router.clean_experience_denied(request)
    if denied:
        return denied
    if not base_router.get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not base_router.can_manage_carfast_fleet(request):
        return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
    return None


def _portal_admin_data(db) -> dict:
    organizations = db.scalars(
        select(PortalOrganization).order_by(
            PortalOrganization.status.asc(),
            PortalOrganization.name.asc(),
        )
    ).all()
    users = db.scalars(select(PortalUser).order_by(PortalUser.name.asc())).all()
    invitations = db.scalars(
        select(PortalInvitation)
        .order_by(PortalInvitation.id.desc())
        .limit(100)
    ).all()
    return {
        "organizations": organizations,
        "users": users,
        "invitations": invitations,
        "organization_by_id": {item.id: item for item in organizations},
        "users_by_organization": {
            organization.id: [
                user for user in users if user.organization_id == organization.id
            ]
            for organization in organizations
        },
        "permission_catalog": PORTAL_PERMISSION_CATALOG,
        "default_permissions": DEFAULT_TRADE_PERMISSIONS,
        "now": datetime.now(UTC),
    }


def _render_portal_admin(
    request: Request,
    *,
    created_invitation_url: str = "",
    error: str = "",
    status_code: int = 200,
):
    with base_router.SessionLocal() as db:
        context = _portal_admin_data(db)
    context.update(
        {
            "csrf_token": portal_csrf_token(request),
            "created_invitation_url": created_invitation_url,
            "error": error,
        }
    )
    return base_router.templates.TemplateResponse(
        request,
        "clean_portal_access.html",
        context,
        status_code=status_code,
    )


@portal_router.get("/portal", response_class=HTMLResponse)
def portal_home(request: Request):
    with base_router.SessionLocal() as db:
        context = portal_context(request, db)
    return base_router.templates.TemplateResponse(
        request,
        "portal_home.html",
        {
            "portal_context": context,
            "csrf_token": portal_csrf_token(request),
        },
    )


@portal_router.get("/portal/entrar", response_class=HTMLResponse)
def portal_login_form(request: Request, next: str = "", error: str = ""):
    with base_router.SessionLocal() as db:
        context = portal_context(request, db)
    if context:
        return RedirectResponse(_safe_portal_next(next), status_code=303)
    errors = {
        "invalid": "E-mail ou palavra-passe inválidos.",
        "csrf": "A sessão expirou. Tenta novamente.",
        "rate_limit": "Foram feitas várias tentativas. Tenta novamente dentro de alguns minutos.",
    }
    return base_router.templates.TemplateResponse(
        request,
        "portal_login.html",
        {
            "csrf_token": portal_csrf_token(request),
            "next_url": _safe_portal_next(next),
            "error": errors.get(error),
        },
    )


@portal_router.post("/portal/entrar")
def portal_login_submit(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    next_url: str = Form("/portal"),
    csrf_token: str = Form(""),
):
    destination = _safe_portal_next(next_url)
    if not valid_portal_csrf(request, csrf_token):
        return RedirectResponse(
            f"/portal/entrar?error=csrf&next={quote(destination, safe='')}",
            status_code=303,
        )
    client_key = f"portal-login:{base_router.external_client_key(request)}"
    if not base_router.external_portal_rate_limit_allows(client_key):
        return RedirectResponse(
            f"/portal/entrar?error=rate_limit&next={quote(destination, safe='')}",
            status_code=303,
        )
    with base_router.SessionLocal() as db:
        user = db.scalar(
            select(PortalUser).where(PortalUser.email == email.strip().lower())
        )
        organization = db.get(PortalOrganization, user.organization_id) if user else None
        valid = bool(
            user
            and user.active
            and organization
            and organization.status == "active"
            and "portal.access"
            in normalize_portal_permissions(user.permissions_json or [])
            and verify_password(password, user.password_hash)
        )
        if not valid:
            return RedirectResponse(
                f"/portal/entrar?error=invalid&next={quote(destination, safe='')}",
                status_code=303,
            )
        clear_portal_session(request)
        request.session["portal_user_id"] = user.id
        request.session["portal_organization_id"] = organization.id
        user.last_login_at = datetime.now(UTC)
        record_audit(
            db,
            action="portal.login",
            entity_type="portal_user",
            entity_id=user.id,
            detail=f"Entrada no portal externo: {user.email}",
            after_json={"organization_id": organization.id},
            user_id=None,
        )
        db.commit()
    return RedirectResponse(destination, status_code=303)


@portal_router.post("/portal/sair")
def portal_logout(request: Request, csrf_token: str = Form("")):
    if valid_portal_csrf(request, csrf_token):
        clear_portal_session(request)
        request.session.pop("portal_csrf_token", None)
    return RedirectResponse("/portal", status_code=303)


def _invitation_for_token(db, token: str) -> PortalInvitation | None:
    invitation = db.scalar(
        select(PortalInvitation).where(
            PortalInvitation.token_hash == invitation_token_hash(token)
        )
    )
    if (
        not invitation
        or invitation.status != "pending"
        or utc_datetime(invitation.expires_at) <= datetime.now(UTC)
    ):
        return None
    return invitation


@portal_router.get("/portal/convite/{token}", response_class=HTMLResponse)
def portal_invitation_form(request: Request, token: str, error: str = ""):
    with base_router.SessionLocal() as db:
        invitation = _invitation_for_token(db, token)
        organization = (
            db.get(PortalOrganization, invitation.organization_id)
            if invitation
            else None
        )
        if not invitation or not organization or organization.status != "active":
            return base_router.templates.TemplateResponse(
                request,
                "portal_invitation.html",
                {"invitation": None, "organization": None, "error": None},
                status_code=410,
            )
    errors = {
        "password": "Usa uma palavra-passe com pelo menos 12 caracteres e confirma-a.",
        "email_exists": "Já existe uma conta do portal com este e-mail.",
        "csrf": "A sessão expirou. Abre novamente o convite.",
    }
    return base_router.templates.TemplateResponse(
        request,
        "portal_invitation.html",
        {
            "invitation": invitation,
            "organization": organization,
            "token": token,
            "csrf_token": portal_csrf_token(request),
            "error": errors.get(error),
        },
    )


@portal_router.post("/portal/convite/{token}")
def portal_invitation_accept(
    request: Request,
    token: str,
    password: str = Form(""),
    password_confirmation: str = Form(""),
    csrf_token: str = Form(""),
):
    if not valid_portal_csrf(request, csrf_token):
        return RedirectResponse(f"/portal/convite/{token}?error=csrf", status_code=303)
    if len(password) < 12 or password != password_confirmation:
        return RedirectResponse(f"/portal/convite/{token}?error=password", status_code=303)
    with base_router.SessionLocal() as db:
        invitation = _invitation_for_token(db, token)
        organization = (
            db.get(PortalOrganization, invitation.organization_id)
            if invitation
            else None
        )
        if not invitation or not organization or organization.status != "active":
            return base_router.templates.TemplateResponse(
                request,
                "portal_invitation.html",
                {"invitation": None, "organization": None, "error": None},
                status_code=410,
            )
        if db.scalar(select(PortalUser.id).where(PortalUser.email == invitation.email)):
            return RedirectResponse(
                f"/portal/convite/{token}?error=email_exists", status_code=303
            )
        now = datetime.now(UTC)
        user = PortalUser(
            organization_id=organization.id,
            name=invitation.name,
            email=invitation.email,
            password_hash=hash_password(password),
            permissions_json=normalize_portal_permissions(
                invitation.permissions_json or []
            ),
            active=True,
            email_verified_at=now,
            password_changed_at=now,
            invited_by_id=invitation.created_by_id,
        )
        db.add(user)
        db.flush()
        invitation.status = "accepted"
        invitation.accepted_at = now
        invitation.accepted_by_user_id = user.id
        record_audit(
            db,
            action="portal.invitation.accepted",
            entity_type="portal_user",
            entity_id=user.id,
            detail=f"Convite aceite por {user.email}",
            after_json={"organization_id": organization.id},
            user_id=None,
        )
        db.commit()
        clear_portal_session(request)
        request.session["portal_user_id"] = user.id
        request.session["portal_organization_id"] = organization.id
    return RedirectResponse("/portal", status_code=303)


@portal_router.get("/portal/viaturas", response_class=HTMLResponse)
def portal_vehicle_catalog(request: Request, q: str = ""):
    with base_router.SessionLocal() as db:
        context = portal_context(request, db)
        if not context:
            return _portal_login_redirect(request)
        if not context.has("vehicles.catalog.view"):
            return base_router.templates.TemplateResponse(
                request,
                "portal_forbidden.html",
                {"portal_context": context},
                status_code=403,
            )
        publications = db.scalars(
            select(VehicleSalePublication)
            .where(VehicleSalePublication.status == "published")
            .order_by(
                VehicleSalePublication.published_at.desc(),
                VehicleSalePublication.id.desc(),
            )
            .limit(1000)
        ).all()
        rows = []
        seen_vehicle_ids: set[int] = set()
        query = q.strip().casefold()
        for publication in publications:
            if not _available(publication) or publication.vehicle_id in seen_vehicle_ids:
                continue
            if not publication_allowed_for_portal(db, publication, context):
                continue
            if publication.audience == "trade" and not context.has(
                "vehicles.trade_price.view"
            ):
                continue
            if publication.audience == "retail" and not context.has(
                "vehicles.retail_price.view"
            ):
                continue
            snapshot = dict(publication.snapshot_json or {})
            vehicle = dict(snapshot.get("vehicle") or {})
            sale = dict(snapshot.get("sale") or {})
            haystack = " ".join(
                str(value or "")
                for value in (
                    vehicle.get("reference"),
                    vehicle.get("brand"),
                    vehicle.get("model"),
                    vehicle.get("version"),
                    vehicle.get("year"),
                )
            ).casefold()
            if query and query not in haystack:
                continue
            rows.append(
                {
                    "publication": publication,
                    "vehicle": vehicle,
                    "sale": sale,
                    "cover_image_id": next(
                        (
                            int(value)
                            for value in (
                                publication.selected_image_ids_json or []
                            )
                            if str(value).isdigit()
                        ),
                        None,
                    ),
                }
            )
            seen_vehicle_ids.add(publication.vehicle_id)
    return base_router.templates.TemplateResponse(
        request,
        "portal_vehicle_catalog.html",
        {
            "portal_context": context,
            "rows": rows,
            "query": q.strip(),
            "csrf_token": portal_csrf_token(request),
            "money": money,
        },
    )


@portal_router.get("/portal/interacoes", response_class=HTMLResponse)
def portal_interactions(request: Request):
    with base_router.SessionLocal() as db:
        context = portal_context(request, db)
        if not context:
            return _portal_login_redirect(request)
        scope = (
            VehicleSaleLead.portal_organization_id == context.organization.id
            if context.has("offers.view_organization")
            else VehicleSaleLead.portal_user_id == context.user.id
        )
        leads = db.scalars(
            select(VehicleSaleLead)
            .where(scope)
            .order_by(VehicleSaleLead.id.desc())
            .limit(500)
        ).all()
        publication_ids = {lead.publication_id for lead in leads}
        publications = {
            publication.id: publication
            for publication in (
                db.scalars(
                    select(VehicleSalePublication).where(
                        VehicleSalePublication.id.in_(publication_ids)
                    )
                ).all()
                if publication_ids
                else []
            )
        }
    return base_router.templates.TemplateResponse(
        request,
        "portal_interactions.html",
        {
            "portal_context": context,
            "leads": leads,
            "publications": publications,
            "lead_kind_labels": LEAD_KIND_LABELS,
            "lead_status_labels": LEAD_STATUS_LABELS,
            "csrf_token": portal_csrf_token(request),
            "money": money,
        },
    )


@portal_router.get("/v2-clean/fleet/sales-access", response_class=HTMLResponse)
def portal_access_admin(request: Request, error: str = ""):
    denied = _internal_access_denied(request)
    if denied:
        return denied
    return _render_portal_admin(request, error=error)


@portal_router.post("/v2-clean/fleet/sales-access/organizations")
def portal_organization_create(
    request: Request,
    name: str = Form(""),
    tax_number: str = Form(""),
    organization_type: str = Form("trade"),
    notes: str = Form(""),
    csrf_token: str = Form(""),
):
    denied = _internal_access_denied(request)
    if denied:
        return denied
    if not valid_portal_csrf(request, csrf_token):
        return RedirectResponse(
            "/v2-clean/fleet/sales-access?error=csrf", status_code=303
        )
    clean_name = name.strip()
    clean_tax_number = "".join(char for char in tax_number if char.isalnum()).upper()
    if not clean_name:
        return RedirectResponse(
            "/v2-clean/fleet/sales-access?error=organization_required",
            status_code=303,
        )
    user_id = int(base_router.get_web_user_id(request))
    with base_router.SessionLocal() as db:
        if clean_tax_number and db.scalar(
            select(PortalOrganization.id).where(
                PortalOrganization.tax_number == clean_tax_number
            )
        ):
            return RedirectResponse(
                "/v2-clean/fleet/sales-access?error=tax_number_exists",
                status_code=303,
            )
        organization = PortalOrganization(
            name=clean_name[:200],
            tax_number=clean_tax_number[:40] or None,
            organization_type=(
                organization_type
                if organization_type in {"trade", "partner", "customer"}
                else "trade"
            ),
            status="active",
            notes=notes.strip()[:5000] or None,
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        db.add(organization)
        db.flush()
        record_audit(
            db,
            action="portal.organization.created",
            entity_type="portal_organization",
            entity_id=organization.id,
            detail=f"Entidade externa criada: {organization.name}",
            after_json={
                "tax_number": organization.tax_number,
                "organization_type": organization.organization_type,
            },
            user_id=user_id,
        )
        db.commit()
    return RedirectResponse("/v2-clean/fleet/sales-access?saved=organization", status_code=303)


@portal_router.post("/v2-clean/fleet/sales-access/invitations")
async def portal_invitation_create(request: Request):
    denied = _internal_access_denied(request)
    if denied:
        return denied
    form = await request.form()
    if not valid_portal_csrf(request, str(form.get("csrf_token") or "")):
        return RedirectResponse(
            "/v2-clean/fleet/sales-access?error=csrf", status_code=303
        )
    try:
        organization_id = int(str(form.get("organization_id") or "0"))
    except ValueError:
        organization_id = 0
    name = str(form.get("name") or "").strip()
    email = str(form.get("email") or "").strip().lower()
    permissions = normalize_portal_permissions(form.getlist("permissions"))
    if "portal.access" not in permissions:
        permissions.insert(0, "portal.access")
    try:
        expires_days = min(max(int(str(form.get("expires_days") or "7")), 1), 30)
    except ValueError:
        expires_days = 7
    if not name or "@" not in email:
        return RedirectResponse(
            "/v2-clean/fleet/sales-access?error=invitation_required",
            status_code=303,
        )
    user_id = int(base_router.get_web_user_id(request))
    raw_token = new_invitation_token()
    with base_router.SessionLocal() as db:
        organization = db.get(PortalOrganization, organization_id)
        if not organization or organization.status != "active":
            return RedirectResponse(
                "/v2-clean/fleet/sales-access?error=organization_invalid",
                status_code=303,
            )
        if db.scalar(select(PortalUser.id).where(PortalUser.email == email)):
            return RedirectResponse(
                "/v2-clean/fleet/sales-access?error=email_exists", status_code=303
            )
        pending = db.scalars(
            select(PortalInvitation).where(
                PortalInvitation.email == email,
                PortalInvitation.status == "pending",
            )
        ).all()
        for item in pending:
            item.status = "revoked"
        invitation = PortalInvitation(
            organization_id=organization.id,
            name=name[:160],
            email=email[:255],
            token_hash=invitation_token_hash(raw_token),
            permissions_json=permissions,
            status="pending",
            expires_at=datetime.now(UTC) + timedelta(days=expires_days),
            created_by_id=user_id,
        )
        db.add(invitation)
        db.flush()
        record_audit(
            db,
            action="portal.invitation.created",
            entity_type="portal_invitation",
            entity_id=invitation.id,
            detail=f"Convite externo criado para {invitation.email}",
            after_json={
                "organization_id": organization.id,
                "permissions": permissions,
                "expires_at": invitation.expires_at.isoformat(),
            },
            user_id=user_id,
        )
        db.commit()
    invitation_url = f"{_portal_base_url(request)}/portal/convite/{raw_token}"
    return _render_portal_admin(
        request,
        created_invitation_url=invitation_url,
    )


@portal_router.post("/v2-clean/fleet/sales-access/organizations/{organization_id}/status")
def portal_organization_status(
    request: Request,
    organization_id: int,
    status: str = Form("suspended"),
    csrf_token: str = Form(""),
):
    denied = _internal_access_denied(request)
    if denied:
        return denied
    if not valid_portal_csrf(request, csrf_token):
        return RedirectResponse(
            "/v2-clean/fleet/sales-access?error=csrf", status_code=303
        )
    normalized = status if status in {"active", "suspended"} else "suspended"
    user_id = int(base_router.get_web_user_id(request))
    with base_router.SessionLocal() as db:
        organization = db.get(PortalOrganization, organization_id)
        if organization:
            before = organization.status
            organization.status = normalized
            organization.updated_by_id = user_id
            record_audit(
                db,
                action="portal.organization.status_updated",
                entity_type="portal_organization",
                entity_id=organization.id,
                detail=f"Estado da entidade externa: {organization.name}",
                before_json={"status": before},
                after_json={"status": normalized},
                user_id=user_id,
            )
            db.commit()
    return RedirectResponse("/v2-clean/fleet/sales-access?saved=status", status_code=303)


@portal_router.post("/v2-clean/fleet/sales-access/users/{portal_user_id}")
async def portal_user_update(request: Request, portal_user_id: int):
    denied = _internal_access_denied(request)
    if denied:
        return denied
    form = await request.form()
    if not valid_portal_csrf(request, str(form.get("csrf_token") or "")):
        return RedirectResponse(
            "/v2-clean/fleet/sales-access?error=csrf", status_code=303
        )
    permissions = normalize_portal_permissions(form.getlist("permissions"))
    active = str(form.get("active") or "") == "1"
    if active and "portal.access" not in permissions:
        permissions.insert(0, "portal.access")
    user_id = int(base_router.get_web_user_id(request))
    with base_router.SessionLocal() as db:
        portal_user = db.get(PortalUser, portal_user_id)
        if portal_user:
            before = {
                "active": portal_user.active,
                "permissions": portal_user.permissions_json or [],
            }
            portal_user.active = active
            portal_user.permissions_json = permissions
            record_audit(
                db,
                action="portal.user.updated",
                entity_type="portal_user",
                entity_id=portal_user.id,
                detail=f"Acesso externo atualizado: {portal_user.email}",
                before_json=before,
                after_json={"active": active, "permissions": permissions},
                user_id=user_id,
            )
            db.commit()
    return RedirectResponse("/v2-clean/fleet/sales-access?saved=user", status_code=303)


@portal_router.post("/v2-clean/fleet/sales-access/invitations/{invitation_id}/revoke")
def portal_invitation_revoke(
    request: Request,
    invitation_id: int,
    csrf_token: str = Form(""),
):
    denied = _internal_access_denied(request)
    if denied:
        return denied
    if not valid_portal_csrf(request, csrf_token):
        return RedirectResponse(
            "/v2-clean/fleet/sales-access?error=csrf", status_code=303
        )
    user_id = int(base_router.get_web_user_id(request))
    with base_router.SessionLocal() as db:
        invitation = db.get(PortalInvitation, invitation_id)
        if invitation and invitation.status == "pending":
            invitation.status = "revoked"
            record_audit(
                db,
                action="portal.invitation.revoked",
                entity_type="portal_invitation",
                entity_id=invitation.id,
                detail=f"Convite externo revogado: {invitation.email}",
                user_id=user_id,
            )
            db.commit()
    return RedirectResponse("/v2-clean/fleet/sales-access?saved=invitation", status_code=303)
