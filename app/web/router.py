from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import verify_password
from app.models.admin import User
from app.models.imports import ImportBatch
from app.models.tasks import Task, TaskHistory
from app.models.vehicles import Vehicle
from app.services.rentway_fleet_importer import import_rentway_fleet_xlsx
from app.services.audit import record_audit
from app.services.authorization import get_user_authorized_unit_codes, get_user_permission_codes

templates = Jinja2Templates(directory="app/templates")
web_router = APIRouter(include_in_schema=False)


@web_router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = get_web_user_id(request)
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


@web_router.get("/fleet", response_class=HTMLResponse)
def vehicles_page(request: Request, q: str | None = None, imported: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        stmt = select(Vehicle).order_by(Vehicle.plate, Vehicle.id).limit(100)
        if q:
            normalized = q.strip().upper().replace(" ", "")
            stmt = stmt.where(
                (Vehicle.plate == normalized)
                | (Vehicle.vin == normalized)
                | (Vehicle.rentway_unit_nr == normalized)
                | Vehicle.brand.ilike(f"%{q}%")
                | Vehicle.model.ilike(f"%{q}%")
            )
        vehicles = db.scalars(stmt).all()
        return templates.TemplateResponse(
            request,
            "vehicles.html",
            {
                "vehicles": vehicles,
                "q": q or "",
                "imported": imported,
            },
        )


@web_router.get("/imports/fleet", response_class=HTMLResponse)
def fleet_import_form(request: Request):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "fleet_import.html", {"error": None})


@web_router.post("/imports/fleet", response_class=HTMLResponse)
def fleet_import_submit(request: Request, file: UploadFile):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not file.filename.lower().endswith(".xlsx"):
        return templates.TemplateResponse(
            request,
            "fleet_import.html",
            {"error": "Carrega um ficheiro XLSX."},
            status_code=400,
        )

    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        with SessionLocal() as db:
            stats = import_rentway_fleet_xlsx(db, tmp_path, original_name=file.filename)
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(
        f"/fleet?imported={stats['created_rows']}+criadas,+{stats['updated_rows']}+atualizadas",
        status_code=303,
    )


@web_router.get("/task-board", response_class=HTMLResponse)
def task_board(request: Request, created: str | None = None, closed: str | None = None):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        tasks = db.scalars(
            select(Task)
            .where(Task.closed_at.is_(None))
            .order_by(Task.due_on.is_(None), Task.due_on, Task.id.desc())
            .limit(100)
        ).all()
        return templates.TemplateResponse(
            request,
            "tasks.html",
            {
                "tasks": tasks,
                "created": created,
                "closed": closed,
                "error": None,
            },
        )


@web_router.post("/task-board", response_class=HTMLResponse)
def task_create(
    request: Request,
    title: str = Form(...),
    category: str = Form("operacional"),
    priority: str = Form("normal"),
    description: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_title = title.strip()
    if not clean_title:
        with SessionLocal() as db:
            tasks = db.scalars(
                select(Task)
                .where(Task.closed_at.is_(None))
                .order_by(Task.due_on.is_(None), Task.due_on, Task.id.desc())
                .limit(100)
            ).all()
        return templates.TemplateResponse(
            request,
            "tasks.html",
            {
                "tasks": tasks,
                "created": None,
                "closed": None,
                "error": "Indica um titulo para a tarefa.",
            },
            status_code=400,
        )

    with SessionLocal() as db:
        task = Task(
            title=clean_title,
            description=description.strip() or None,
            category=category,
            status="new",
            priority=priority,
            created_by_id=user_id,
        )
        db.add(task)
        db.flush()
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        record_audit(
            db,
            action="task.create",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa criada: {task.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/task-board?created=1", status_code=303)


@web_router.post("/task-board/{task_id}/close")
def task_close(request: Request, task_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task and not task.closed_at:
            old_status = task.status
            task.status = "done"
            task.closed_at = datetime.now(UTC)
            db.add(
                TaskHistory(
                    task_id=task.id,
                    user_id=user_id,
                    field_name="status",
                    old_value=old_status,
                    new_value="done",
                )
            )
            record_audit(
                db,
                action="task.close",
                entity_type="task",
                entity_id=task.id,
                detail=f"Tarefa fechada: {task.title}",
                user_id=user_id,
            )
            db.commit()

    return RedirectResponse("/task-board?closed=1", status_code=303)


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


def get_web_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not user_id:
        return None
    return int(user_id)


def count_rows(db, model) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(model)) or 0


def count_open_tasks(db) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(Task).where(Task.closed_at.is_(None))) or 0
