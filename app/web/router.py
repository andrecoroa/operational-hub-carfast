from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import verify_password
from app.models.admin import User
from app.models.imports import ImportBatch
from app.models.tasks import Task
from app.models.vehicles import Vehicle
from app.services.audit import record_audit
from app.services.authorization import get_user_authorized_unit_codes, get_user_permission_codes

templates = Jinja2Templates(directory="app/templates")
web_router = APIRouter(include_in_schema=False)


@web_router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)
        metrics = {
            "vehicles": db.scalar(select(Vehicle).count()) if False else count_rows(db, Vehicle),
            "open_tasks": db.scalar(select(Task).where(Task.closed_at.is_(None)).count())
            if False
            else count_open_tasks(db),
            "imports": count_rows(db, ImportBatch),
        }
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "user": user,
                "permissions": sorted(get_user_permission_codes(db, user)),
                "authorized_units": sorted(get_user_authorized_unit_codes(db, user)),
                "metrics": metrics,
            },
        )


@web_router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@web_router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not user.active or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                request,
                "login.html",
                {"error": "Email ou password invalidos."},
                status_code=401,
            )
        request.session["user_id"] = user.id
        record_audit(
            db,
            action="web.login",
            entity_type="user",
            entity_id=user.id,
            detail=f"Login web de {user.email}",
            user_id=user.id,
        )
        db.commit()
    return RedirectResponse("/", status_code=303)


@web_router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def count_rows(db, model) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(model)) or 0


def count_open_tasks(db) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(Task).where(Task.closed_at.is_(None))) or 0
