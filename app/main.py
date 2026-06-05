from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.api.router import api_router
from app.core.change_notice import CHANGE_NOTICE_SESSION_KEY, CHANGE_NOTICE_VERSION
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.admin import User
from app.services.authorization import get_user_permission_codes
from app.web.router import web_router

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

WEB_PERMISSION_RULES = (
    (("/",), {"GET": {"dashboard.read"}}),
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
                "tasks.management.write",
                "tasks.administration.read",
                "tasks.administration.write",
            },
            "POST": {
                "tasks.write",
                "tasks.operational.write",
                "tasks.workshop.write",
                "tasks.management.write",
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
        if (
            request.method == "HEAD"
            or path in PERMISSION_ALLOWED_PATHS
            or any(path == prefix or path.startswith(f"{prefix}/") for prefix in PERMISSION_ALLOWED_PREFIXES)
        ):
            return await call_next(request)
        required_permissions = route_required_permissions(path, request.method)
        if required_permissions and not has_required_permission(request, required_permissions):
            if not request.session.get("user_id"):
                return RedirectResponse("/login", status_code=303)
            if path == "/":
                return RedirectResponse("/manual", status_code=303)
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
    app.include_router(web_router)
    return app


app = create_app()
