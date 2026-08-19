# ruff: noqa: B008

from __future__ import annotations

import csv
import io
import re
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, or_, select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.admin import Permission, Role, RolePermission, User, UserRole
from app.models.audit import AuditLog
from app.models.email import EmailChannel, EmailChannelRole, EmailTemplate
from app.models.integrations import EmailIntake, EmailIntakeAttachment
from app.models.organization import (
    OrganizationalUnit,
    Team,
    TeamMember,
    UserOrganizationalUnit,
)
from app.models.settings import SettingsCatalog, SettingsValue
from app.models.tasks import Task
from app.models.work_hierarchy import (
    RoleWorkScope,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
    WorkSourceDefault,
    WorkSubcategory,
)
from app.models.workshop_phased import WorkshopTemplate
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.services.users import create_user

clean_admin_router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{1,79}$")

SETTINGS_CATALOG_LABELS = {
    "vehicle_lifecycle_status": "Estado do ciclo de vida da viatura",
    "vehicle_operational_status": "Estado operacional da viatura",
    "task_status": "Estado das tarefas",
    "task_priority": "Prioridade das tarefas",
    "task_area": "Área das tarefas",
    "task_category": "Categoria das tarefas",
    "task_subcategory": "Subcategoria das tarefas",
    "document_type": "Tipos de documento",
    "import_type": "Tipos de importação",
}

SETTINGS_VALUE_LABELS = {
    "active": "Ativa",
    "for_sale": "Para venda",
    "sold": "Vendida",
    "inactive": "Inativa",
    "written_off": "Abatida",
    "in_contract": "Em contrato",
    "free": "Livre",
    "in_impro": "Em IMPRO",
    "in_preparation": "Em preparação",
    "blocked": "Bloqueada",
    "in_maintenance": "Em manutenção",
    "reserved": "Reservada",
    "in_transfer": "Em transferência",
    "planned": "Planeada",
    "new": "Nova",
    "in_execution": "Em execução",
    "delegated": "Delegada",
    "waiting": "Em espera",
    "execution_done": "Execução concluída",
    "ready_validation": "Pronta para validação",
    "closed": "Fechada",
    "cancelled": "Cancelada",
    "no_action_needed": "Sem ação necessária",
    "normal": "Normal",
    "high": "Alta",
    "urgent": "Urgente",
    "operations": "Operações",
    "workshop": "Oficina",
    "documents": "Documentação",
    "fleet": "Frota",
    "administration": "Administração",
    "request": "Pedido",
    "information": "Informação",
    "invoice": "Fatura",
    "work_order": "Folha de obra",
    "diagnostic": "Diagnóstico",
    "compliance": "Conformidade",
    "other": "Outro",
    "validation": "Validação",
    "missing_document": "Documento em falta",
    "data_mismatch": "Dados divergentes",
    "follow_up": "Acompanhamento",
    "support": "Suporte",
    "general": "Documento geral",
    "report": "Relatório",
    "photo": "Fotografia",
    "contract": "Contrato",
    "rentway_fleet": "Frota Rentway",
    "rentway_contracts": "Contratos Rentway",
    "rentway_impros": "IMPRO Rentway",
    "trade_debt": "Dívida comercial",
}

ADMIN_NAV = (
    (
        "overview",
        "Visão geral",
        "/v2-clean/admin/overview",
        ("admin.dashboard.read", "admin.manage"),
    ),
    (
        "users",
        "Utilizadores",
        "/v2-clean/admin/users",
        ("admin.users.read", "admin.users.manage", "users.manage", "admin.manage"),
    ),
    (
        "roles",
        "Perfis e permissões",
        "/v2-clean/admin/roles",
        ("admin.roles.read", "admin.roles.manage", "users.manage", "admin.manage"),
    ),
    (
        "organization",
        "Organização",
        "/v2-clean/admin/organization",
        ("admin.organization.read", "admin.organization.manage", "users.manage", "admin.manage"),
    ),
    (
        "settings",
        "Configurações",
        "/v2-clean/admin/settings",
        ("admin.settings.read", "admin.settings.manage", "settings.manage", "admin.manage"),
    ),
    (
        "work_classification",
        "Filas e classificação",
        "/v2-clean/admin/work-classification",
        ("admin.settings.read", "admin.settings.manage", "settings.manage", "admin.manage"),
    ),
    (
        "workshop_models",
        "Modelos da Oficina",
        "/v2-clean/admin/workshop-models",
        (
            "admin.workshop_models.read",
            "admin.workshop_models.manage",
            "settings.manage",
            "admin.manage",
        ),
    ),
    (
        "audit",
        "Auditoria",
        "/v2-clean/admin/audit",
        ("admin.audit.read", "admin.audit.export", "admin.manage"),
    ),
    (
        "integrations",
        "Integrações",
        "/v2-clean/admin/integrations",
        ("admin.integrations.read", "admin.integrations.manage", "settings.manage", "admin.manage"),
    ),
    (
        "security",
        "Segurança e acessos",
        "/v2-clean/admin/security",
        ("admin.security.read", "admin.security.manage", "users.manage", "admin.manage"),
    ),
)


WORK_ENTITY_MODELS = {
    "queue": WorkQueue,
    "department": WorkDepartment,
    "category": WorkCategory,
    "subcategory": WorkSubcategory,
}


def clean_admin_user_has(db, user: User | None, *permission_codes: str) -> bool:
    if not user or not user.active:
        return False
    permissions = get_user_permission_codes(db, user)
    return bool(permissions.intersection(permission_codes))


def _template_nav_permissions(request: Request) -> set[str]:
    raw_user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not raw_user_id:
        return set()
    cached_permissions = getattr(request.state, "permission_codes", None)
    if cached_permissions is not None:
        return set(cached_permissions)
    with SessionLocal() as db:
        user = db.get(User, int(raw_user_id))
        permissions = (
            get_user_permission_codes(db, user) if user and user.active else set()
        )
    request.state.permission_codes = permissions
    return permissions


def _template_nav_has_permission(
    request: Request,
    *permission_codes: str,
) -> bool:
    return bool(_template_nav_permissions(request).intersection(permission_codes))


templates.env.globals["nav_permissions"] = _template_nav_permissions
templates.env.globals["nav_has_permission"] = _template_nav_has_permission


def _authorized(
    request: Request,
    *permission_codes: str,
) -> tuple[int, set[str]] | None:
    raw_user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not raw_user_id:
        return None
    user_id = int(raw_user_id)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user or not user.active:
            request.session.clear()
            return None
        permissions = get_user_permission_codes(db, user)
    if not permissions.intersection(permission_codes):
        return None
    return user_id, permissions


def _denied(request: Request) -> RedirectResponse:
    if not request.session.get("user_id"):
        return RedirectResponse("/login?next=/v2-clean/admin", status_code=303)
    return RedirectResponse("/v2-clean?error=forbidden", status_code=303)


def _layout_context(
    db,
    user_id: int,
    permissions: set[str],
    section: str,
    **extra,
) -> dict[str, object]:
    user = db.get(User, user_id)
    nav = [
        {"code": code, "label": label, "href": href}
        for code, label, href, required in ADMIN_NAV
        if permissions.intersection(required)
    ]
    return {
        "active_menu": "clean_admin",
        "admin_section": section,
        "admin_nav": nav,
        "current_admin_user": user,
        "current_admin_permissions": permissions,
        **extra,
    }


def _redirect(path: str, flag: str, value: str = "1") -> RedirectResponse:
    separator = "&" if "?" in path else "?"
    return RedirectResponse(f"{path}{separator}{flag}={value}", status_code=303)


def _role_codes_for_user(db, user_id: int) -> set[str]:
    return {
        row[0]
        for row in db.execute(
            select(Role.code)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user_id)
        ).all()
    }


def _active_admin_count(db) -> int:
    return (
        db.scalar(
            select(func.count(func.distinct(User.id)))
            .select_from(User)
            .join(UserRole, UserRole.user_id == User.id)
            .join(Role, Role.id == UserRole.role_id)
            .where(User.active.is_(True), Role.active.is_(True), Role.code == "admin")
        )
        or 0
    )


@clean_admin_router.get("/v2-clean/admin/overview", response_class=HTMLResponse)
def clean_admin_overview(request: Request):
    access = _authorized(
        request,
        "admin.dashboard.read",
        "admin.manage",
        "users.manage",
        "settings.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    since = datetime.now(UTC) - timedelta(hours=24)
    with SessionLocal() as db:
        metrics = {
            "users": db.scalar(select(func.count()).select_from(User)) or 0,
            "active_users": db.scalar(
                select(func.count()).select_from(User).where(User.active.is_(True))
            )
            or 0,
            "roles": db.scalar(select(func.count()).select_from(Role).where(Role.active.is_(True)))
            or 0,
            "catalogs": db.scalar(
                select(func.count())
                .select_from(SettingsCatalog)
                .where(SettingsCatalog.active.is_(True))
            )
            or 0,
            "workshop_models": db.scalar(
                select(func.count())
                .select_from(WorkshopTemplate)
                .where(WorkshopTemplate.active.is_(True))
            )
            or 0,
            "audit_24h": db.scalar(
                select(func.count()).select_from(AuditLog).where(AuditLog.created_at >= since)
            )
            or 0,
            "integration_errors": db.scalar(
                select(func.count()).select_from(EmailIntake).where(EmailIntake.status == "error")
            )
            or 0,
        }
        recent_audit = db.scalars(
            select(AuditLog).order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(12)
        ).all()
        audit_user_ids = {entry.user_id for entry in recent_audit if entry.user_id}
        audit_users = (
            {
                item.id: item
                for item in db.scalars(select(User).where(User.id.in_(audit_user_ids))).all()
            }
            if audit_user_ids
            else {}
        )
        context = _layout_context(
            db,
            user_id,
            permissions,
            "overview",
            metrics=metrics,
            recent_audit=recent_audit,
            audit_users=audit_users,
            auth_mode="local",
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


@clean_admin_router.get("/v2-clean/admin/users", response_class=HTMLResponse)
def clean_admin_users(request: Request):
    access = _authorized(
        request,
        "admin.users.read",
        "admin.users.manage",
        "users.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.name, User.email).limit(250)).all()
        roles = db.scalars(select(Role).order_by(Role.name, Role.code)).all()
        units = db.scalars(
            select(OrganizationalUnit).order_by(
                OrganizationalUnit.sort_order,
                OrganizationalUnit.name,
            )
        ).all()
        teams = db.scalars(select(Team).order_by(Team.name)).all()
        user_ids = [item.id for item in users]
        role_rows = db.execute(
            select(UserRole.user_id, Role.code)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_(user_ids))
        ).all()
        unit_rows = db.execute(
            select(UserOrganizationalUnit.user_id, OrganizationalUnit.code)
            .join(
                OrganizationalUnit,
                OrganizationalUnit.id == UserOrganizationalUnit.organizational_unit_id,
            )
            .where(UserOrganizationalUnit.user_id.in_(user_ids))
        ).all()
        team_rows = db.execute(
            select(TeamMember.user_id, Team.code)
            .join(Team, Team.id == TeamMember.team_id)
            .where(TeamMember.user_id.in_(user_ids))
        ).all()
        user_roles: dict[int, set[str]] = {}
        user_units: dict[int, set[str]] = {}
        user_teams: dict[int, set[str]] = {}
        role_names = {item.code: item.name for item in roles}
        unit_names = {item.code: item.name for item in units}
        team_names = {item.code: item.name for item in teams}
        for target_id, code in role_rows:
            user_roles.setdefault(target_id, set()).add(code)
        for target_id, code in unit_rows:
            user_units.setdefault(target_id, set()).add(code)
        for target_id, code in team_rows:
            user_teams.setdefault(target_id, set()).add(code)
        context = _layout_context(
            db,
            user_id,
            permissions,
            "users",
            users=users,
            roles=roles,
            units=units,
            teams=teams,
            user_roles=user_roles,
            user_units=user_units,
            user_teams=user_teams,
            role_names=role_names,
            unit_names=unit_names,
            team_names=team_names,
            active_admin_count=_active_admin_count(db),
            can_manage=bool(
                permissions.intersection({"admin.users.manage", "users.manage", "admin.manage"})
            ),
            can_manage_credentials=bool(
                permissions.intersection(
                    {"admin.users.credentials", "users.manage", "admin.manage"}
                )
            ),
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


@clean_admin_router.post("/v2-clean/admin/users")
def clean_admin_create_user(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    role_codes: list[str] = Form(default=[]),
    unit_codes: list[str] = Form(default=[]),
    team_codes: list[str] = Form(default=[]),
):
    access = _authorized(
        request,
        "admin.users.credentials",
        "users.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    clean_name = name.strip()
    clean_email = email.strip().lower()
    if not clean_name or "@" not in clean_email or len(password) < 10:
        return _redirect("/v2-clean/admin/users", "error", "invalid_user")
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == clean_email)):
            return _redirect("/v2-clean/admin/users", "error", "duplicate_email")
        valid_roles = (
            db.scalars(select(Role).where(Role.code.in_(role_codes), Role.active.is_(True))).all()
            if role_codes
            else []
        )
        valid_units = (
            db.scalars(
                select(OrganizationalUnit).where(
                    OrganizationalUnit.code.in_(unit_codes),
                    OrganizationalUnit.active.is_(True),
                )
            ).all()
            if unit_codes
            else []
        )
        valid_teams = (
            db.scalars(select(Team).where(Team.code.in_(team_codes), Team.active.is_(True))).all()
            if team_codes
            else []
        )
        new_user = create_user(
            db,
            name=clean_name,
            email=clean_email,
            password=password,
            role_codes=[role.code for role in valid_roles],
            organizational_unit_codes=[unit.code for unit in valid_units],
        )
        db.flush()
        for team in valid_teams:
            db.add(TeamMember(team_id=team.id, user_id=new_user.id))
        record_audit(
            db,
            action="clean_admin.user.created",
            entity_type="user",
            entity_id=new_user.id,
            detail=new_user.email,
            after_json={
                "roles": sorted(role.code for role in valid_roles),
                "units": sorted(unit.code for unit in valid_units),
                "teams": sorted(team.code for team in valid_teams),
            },
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/users", "created")


@clean_admin_router.post("/v2-clean/admin/users/{target_user_id}/access")
def clean_admin_update_user_access(
    request: Request,
    target_user_id: int,
    role_codes: list[str] = Form(default=[]),
    unit_codes: list[str] = Form(default=[]),
    team_codes: list[str] = Form(default=[]),
    active: str | None = Form(default=None),
):
    access = _authorized(
        request,
        "admin.users.manage",
        "users.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    with SessionLocal() as db:
        target = db.get(User, target_user_id)
        if not target:
            return _redirect("/v2-clean/admin/users", "error", "missing_user")
        target_roles_before = _role_codes_for_user(db, target.id)
        new_active = active == "on"
        removing_admin = "admin" in target_roles_before and "admin" not in role_codes
        if target.id == user_id and not new_active:
            return _redirect("/v2-clean/admin/users", "error", "self_deactivation")
        if (
            "admin" in target_roles_before
            and (not new_active or removing_admin)
            and _active_admin_count(db) <= 1
        ):
            return _redirect("/v2-clean/admin/users", "error", "last_admin")
        valid_roles = (
            db.scalars(select(Role).where(Role.code.in_(role_codes), Role.active.is_(True))).all()
            if role_codes
            else []
        )
        valid_units = (
            db.scalars(
                select(OrganizationalUnit).where(
                    OrganizationalUnit.code.in_(unit_codes),
                    OrganizationalUnit.active.is_(True),
                )
            ).all()
            if unit_codes
            else []
        )
        valid_teams = (
            db.scalars(select(Team).where(Team.code.in_(team_codes), Team.active.is_(True))).all()
            if team_codes
            else []
        )
        before = {
            "active": target.active,
            "roles": sorted(target_roles_before),
            "units": sorted(
                row[0]
                for row in db.execute(
                    select(OrganizationalUnit.code)
                    .join(
                        UserOrganizationalUnit,
                        UserOrganizationalUnit.organizational_unit_id == OrganizationalUnit.id,
                    )
                    .where(UserOrganizationalUnit.user_id == target.id)
                ).all()
            ),
            "teams": sorted(
                row[0]
                for row in db.execute(
                    select(Team.code)
                    .join(TeamMember, TeamMember.team_id == Team.id)
                    .where(TeamMember.user_id == target.id)
                ).all()
            ),
        }
        target.active = new_active
        db.execute(delete(UserRole).where(UserRole.user_id == target.id))
        db.execute(
            delete(UserOrganizationalUnit).where(UserOrganizationalUnit.user_id == target.id)
        )
        db.execute(delete(TeamMember).where(TeamMember.user_id == target.id))
        for role in valid_roles:
            db.add(UserRole(user_id=target.id, role_id=role.id))
        for unit in valid_units:
            db.add(
                UserOrganizationalUnit(
                    user_id=target.id,
                    organizational_unit_id=unit.id,
                )
            )
        for team in valid_teams:
            db.add(TeamMember(user_id=target.id, team_id=team.id))
        after = {
            "active": target.active,
            "roles": sorted(role.code for role in valid_roles),
            "units": sorted(unit.code for unit in valid_units),
            "teams": sorted(team.code for team in valid_teams),
        }
        record_audit(
            db,
            action="clean_admin.user.access_updated",
            entity_type="user",
            entity_id=target.id,
            detail=target.email,
            before_json=before,
            after_json=after,
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/users", "saved")


@clean_admin_router.post("/v2-clean/admin/users/{target_user_id}/password")
def clean_admin_reset_password(
    request: Request,
    target_user_id: int,
    password: str = Form(""),
):
    access = _authorized(
        request,
        "admin.users.credentials",
        "users.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    if len(password) < 10:
        return _redirect("/v2-clean/admin/users", "error", "weak_password")
    with SessionLocal() as db:
        target = db.get(User, target_user_id)
        if not target:
            return _redirect("/v2-clean/admin/users", "error", "missing_user")
        target.password_hash = hash_password(password)
        record_audit(
            db,
            action="clean_admin.user.password_reset",
            entity_type="user",
            entity_id=target.id,
            detail=f"Credencial local redefinida para {target.email}",
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/users", "password_saved")


@clean_admin_router.get("/v2-clean/admin/roles", response_class=HTMLResponse)
def clean_admin_roles(request: Request):
    access = _authorized(
        request,
        "admin.roles.read",
        "admin.roles.manage",
        "users.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        roles = db.scalars(select(Role).order_by(Role.name, Role.code)).all()
        permission_catalog = db.scalars(select(Permission).order_by(Permission.code)).all()
        rows = db.execute(
            select(RolePermission.role_id, Permission.code).join(
                Permission, Permission.id == RolePermission.permission_id
            )
        ).all()
        role_permissions: dict[int, set[str]] = {}
        for role_id, code in rows:
            role_permissions.setdefault(role_id, set()).add(code)
        permission_groups: dict[str, list[Permission]] = {}
        for permission in permission_catalog:
            group = permission.code.split(".", 1)[0]
            if permission.code.startswith("admin."):
                parts = permission.code.split(".")
                group = f"admin.{parts[1]}" if len(parts) > 1 else "admin"
            permission_groups.setdefault(group, []).append(permission)
        context = _layout_context(
            db,
            user_id,
            permissions,
            "roles",
            roles=roles,
            role_permissions=role_permissions,
            permission_groups=permission_groups,
            can_manage=bool(
                permissions.intersection({"admin.roles.manage", "users.manage", "admin.manage"})
            ),
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


@clean_admin_router.post("/v2-clean/admin/roles")
def clean_admin_create_role(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
):
    access = _authorized(
        request,
        "admin.roles.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    clean_code = code.strip().lower()
    clean_name = name.strip()
    if not CODE_PATTERN.fullmatch(clean_code) or not clean_name:
        return _redirect("/v2-clean/admin/roles", "error", "invalid_role")
    with SessionLocal() as db:
        if db.scalar(select(Role).where(Role.code == clean_code)):
            return _redirect("/v2-clean/admin/roles", "error", "duplicate_role")
        role = Role(
            code=clean_code,
            name=clean_name,
            description=description.strip() or None,
            active=True,
            is_system=False,
        )
        db.add(role)
        db.flush()
        record_audit(
            db,
            action="clean_admin.role.created",
            entity_type="role",
            entity_id=role.id,
            detail=role.code,
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/roles", "created")


@clean_admin_router.post("/v2-clean/admin/roles/{role_id}/permissions")
def clean_admin_update_role_permissions(
    request: Request,
    role_id: int,
    permission_codes: list[str] = Form(default=[]),
):
    access = _authorized(
        request,
        "admin.roles.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    with SessionLocal() as db:
        role = db.get(Role, role_id)
        if not role:
            return _redirect("/v2-clean/admin/roles", "error", "missing_role")
        if role.code == "admin":
            return _redirect("/v2-clean/admin/roles", "error", "protected_admin")
        before = sorted(
            row[0]
            for row in db.execute(
                select(Permission.code)
                .join(
                    RolePermission,
                    RolePermission.permission_id == Permission.id,
                )
                .where(RolePermission.role_id == role.id)
            ).all()
        )
        valid = (
            db.scalars(select(Permission).where(Permission.code.in_(permission_codes))).all()
            if permission_codes
            else []
        )
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for permission in valid:
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=permission.id,
                )
            )
        after = sorted(permission.code for permission in valid)
        record_audit(
            db,
            action="clean_admin.role.permissions_updated",
            entity_type="role",
            entity_id=role.id,
            detail=role.code,
            before_json={"permissions": before},
            after_json={"permissions": after},
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/roles", "saved")


@clean_admin_router.post("/v2-clean/admin/roles/{role_id}/toggle")
def clean_admin_toggle_role(request: Request, role_id: int):
    access = _authorized(request, "admin.roles.manage", "admin.manage")
    if not access:
        return _denied(request)
    user_id, _permissions = access
    with SessionLocal() as db:
        role = db.get(Role, role_id)
        if not role or role.code == "admin":
            return _redirect("/v2-clean/admin/roles", "error", "protected_admin")
        before = role.active
        role.active = not role.active
        record_audit(
            db,
            action="clean_admin.role.activation_changed",
            entity_type="role",
            entity_id=role.id,
            detail=role.code,
            before_json={"active": before},
            after_json={"active": role.active},
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/roles", "saved")


@clean_admin_router.get("/v2-clean/admin/organization", response_class=HTMLResponse)
def clean_admin_organization(request: Request):
    access = _authorized(
        request,
        "admin.organization.read",
        "admin.organization.manage",
        "users.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        units = db.scalars(
            select(OrganizationalUnit).order_by(
                OrganizationalUnit.sort_order,
                OrganizationalUnit.name,
            )
        ).all()
        teams = db.scalars(select(Team).order_by(Team.name)).all()
        unit_by_id = {unit.id: unit for unit in units}
        team_member_counts = {
            row[0]: row[1]
            for row in db.execute(
                select(TeamMember.team_id, func.count()).group_by(TeamMember.team_id)
            ).all()
        }
        context = _layout_context(
            db,
            user_id,
            permissions,
            "organization",
            units=units,
            teams=teams,
            unit_by_id=unit_by_id,
            team_member_counts=team_member_counts,
            can_manage=bool(
                permissions.intersection({"admin.organization.manage", "admin.manage"})
            ),
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


@clean_admin_router.post("/v2-clean/admin/organization/units")
def clean_admin_create_unit(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    unit_type: str = Form("workspace_area"),
    parent_id: int | None = Form(default=None),
):
    access = _authorized(
        request,
        "admin.organization.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    clean_code = code.strip().lower()
    if not CODE_PATTERN.fullmatch(clean_code) or not name.strip():
        return _redirect("/v2-clean/admin/organization", "error", "invalid_unit")
    with SessionLocal() as db:
        if db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code == clean_code)):
            return _redirect("/v2-clean/admin/organization", "error", "duplicate_unit")
        if parent_id and not db.get(OrganizationalUnit, parent_id):
            parent_id = None
        unit = OrganizationalUnit(
            code=clean_code,
            name=name.strip(),
            unit_type=unit_type.strip() or "workspace_area",
            parent_id=parent_id,
            active=True,
            sort_order=0,
        )
        db.add(unit)
        db.flush()
        record_audit(
            db,
            action="clean_admin.organization.unit_created",
            entity_type="organizational_unit",
            entity_id=unit.id,
            detail=unit.code,
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/organization", "created")


@clean_admin_router.post("/v2-clean/admin/organization/units/{unit_id}")
def clean_admin_update_unit(
    request: Request,
    unit_id: int,
    name: str = Form(""),
    unit_type: str = Form("workspace_area"),
    parent_id: int | None = Form(default=None),
    sort_order: int = Form(0),
    active: str | None = Form(default=None),
):
    access = _authorized(
        request,
        "admin.organization.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    with SessionLocal() as db:
        unit = db.get(OrganizationalUnit, unit_id)
        if not unit:
            return _redirect("/v2-clean/admin/organization", "error", "missing_unit")
        if parent_id == unit.id:
            parent_id = None
        before = {
            "name": unit.name,
            "unit_type": unit.unit_type,
            "parent_id": unit.parent_id,
            "active": unit.active,
            "sort_order": unit.sort_order,
        }
        unit.name = name.strip() or unit.name
        unit.unit_type = unit_type.strip() or unit.unit_type
        unit.parent_id = parent_id
        unit.sort_order = sort_order
        unit.active = active == "on"
        record_audit(
            db,
            action="clean_admin.organization.unit_updated",
            entity_type="organizational_unit",
            entity_id=unit.id,
            detail=unit.code,
            before_json=before,
            after_json={
                "name": unit.name,
                "unit_type": unit.unit_type,
                "parent_id": unit.parent_id,
                "active": unit.active,
                "sort_order": unit.sort_order,
            },
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/organization", "saved")


@clean_admin_router.post("/v2-clean/admin/organization/teams")
def clean_admin_create_team(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    organizational_unit_id: int | None = Form(default=None),
):
    access = _authorized(
        request,
        "admin.organization.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    clean_code = code.strip().lower()
    if not CODE_PATTERN.fullmatch(clean_code) or not name.strip():
        return _redirect("/v2-clean/admin/organization", "error", "invalid_team")
    with SessionLocal() as db:
        if db.scalar(select(Team).where(Team.code == clean_code)):
            return _redirect("/v2-clean/admin/organization", "error", "duplicate_team")
        team = Team(
            code=clean_code,
            name=name.strip(),
            organizational_unit_id=organizational_unit_id,
            active=True,
        )
        db.add(team)
        db.flush()
        record_audit(
            db,
            action="clean_admin.organization.team_created",
            entity_type="team",
            entity_id=team.id,
            detail=team.code,
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/organization", "created")


@clean_admin_router.post("/v2-clean/admin/organization/teams/{team_id}")
def clean_admin_update_team(
    request: Request,
    team_id: int,
    name: str = Form(""),
    organizational_unit_id: int | None = Form(default=None),
    active: str | None = Form(default=None),
):
    access = _authorized(
        request,
        "admin.organization.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    with SessionLocal() as db:
        team = db.get(Team, team_id)
        if not team:
            return _redirect("/v2-clean/admin/organization", "error", "missing_team")
        before = {
            "name": team.name,
            "organizational_unit_id": team.organizational_unit_id,
            "active": team.active,
        }
        team.name = name.strip() or team.name
        team.organizational_unit_id = organizational_unit_id
        team.active = active == "on"
        record_audit(
            db,
            action="clean_admin.organization.team_updated",
            entity_type="team",
            entity_id=team.id,
            detail=team.code,
            before_json=before,
            after_json={
                "name": team.name,
                "organizational_unit_id": team.organizational_unit_id,
                "active": team.active,
            },
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/organization", "saved")


@clean_admin_router.get("/v2-clean/admin/settings", response_class=HTMLResponse)
def clean_admin_settings(request: Request):
    access = _authorized(
        request,
        "admin.settings.read",
        "admin.settings.manage",
        "settings.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        catalogs = db.scalars(select(SettingsCatalog).order_by(SettingsCatalog.name)).all()
        values = db.scalars(
            select(SettingsValue).order_by(
                SettingsValue.catalog_id,
                SettingsValue.sort_order,
                SettingsValue.label,
            )
        ).all()
        values_by_catalog: dict[int, list[SettingsValue]] = {}
        for value in values:
            values_by_catalog.setdefault(value.catalog_id, []).append(value)
        context = _layout_context(
            db,
            user_id,
            permissions,
            "settings",
            catalogs=catalogs,
            values_by_catalog=values_by_catalog,
            catalog_display_names={
                catalog.id: SETTINGS_CATALOG_LABELS.get(catalog.code, catalog.name)
                for catalog in catalogs
            },
            value_display_labels={
                value.id: SETTINGS_VALUE_LABELS.get(value.code, value.label)
                for value in values
            },
            can_manage=bool(
                permissions.intersection(
                    {"admin.settings.manage", "settings.manage", "admin.manage"}
                )
            ),
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


@clean_admin_router.get(
    "/v2-clean/admin/work-classification", response_class=HTMLResponse
)
def clean_admin_work_classification(request: Request):
    access = _authorized(
        request,
        "admin.settings.read",
        "admin.settings.manage",
        "settings.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        queues = db.scalars(select(WorkQueue).order_by(WorkQueue.sort_order, WorkQueue.name)).all()
        departments = db.scalars(
            select(WorkDepartment).order_by(
                WorkDepartment.queue_id, WorkDepartment.sort_order, WorkDepartment.name
            )
        ).all()
        categories = db.scalars(
            select(WorkCategory).order_by(
                WorkCategory.department_id, WorkCategory.sort_order, WorkCategory.name
            )
        ).all()
        subcategories = db.scalars(
            select(WorkSubcategory).order_by(
                WorkSubcategory.category_id,
                WorkSubcategory.sort_order,
                WorkSubcategory.name,
            )
        ).all()
        roles = db.scalars(select(Role).where(Role.active.is_(True)).order_by(Role.name)).all()
        scopes = db.scalars(select(RoleWorkScope).order_by(RoleWorkScope.role_id)).all()
        channels = db.scalars(select(EmailChannel).order_by(EmailChannel.name)).all()
        channel_roles = db.scalars(
            select(EmailChannelRole).order_by(
                EmailChannelRole.channel_id, EmailChannelRole.role_id
            )
        ).all()
        email_templates = db.scalars(
            select(EmailTemplate).order_by(EmailTemplate.name)
        ).all()
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
        source_defaults = db.scalars(
            select(WorkSourceDefault).order_by(
                WorkSourceDefault.source_type, WorkSourceDefault.source_key
            )
        ).all()
        usage_fields = {
            "queue": Task.work_queue_id,
            "department": Task.work_department_id,
            "category": Task.work_category_id,
            "subcategory": Task.work_subcategory_id,
        }
        usage_counts = {
            level: {
                item_id: count
                for item_id, count in db.execute(
                    select(field, func.count(Task.id))
                    .where(field.is_not(None))
                    .group_by(field)
                ).all()
            }
            for level, field in usage_fields.items()
        }
        child_counts = {
            "queue": {
                item.id: sum(1 for child in departments if child.queue_id == item.id)
                for item in queues
            },
            "department": {
                item.id: sum(
                    1 for child in categories if child.department_id == item.id
                )
                for item in departments
            },
            "category": {
                item.id: sum(
                    1 for child in subcategories if child.category_id == item.id
                )
                for item in categories
            },
            "subcategory": {item.id: 0 for item in subcategories},
        }
        context = _layout_context(
            db,
            user_id,
            permissions,
            "work_classification",
            work_queues=queues,
            work_departments=departments,
            work_categories=categories,
            work_subcategories=subcategories,
            work_queues_by_id={item.id: item for item in queues},
            work_departments_by_id={item.id: item for item in departments},
            work_categories_by_id={item.id: item for item in categories},
            work_subcategories_by_id={item.id: item for item in subcategories},
            roles=roles,
            roles_by_id={item.id: item for item in roles},
            work_scopes=scopes,
            email_channels=channels,
            email_channel_roles=channel_roles,
            email_templates=email_templates,
            active_users=users,
            source_defaults=source_defaults,
            work_usage_counts=usage_counts,
            work_child_counts=child_counts,
            can_manage=bool(
                permissions.intersection(
                    {"admin.settings.manage", "settings.manage", "admin.manage"}
                )
            ),
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


def _work_classification_manage_access(request: Request):
    return _authorized(
        request, "admin.settings.manage", "settings.manage", "admin.manage"
    )


@clean_admin_router.post("/v2-clean/admin/work-classification/items/{entity_type}")
def clean_admin_create_work_classification(
    request: Request,
    entity_type: str,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
    parent_id: int | None = Form(None),
    sort_order: int = Form(0),
    requires_description: str = Form(""),
):
    access = _work_classification_manage_access(request)
    if not access:
        return _denied(request)
    model = WORK_ENTITY_MODELS.get(entity_type)
    clean_code = code.strip().lower()
    if not model or not CODE_PATTERN.fullmatch(clean_code) or not name.strip():
        return _redirect(
            "/v2-clean/admin/work-classification", "error", "invalid_classification"
        )
    parent_fields = {
        "department": "queue_id",
        "category": "department_id",
        "subcategory": "category_id",
    }
    if entity_type != "queue" and not parent_id:
        return _redirect(
            "/v2-clean/admin/work-classification", "error", "missing_parent"
        )
    values = {
        "code": clean_code,
        "name": name.strip(),
        "description": description.strip() or None,
        "sort_order": sort_order,
        "active": True,
    }
    if entity_type != "queue":
        values[parent_fields[entity_type]] = parent_id
        values["requires_description"] = requires_description == "on"
    with SessionLocal() as db:
        db.add(model(**values))
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post(
    "/v2-clean/admin/work-classification/items/{entity_type}/{entity_id}"
)
def clean_admin_update_work_classification(
    request: Request,
    entity_type: str,
    entity_id: int,
    name: str = Form(""),
    description: str = Form(""),
    sort_order: int = Form(0),
    active: str = Form(""),
    requires_description: str = Form(""),
):
    access = _work_classification_manage_access(request)
    if not access:
        return _denied(request)
    model = WORK_ENTITY_MODELS.get(entity_type)
    if not model or not name.strip():
        return _redirect("/v2-clean/admin/work-classification", "error", "invalid")
    with SessionLocal() as db:
        item = db.get(model, entity_id)
        if not item:
            return _redirect("/v2-clean/admin/work-classification", "error", "missing")
        item.name = name.strip()
        item.description = description.strip() or None
        item.sort_order = sort_order
        item.active = active == "on"
        if hasattr(item, "requires_description"):
            item.requires_description = requires_description == "on"
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post("/v2-clean/admin/work-classification/scopes")
def clean_admin_save_work_scope(
    request: Request,
    role_id: int = Form(...),
    queue_id: int = Form(...),
    department_id: int | None = Form(None),
    category_id: int | None = Form(None),
    subcategory_id: int | None = Form(None),
    can_read: str = Form(""),
    can_create: str = Form(""),
    can_update: str = Form(""),
    can_assign: str = Form(""),
    can_close: str = Form(""),
    can_manage: str = Form(""),
):
    if not _work_classification_manage_access(request):
        return _denied(request)
    with SessionLocal() as db:
        scope = db.scalar(
            select(RoleWorkScope).where(
                RoleWorkScope.role_id == role_id,
                RoleWorkScope.queue_id == queue_id,
                RoleWorkScope.department_id == department_id,
                RoleWorkScope.category_id == category_id,
                RoleWorkScope.subcategory_id == subcategory_id,
            )
        ) or RoleWorkScope(
            role_id=role_id,
            queue_id=queue_id,
            department_id=department_id,
            category_id=category_id,
            subcategory_id=subcategory_id,
        )
        scope.can_read = can_read == "on"
        scope.can_create = can_create == "on"
        scope.can_update = can_update == "on"
        scope.can_assign = can_assign == "on"
        scope.can_close = can_close == "on"
        scope.can_manage = can_manage == "on"
        db.add(scope)
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post("/v2-clean/admin/work-classification/scopes/{scope_id}/delete")
def clean_admin_delete_work_scope(request: Request, scope_id: int):
    if not _work_classification_manage_access(request):
        return _denied(request)
    with SessionLocal() as db:
        scope = db.get(RoleWorkScope, scope_id)
        if scope:
            db.delete(scope)
            db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post("/v2-clean/admin/work-classification/email-channels/{channel_id}")
def clean_admin_update_email_channel(
    request: Request,
    channel_id: int,
    name: str = Form(""),
    active: str = Form(""),
    auto_task_mode: str = Form("none"),
    default_queue_id: int | None = Form(None),
    default_department_id: int | None = Form(None),
    default_category_id: int | None = Form(None),
    default_subcategory_id: int | None = Form(None),
    default_document_type: str = Form(""),
    default_assignee_id: int | None = Form(None),
    default_due_days: int | None = Form(None),
    default_wait_days: int | None = Form(None),
):
    if not _work_classification_manage_access(request):
        return _denied(request)
    if auto_task_mode not in {"none", "open", "complete"}:
        return _redirect("/v2-clean/admin/work-classification", "error", "invalid_mode")
    with SessionLocal() as db:
        channel = db.get(EmailChannel, channel_id)
        if not channel:
            return _redirect("/v2-clean/admin/work-classification", "error", "missing")
        channel.name = name.strip() or channel.name
        channel.active = active == "on"
        channel.auto_task_mode = auto_task_mode
        channel.default_queue_id = default_queue_id
        channel.default_department_id = default_department_id
        channel.default_category_id = default_category_id
        channel.default_subcategory_id = default_subcategory_id
        channel.default_document_type = default_document_type.strip() or None
        channel.default_assignee_id = default_assignee_id
        channel.default_due_days = default_due_days
        channel.default_wait_days = default_wait_days
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post("/v2-clean/admin/work-classification/email-channel-roles")
def clean_admin_save_email_channel_role(
    request: Request,
    channel_id: int = Form(...),
    role_id: int = Form(...),
    can_read: str = Form(""),
    can_reply: str = Form(""),
    can_send_direct: str = Form(""),
    can_approve: str = Form(""),
    can_manage: str = Form(""),
):
    if not _work_classification_manage_access(request):
        return _denied(request)
    with SessionLocal() as db:
        grant = db.scalar(
            select(EmailChannelRole).where(
                EmailChannelRole.channel_id == channel_id,
                EmailChannelRole.role_id == role_id,
            )
        ) or EmailChannelRole(channel_id=channel_id, role_id=role_id)
        grant.can_read = can_read == "on"
        grant.can_reply = can_reply == "on"
        grant.can_send_direct = can_send_direct == "on"
        grant.can_approve = can_approve == "on"
        grant.can_manage = can_manage == "on"
        db.add(grant)
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post("/v2-clean/admin/work-classification/email-templates")
def clean_admin_create_email_template(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    subject_template: str = Form(""),
    body_template: str = Form(""),
    channel_id: int | None = Form(None),
    category_id: int | None = Form(None),
    subcategory_id: int | None = Form(None),
):
    access = _work_classification_manage_access(request)
    if not access:
        return _denied(request)
    clean_code = code.strip().lower()
    if not CODE_PATTERN.fullmatch(clean_code) or not name.strip() or not body_template.strip():
        return _redirect("/v2-clean/admin/work-classification", "error", "invalid_template")
    with SessionLocal() as db:
        db.add(
            EmailTemplate(
                code=clean_code,
                name=name.strip(),
                subject_template=subject_template.strip() or None,
                body_template=body_template.strip(),
                channel_id=channel_id,
                category_id=category_id,
                subcategory_id=subcategory_id,
                active=True,
                created_by_id=access[0],
            )
        )
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post(
    "/v2-clean/admin/work-classification/email-templates/{template_id}"
)
def clean_admin_update_email_template(
    request: Request,
    template_id: int,
    name: str = Form(""),
    subject_template: str = Form(""),
    body_template: str = Form(""),
    channel_id: int | None = Form(None),
    category_id: int | None = Form(None),
    subcategory_id: int | None = Form(None),
    active: str = Form(""),
):
    if not _work_classification_manage_access(request):
        return _denied(request)
    if not name.strip() or not body_template.strip():
        return _redirect(
            "/v2-clean/admin/work-classification", "error", "invalid_template"
        )
    with SessionLocal() as db:
        item = db.get(EmailTemplate, template_id)
        if not item:
            return _redirect(
                "/v2-clean/admin/work-classification", "error", "missing"
            )
        item.name = name.strip()
        item.subject_template = subject_template.strip() or None
        item.body_template = body_template.strip()
        item.channel_id = channel_id
        item.category_id = category_id
        item.subcategory_id = subcategory_id
        item.active = active == "on"
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


WORK_SOURCE_TYPES = {"recurring", "email", "documentation", "workshop", "stock"}


@clean_admin_router.post("/v2-clean/admin/work-classification/source-defaults")
def clean_admin_create_source_default(
    request: Request,
    source_type: str = Form(""),
    source_key: str = Form(""),
    queue_id: int | None = Form(None),
    department_id: int | None = Form(None),
    category_id: int | None = Form(None),
    subcategory_id: int | None = Form(None),
):
    if not _work_classification_manage_access(request):
        return _denied(request)
    clean_type = source_type.strip().lower()
    clean_key = source_key.strip().lower()
    if clean_type not in WORK_SOURCE_TYPES or not CODE_PATTERN.fullmatch(clean_key):
        return _redirect(
            "/v2-clean/admin/work-classification", "error", "invalid_source"
        )
    with SessionLocal() as db:
        if db.scalar(
            select(WorkSourceDefault).where(
                WorkSourceDefault.source_type == clean_type,
                WorkSourceDefault.source_key == clean_key,
            )
        ):
            return _redirect(
                "/v2-clean/admin/work-classification", "error", "duplicate_source"
            )
        db.add(
            WorkSourceDefault(
                source_type=clean_type,
                source_key=clean_key,
                queue_id=queue_id,
                department_id=department_id,
                category_id=category_id,
                subcategory_id=subcategory_id,
                active=True,
            )
        )
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post(
    "/v2-clean/admin/work-classification/source-defaults/{default_id}"
)
def clean_admin_update_source_default(
    request: Request,
    default_id: int,
    queue_id: int | None = Form(None),
    department_id: int | None = Form(None),
    category_id: int | None = Form(None),
    subcategory_id: int | None = Form(None),
    active: str = Form(""),
):
    if not _work_classification_manage_access(request):
        return _denied(request)
    with SessionLocal() as db:
        item = db.get(WorkSourceDefault, default_id)
        if not item:
            return _redirect(
                "/v2-clean/admin/work-classification", "error", "missing"
            )
        item.queue_id = queue_id
        item.department_id = department_id
        item.category_id = category_id
        item.subcategory_id = subcategory_id
        item.active = active == "on"
        db.commit()
    return _redirect("/v2-clean/admin/work-classification", "saved")


@clean_admin_router.post("/v2-clean/admin/settings/catalogs")
def clean_admin_create_catalog(
    request: Request,
    code: str = Form(""),
    name: str = Form(""),
    description: str = Form(""),
):
    access = _authorized(
        request,
        "admin.settings.manage",
        "settings.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    clean_code = code.strip().lower()
    if not CODE_PATTERN.fullmatch(clean_code) or not name.strip():
        return _redirect("/v2-clean/admin/settings", "error", "invalid_catalog")
    with SessionLocal() as db:
        if db.scalar(select(SettingsCatalog).where(SettingsCatalog.code == clean_code)):
            return _redirect("/v2-clean/admin/settings", "error", "duplicate_catalog")
        catalog = SettingsCatalog(
            code=clean_code,
            name=name.strip(),
            description=description.strip() or None,
            active=True,
        )
        db.add(catalog)
        db.flush()
        record_audit(
            db,
            action="clean_admin.settings.catalog_created",
            entity_type="settings_catalog",
            entity_id=catalog.id,
            detail=catalog.code,
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/settings", "created")


@clean_admin_router.post("/v2-clean/admin/settings/catalogs/{catalog_id}")
def clean_admin_update_catalog(
    request: Request,
    catalog_id: int,
    name: str = Form(""),
    description: str = Form(""),
    active: str | None = Form(default=None),
):
    access = _authorized(
        request,
        "admin.settings.manage",
        "settings.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    with SessionLocal() as db:
        catalog = db.get(SettingsCatalog, catalog_id)
        if not catalog:
            return _redirect("/v2-clean/admin/settings", "error", "missing_catalog")
        before = {
            "name": catalog.name,
            "description": catalog.description,
            "active": catalog.active,
        }
        catalog.name = name.strip() or catalog.name
        catalog.description = description.strip() or None
        catalog.active = active == "on"
        record_audit(
            db,
            action="clean_admin.settings.catalog_updated",
            entity_type="settings_catalog",
            entity_id=catalog.id,
            detail=catalog.code,
            before_json=before,
            after_json={
                "name": catalog.name,
                "description": catalog.description,
                "active": catalog.active,
            },
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/settings", "saved")


@clean_admin_router.post("/v2-clean/admin/settings/catalogs/{catalog_id}/values")
def clean_admin_create_value(
    request: Request,
    catalog_id: int,
    code: str = Form(""),
    label: str = Form(""),
    description: str = Form(""),
    color: str = Form(""),
    sort_order: int = Form(0),
):
    access = _authorized(
        request,
        "admin.settings.manage",
        "settings.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    clean_code = code.strip().lower()
    if not CODE_PATTERN.fullmatch(clean_code) or not label.strip():
        return _redirect("/v2-clean/admin/settings", "error", "invalid_value")
    with SessionLocal() as db:
        catalog = db.get(SettingsCatalog, catalog_id)
        if not catalog:
            return _redirect("/v2-clean/admin/settings", "error", "missing_catalog")
        existing = db.scalar(
            select(SettingsValue).where(
                SettingsValue.catalog_id == catalog.id,
                SettingsValue.code == clean_code,
            )
        )
        if existing:
            return _redirect("/v2-clean/admin/settings", "error", "duplicate_value")
        value = SettingsValue(
            catalog_id=catalog.id,
            code=clean_code,
            label=label.strip(),
            description=description.strip() or None,
            color=color.strip() or None,
            sort_order=sort_order,
            active=True,
            is_system=False,
        )
        db.add(value)
        db.flush()
        record_audit(
            db,
            action="clean_admin.settings.value_created",
            entity_type="settings_value",
            entity_id=value.id,
            detail=f"{catalog.code}.{value.code}",
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/settings", "created")


@clean_admin_router.post("/v2-clean/admin/settings/values/{value_id}")
def clean_admin_update_value(
    request: Request,
    value_id: int,
    label: str = Form(""),
    description: str = Form(""),
    color: str = Form(""),
    sort_order: int = Form(0),
    active: str | None = Form(default=None),
):
    access = _authorized(
        request,
        "admin.settings.manage",
        "settings.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, _permissions = access
    with SessionLocal() as db:
        value = db.get(SettingsValue, value_id)
        if not value:
            return _redirect("/v2-clean/admin/settings", "error", "missing_value")
        before = {
            "label": value.label,
            "description": value.description,
            "color": value.color,
            "sort_order": value.sort_order,
            "active": value.active,
        }
        value.label = label.strip() or value.label
        value.description = description.strip() or None
        value.color = color.strip() or None
        value.sort_order = sort_order
        value.active = active == "on"
        record_audit(
            db,
            action="clean_admin.settings.value_updated",
            entity_type="settings_value",
            entity_id=value.id,
            detail=value.code,
            before_json=before,
            after_json={
                "label": value.label,
                "description": value.description,
                "color": value.color,
                "sort_order": value.sort_order,
                "active": value.active,
            },
            user_id=user_id,
        )
        db.commit()
    return _redirect("/v2-clean/admin/settings", "saved")


def _audit_statement(
    *,
    q: str = "",
    action: str = "",
    entity_type: str = "",
    audit_user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    stmt = select(AuditLog)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                AuditLog.action.ilike(like),
                AuditLog.detail.ilike(like),
                AuditLog.entity_type.ilike(like),
                AuditLog.entity_id.ilike(like),
            )
        )
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if audit_user_id:
        stmt = stmt.where(AuditLog.user_id == audit_user_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min, tzinfo=UTC))
    if date_to:
        stmt = stmt.where(
            AuditLog.created_at
            < datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=UTC)
        )
    return stmt


@clean_admin_router.get("/v2-clean/admin/audit", response_class=HTMLResponse)
def clean_admin_audit(
    request: Request,
    q: str = "",
    action: str = "",
    entity_type: str = "",
    audit_user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    access = _authorized(
        request,
        "admin.audit.read",
        "admin.audit.export",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        entries = db.scalars(
            _audit_statement(
                q=q.strip(),
                action=action.strip(),
                entity_type=entity_type.strip(),
                audit_user_id=audit_user_id,
                date_from=date_from,
                date_to=date_to,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(300)
        ).all()
        users = db.scalars(select(User).order_by(User.name)).all()
        user_by_id = {item.id: item for item in users}
        actions = db.scalars(
            select(AuditLog.action).distinct().order_by(AuditLog.action).limit(300)
        ).all()
        entity_types = [
            item
            for item in db.scalars(
                select(AuditLog.entity_type)
                .where(AuditLog.entity_type.is_not(None))
                .distinct()
                .order_by(AuditLog.entity_type)
                .limit(200)
            ).all()
            if item
        ]
        context = _layout_context(
            db,
            user_id,
            permissions,
            "audit",
            audit_entries=entries,
            audit_users=users,
            audit_user_by_id=user_by_id,
            audit_actions=actions,
            audit_entity_types=entity_types,
            audit_filters={
                "q": q,
                "action": action,
                "entity_type": entity_type,
                "audit_user_id": audit_user_id,
                "date_from": date_from,
                "date_to": date_to,
            },
            can_export=bool(permissions.intersection({"admin.audit.export", "admin.manage"})),
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


@clean_admin_router.get("/v2-clean/admin/audit/export")
def clean_admin_audit_export(
    request: Request,
    q: str = "",
    action: str = "",
    entity_type: str = "",
    audit_user_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
):
    access = _authorized(request, "admin.audit.export", "admin.manage")
    if not access:
        return _denied(request)
    with SessionLocal() as db:
        entries = db.scalars(
            _audit_statement(
                q=q.strip(),
                action=action.strip(),
                entity_type=entity_type.strip(),
                audit_user_id=audit_user_id,
                date_from=date_from,
                date_to=date_to,
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(5000)
        ).all()
        user_ids = {entry.user_id for entry in entries if entry.user_id}
        user_by_id = (
            {
                user.id: user.email
                for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
            }
            if user_ids
            else {}
        )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "id",
            "data",
            "utilizador",
            "acao",
            "tipo_entidade",
            "id_entidade",
            "detalhe",
            "antes",
            "depois",
        ]
    )
    for entry in entries:
        writer.writerow(
            [
                entry.id,
                entry.created_at.isoformat() if entry.created_at else "",
                user_by_id.get(entry.user_id, ""),
                entry.action,
                entry.entity_type or "",
                entry.entity_id or "",
                entry.detail or "",
                entry.before_json or "",
                entry.after_json or "",
            ]
        )
    filename = f"carfast-auditoria-{datetime.now().date().isoformat()}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@clean_admin_router.get("/v2-clean/admin/integrations", response_class=HTMLResponse)
def clean_admin_integrations(request: Request, status: str = ""):
    access = _authorized(
        request,
        "admin.integrations.read",
        "admin.integrations.manage",
        "settings.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        stmt = select(EmailIntake)
        if status:
            stmt = stmt.where(EmailIntake.status == status)
        intakes = db.scalars(
            stmt.order_by(
                EmailIntake.received_at.desc().nullslast(),
                EmailIntake.id.desc(),
            ).limit(150)
        ).all()
        status_counts = {
            row[0]: row[1]
            for row in db.execute(
                select(EmailIntake.status, func.count()).group_by(EmailIntake.status)
            ).all()
        }
        attachment_count = db.scalar(select(func.count()).select_from(EmailIntakeAttachment)) or 0
        context = _layout_context(
            db,
            user_id,
            permissions,
            "integrations",
            email_intakes=intakes,
            integration_status_counts=status_counts,
            integration_attachment_count=attachment_count,
            integration_filter=status,
            integration_key_configured=bool(settings.integration_api_key),
            integration_auth_mode="Chave de API em variável de ambiente",
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)


@clean_admin_router.get("/v2-clean/admin/security", response_class=HTMLResponse)
def clean_admin_security(request: Request):
    access = _authorized(
        request,
        "admin.security.read",
        "admin.security.manage",
        "users.manage",
        "admin.manage",
    )
    if not access:
        return _denied(request)
    user_id, permissions = access
    with SessionLocal() as db:
        users = db.scalars(select(User).order_by(User.name)).all()
        privileged_users: list[dict[str, object]] = []
        users_without_roles: list[User] = []
        users_without_scope: list[User] = []
        for item in users:
            role_codes = _role_codes_for_user(db, item.id)
            permission_codes = get_user_permission_codes(db, item)
            admin_permissions = sorted(
                code for code in permission_codes if code.startswith("admin.")
            )
            if admin_permissions or "admin.manage" in permission_codes:
                privileged_users.append(
                    {
                        "user": item,
                        "roles": sorted(role_codes),
                        "permissions": admin_permissions,
                    }
                )
            if item.active and not role_codes:
                users_without_roles.append(item)
            has_scope = db.scalar(
                select(UserOrganizationalUnit.id).where(UserOrganizationalUnit.user_id == item.id)
            )
            if item.active and not has_scope:
                users_without_scope.append(item)
        context = _layout_context(
            db,
            user_id,
            permissions,
            "security",
            privileged_users=privileged_users,
            users_without_roles=users_without_roles,
            users_without_scope=users_without_scope,
            active_admin_count=_active_admin_count(db),
            local_auth_users=sum(1 for item in users if item.active),
            auth_mode="Autenticação local por e-mail e password",
            session_mode="Sessão assinada no navegador; não existe consola de sessões remotas",
        )
    return templates.TemplateResponse(request, "clean_admin.html", context)
