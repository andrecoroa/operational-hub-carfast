from urllib.parse import quote

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request

from app.api.router import api_router
from app.core.change_notice import CHANGE_NOTICE_SESSION_KEY, CHANGE_NOTICE_VERSION
from app.core.config import settings
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


def must_confirm_change_notice(request: Request) -> bool:
    path = request.url.path
    if request.method == "HEAD":
        return False
    if any(path == prefix or path.startswith(f"{prefix}/") for prefix in CHANGE_NOTICE_ALLOWED_PREFIXES):
        return False
    if not request.session.get("user_id"):
        return False
    return request.session.get(CHANGE_NOTICE_SESSION_KEY) != CHANGE_NOTICE_VERSION


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
