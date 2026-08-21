from urllib.parse import quote, urlsplit

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.api.router import api_router
from app.core.change_notice import CHANGE_NOTICE_SESSION_KEY, CHANGE_NOTICE_VERSION
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.admin import User
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.web.email import email_router
from app.web.portal import portal_router
from app.web.router import web_router
from app.web.stock import stock_router
from app.web.suppliers import supplier_router
from app.web.vehicle_sales import vehicle_sales_router

CHANGE_NOTICE_ALLOWED_PREFIXES = (
    "/api",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/portal",
    "/health",
    "/login",
    "/logout",
    "/change-notice",
)

CHANGE_NOTICE_ALLOWED_PATHS = {
    "/admin/roles",
    "/admin/permissions",
}

PERMISSION_ALLOWED_PREFIXES = (
    "/api",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/static",
    "/portal",
    "/health",
    "/login",
    "/logout",
    "/change-notice",
)

PERMISSION_ALLOWED_PATHS = {
    "/admin/roles",
    "/admin/permissions",
}

LEGACY_EXPERIENCE_PERMISSION = "experience.legacy.access"
EXPERIENCE_NEUTRAL_PREFIXES = (
    *PERMISSION_ALLOWED_PREFIXES,
    "/choose-experience",
    "/switch-experience",
    "/evolution/quick",
)

WEB_PERMISSION_RULES = (
    (("/",), {"GET": {"dashboard.read"}}),
    (("/alerts",), {"GET": {"dashboard.read"}}),
    (
        ("/evolution/quick",),
        {
            "POST": {
                "admin.evolution.create",
                "admin.evolution.manage",
                "admin.manage",
            }
        },
    ),
    (
        ("/v2-clean/email",),
        {
            "GET": {"email.read", "email.triage", "email.reply", "email.approve", "email.manage", "email.assume", "email.assign", "email.sla.manage", "admin.manage"},
            "POST": {"email.triage", "email.reply", "email.approve", "email.manage", "email.assume", "email.assign", "email.sla.manage", "tasks.write", "admin.manage"},
        },
    ),
    (
        ("/v2-clean/admin",),
        {
            "GET": {
                "admin.dashboard.read",
                "admin.users.read",
                "admin.users.manage",
                "admin.roles.read",
                "admin.roles.manage",
                "admin.organization.read",
                "admin.organization.manage",
                "admin.settings.read",
                "admin.settings.manage",
                "admin.workshop_models.read",
                "admin.workshop_models.manage",
                "admin.workshop_models.publish",
                "admin.audit.read",
                "admin.audit.export",
                "admin.integrations.read",
                "admin.integrations.manage",
                "admin.security.read",
                "admin.security.manage",
                "admin.evolution.read",
                "admin.evolution.create",
                "admin.evolution.manage",
                "admin.manage",
                "users.manage",
                "settings.manage",
                "service_desk.classifications.manage",
                "suppliers.configuration.manage",
            },
            "POST": {
                "admin.users.manage",
                "admin.users.credentials",
                "admin.roles.manage",
                "admin.organization.manage",
                "admin.settings.manage",
                "admin.workshop_models.manage",
                "admin.workshop_models.publish",
                "admin.integrations.manage",
                "admin.security.manage",
                "admin.evolution.manage",
                "admin.evolution.create",
                "admin.manage",
                "users.manage",
                "settings.manage",
                "service_desk.classifications.manage",
                "suppliers.configuration.manage",
            },
        },
    ),
    (
        ("/v2-clean/suppliers",),
        {
            "GET": {"suppliers.read", "suppliers.write", "stock.read", "stock.manage", "admin.manage"},
            "POST": {"suppliers.write", "admin.manage"},
        },
    ),
    (
        ("/v2-clean/stock",),
        {
            "GET": {"stock.read", "stock.operate", "stock.manage", "admin.manage"},
            "POST": {"stock.operate", "stock.manage", "admin.manage"},
        },
    ),
    (
        ("/v2-clean/tasks",),
        {
            "GET": {
                "tasks.read",
                "tasks.management.read",
                "tasks.management.create",
                "tasks.management.update",
                "tasks.management.close",
                "tasks.recurring.manage",
                "tasks.operational.read",
                "tasks.operational.write",
                "tasks.workshop.read",
                "tasks.workshop.write",
                "tasks.administration.read",
                "tasks.administration.write",
                "service_desk.read",
                "service_desk.create",
                "service_desk.assume",
                "service_desk.assign",
                "service_desk.update",
                "service_desk.respond",
                "service_desk.complete",
                "service_desk.sla.manage",
                "admin.manage",
            },
            "POST": {
                "tasks.write",
                "tasks.management.create",
                "tasks.management.update",
                "tasks.management.close",
                "tasks.recurring.manage",
                "tasks.operational.write",
                "tasks.workshop.write",
                "tasks.administration.write",
                "service_desk.create",
                "service_desk.assume",
                "service_desk.assign",
                "service_desk.update",
                "service_desk.respond",
                "service_desk.complete",
                "service_desk.sla.manage",
                "admin.manage",
            },
        },
    ),
    (
        ("/v2-clean/workshop", "/v2-clean/workshop-entry"),
        {
            "GET": {"workshop.read", "workshop.write", "admin.manage"},
            "POST": {"workshop.write", "admin.manage"},
        },
    ),
    (
        ("/v2-clean/fleet",),
        {
            "GET": {"vehicles.read", "vehicles.write", "fleet.commerce.manage", "admin.manage"},
            "POST": {"vehicles.write", "fleet.commerce.manage", "admin.manage"},
        },
    ),
    (
        (
            "/v2-clean/documentation",
            "/v2-clean/documents",
            "/v2-clean/diagnostics",
        ),
        {
            "GET": {"documents.read", "documents.write", "admin.manage"},
            "POST": {"documents.write", "admin.manage"},
        },
    ),
    (
        ("/v2-clean/processes",),
        {
            "GET": {
                "management_center.read",
                "management_center.write",
                "admin.manage",
            },
            "POST": {"management_center.write", "admin.manage"},
        },
    ),
    (
        ("/v2-clean",),
        {
            "GET": {
                "dashboard.read",
                "vehicles.read",
                "workshop.read",
                "tasks.read",
                "tasks.management.read",
                "tasks.management.create",
                "tasks.management.update",
                "tasks.management.close",
                "tasks.recurring.manage",
                "management_center.read",
                "documents.read",
                "admin.dashboard.read",
                "admin.manage",
            },
            "POST": {
                "vehicles.write",
                "workshop.write",
                "tasks.write",
                "tasks.management.create",
                "tasks.management.update",
                "tasks.management.close",
                "tasks.recurring.manage",
                "management_center.write",
                "documents.write",
                "admin.manage",
            },
        },
    ),
    (("/admin",), {"GET": {"admin.manage", "users.manage", "settings.manage"}, "POST": {"admin.manage", "users.manage"}}),
    (
        ("/task-board",),
        {
            "GET": {
                "tasks.read",
                "tasks.operational.read",
                "tasks.operational.write",
                "tasks.workshop.read",
                "tasks.workshop.write",
                "tasks.management.read",
                "tasks.management.create",
                "tasks.management.update",
                "tasks.management.close",
                "tasks.administration.read",
                "tasks.administration.write",
            },
            "POST": {
                "tasks.write",
                "tasks.operational.write",
                "tasks.workshop.write",
                "tasks.management.create",
                "tasks.management.update",
                "tasks.management.close",
                "tasks.administration.write",
            },
        },
    ),
    (("/workshop",), {"GET": {"workshop.read"}, "POST": {"workshop.write"}}),
    (("/fleet",), {"GET": {"vehicles.read"}, "POST": {"vehicles.write", "fleet.commerce.manage"}}),
    (("/management-center",), {"GET": {"management_center.read", "management_center.write"}, "POST": {"management_center.write"}}),
    (("/imports",), {"GET": {"imports.run", "imports.approve"}, "POST": {"imports.run"}}),
    (("/documents",), {"GET": {"documents.read", "documents.write"}, "POST": {"documents.write"}}),
)


def must_confirm_change_notice(request: Request) -> bool:
    path = request.url.path
    if request.method == "HEAD":
        return False
    if path in CHANGE_NOTICE_ALLOWED_PATHS:
        return False
    if any(path == prefix or path.startswith(f"{prefix}/") for prefix in CHANGE_NOTICE_ALLOWED_PREFIXES):
        return False
    if not request.session.get("user_id"):
        return False
    return request.session.get(CHANGE_NOTICE_SESSION_KEY) != CHANGE_NOTICE_VERSION


def route_required_permissions(path: str, method: str) -> set[str]:
    if path == "/":
        return {"dashboard.read"} if method == "GET" else set()
    for prefixes, method_rules in WEB_PERMISSION_RULES:
        for prefix in prefixes:
            if prefix == "/":
                continue
            if path == prefix or path.startswith(f"{prefix}/"):
                return method_rules.get(method, set())
    return set()


def has_required_permission(request: Request, required_permissions: set[str]) -> bool:
    if not required_permissions:
        return True
    user_id = request.session.get("user_id")
    if not user_id:
        return False
    with SessionLocal() as db:
        user = db.get(User, int(user_id))
        if not user or not user.active:
            request.session.clear()
            return False
        permissions = get_user_permission_codes(db, user)
    return bool(permissions.intersection(required_permissions))


def is_legacy_experience_path(path: str) -> bool:
    if path == "/v2-clean" or path.startswith("/v2-clean/"):
        return False
    return not any(
        path == prefix or path.startswith(f"{prefix}/")
        for prefix in EXPERIENCE_NEUTRAL_PREFIXES
    )


def has_explicit_legacy_context(request: Request) -> bool:
    if request.query_params.get("legacy_entry") == "1":
        return bool(request.session.pop("legacy_entry_pending", False))
    referer = request.headers.get("referer", "")
    if not referer:
        return False
    referer_path = urlsplit(referer).path
    return (
        request.session.get("carfast_experience") == "current"
        and is_legacy_experience_path(referer_path)
    )


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        docs_url="/docs" if settings.enable_docs else None,
        redoc_url="/redoc" if settings.enable_docs else None,
    )

    @app.middleware("http")
    async def change_notice_gate(request: Request, call_next):
        if must_confirm_change_notice(request):
            next_url = request.url.path
            if request.url.query:
                next_url = f"{next_url}?{request.url.query}"
            return RedirectResponse(f"/change-notice?next={quote(next_url, safe='')}", status_code=303)
        return await call_next(request)

    @app.middleware("http")
    async def permission_gate(request: Request, call_next):
        path = request.url.path
        if path == "/v2-clean" or path.startswith("/v2-clean/"):
            request.session["carfast_experience"] = "clean"
        if (
            request.method == "HEAD"
            or path in PERMISSION_ALLOWED_PATHS
            or any(path == prefix or path.startswith(f"{prefix}/") for prefix in PERMISSION_ALLOWED_PREFIXES)
        ):
            return await call_next(request)
        legacy_context = (
            has_explicit_legacy_context(request)
            if is_legacy_experience_path(path) and request.session.get("user_id")
            else False
        )
        if is_legacy_experience_path(path) and request.session.get("user_id") and not legacy_context:
            request.session["carfast_experience"] = "clean"
            return RedirectResponse("/v2-clean", status_code=303)
        if is_legacy_experience_path(path) and request.session.get("user_id"):
            if not has_required_permission(request, {LEGACY_EXPERIENCE_PERMISSION}):
                request.session["carfast_experience"] = "clean"
                return RedirectResponse(
                    "/v2-clean?error=legacy_access_denied",
                    status_code=303,
                )
            if request.session.get("carfast_experience") != "current":
                destination = path
                if request.url.query:
                    destination = f"{destination}?{request.url.query}"
                origin = "/direct"
                referer = request.headers.get("referer", "")
                if referer:
                    parsed_referer = urlsplit(referer)
                    referer_route = parsed_referer.path or "/direct"
                    if parsed_referer.query:
                        referer_route = f"{referer_route}?{parsed_referer.query}"
                    if referer_route == "/v2-clean" or referer_route.startswith("/v2-clean/"):
                        origin = referer_route
                with SessionLocal() as db:
                    record_audit(
                        db,
                        action="web.legacy_experience.open",
                        entity_type="experience",
                        entity_id="current",
                        detail=(
                            f"Entrada direta na versão anterior a partir de {origin}; "
                            f"destino {destination}"
                        ),
                        user_id=int(request.session["user_id"]),
                        after_json={
                            "origin": origin,
                            "destination_route": destination,
                        },
                    )
                    db.commit()
                request.session["carfast_experience"] = "current"
        navigation_permission = navigation_permission_for_path(path)
        if navigation_permission and not has_required_permission(
            request, {navigation_permission}
        ):
            if not request.session.get("user_id"):
                next_url = request.url.path
                if request.url.query:
                    next_url = f"{next_url}?{request.url.query}"
                return RedirectResponse(
                    f"/login?next={quote(next_url, safe='')}", status_code=303
                )
            return PlainTextResponse("Acesso ao módulo não autorizado.", status_code=403)
        required_permissions = route_required_permissions(path, request.method)
        if required_permissions and not has_required_permission(request, required_permissions):
            if not request.session.get("user_id"):
                next_url = request.url.path
                if request.url.query:
                    next_url = f"{next_url}?{request.url.query}"
                return RedirectResponse(f"/login?next={quote(next_url, safe='')}", status_code=303)
            if path == "/":
                return RedirectResponse("/manual", status_code=303)
            if path == "/v2-clean" or path.startswith("/v2-clean/"):
                return RedirectResponse("/v2-clean?error=forbidden", status_code=303)
            return RedirectResponse("/", status_code=303)
        return await call_next(request)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.app_secret_key,
        same_site="lax",
        https_only=settings.app_env.lower() == "production",
    )

    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(api_router)
    app.include_router(portal_router)
    app.include_router(vehicle_sales_router)
    app.include_router(stock_router)
    app.include_router(supplier_router)
    app.include_router(email_router)
    app.include_router(web_router)
    return app


app = create_app()
