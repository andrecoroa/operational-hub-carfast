from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import Permission, Role, RolePermission, User, UserRole
from app.models.organization import OrganizationalUnit, UserOrganizationalUnit

# Compatibility is intentionally additive.  Persisted grants are never rewritten here;
# legacy capabilities only acquire their documented granular equivalents at evaluation time.
PERMISSION_ALIASES: dict[str, set[str]] = {
    "admin.manage": {
        "admin.dashboard.read",
        "admin.users.read",
        "admin.users.manage",
        "admin.users.credentials",
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
        "admin.integrations.credentials",
        "admin.security.read",
        "admin.security.manage",
        "admin.evolution.read",
        "admin.evolution.manage",
    },
    "users.manage": {
        "admin.dashboard.read",
        "admin.users.read",
        "admin.users.manage",
        "admin.users.credentials",
        "admin.roles.read",
        "admin.organization.read",
        "admin.security.read",
    },
    "settings.manage": {
        "admin.dashboard.read",
        "admin.settings.read",
        "admin.settings.manage",
        "admin.workshop_models.read",
        "admin.workshop_models.manage",
        "admin.workshop_models.publish",
        "admin.integrations.read",
        "admin.integrations.manage",
        "admin.audit.read",
    },
    "tasks.audit.read": {"tasks.administration.read"},
    "tasks.audit.write": {"tasks.administration.write"},
    "service_desk.read": {"tasks.operational.read"},
    "service_desk.create": {"tasks.operational.write"},
    "service_desk.assume": {"tasks.operational.write"},
    "service_desk.assign": {"tasks.operational.write"},
    "service_desk.update": {"tasks.operational.write"},
    "service_desk.respond": {"tasks.operational.write"},
    "service_desk.complete": {"tasks.operational.write"},
    "service_desk.sla.manage": {"tasks.operational.write"},
}


def expand_permission_aliases(codes: set[str]) -> set[str]:
    expanded = set(codes)
    pending = list(codes)
    while pending:
        code = pending.pop()
        for alias in PERMISSION_ALIASES.get(code, set()):
            if alias not in expanded:
                expanded.add(alias)
                pending.append(alias)
    return expanded


def get_user_permission_codes(db: Session, user: User) -> set[str]:
    rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
        .where(Role.active.is_(True))
    ).all()
    return expand_permission_aliases({row[0] for row in rows})


def user_has_permission(db: Session, user: User, permission_code: str) -> bool:
    return permission_code in get_user_permission_codes(db, user)


def get_user_authorized_unit_codes(db: Session, user: User) -> set[str]:
    rows = db.execute(
        select(OrganizationalUnit.code)
        .join(
            UserOrganizationalUnit,
            UserOrganizationalUnit.organizational_unit_id == OrganizationalUnit.id,
        )
        .where(UserOrganizationalUnit.user_id == user.id)
        .where(OrganizationalUnit.active.is_(True))
    ).all()
    return {row[0] for row in rows}


def user_has_authorized_unit(db: Session, user: User, unit_code: str) -> bool:
    return unit_code in get_user_authorized_unit_codes(db, user)
