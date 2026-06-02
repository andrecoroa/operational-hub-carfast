from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import Permission, Role, RolePermission, User, UserRole
from app.models.organization import OrganizationalUnit, UserOrganizationalUnit


def get_user_permission_codes(db: Session, user: User) -> set[str]:
    rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
        .where(Role.active.is_(True))
    ).all()
    return {row[0] for row in rows}


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
