from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.admin import Role, User, UserRole
from app.models.organization import OrganizationalUnit, UserOrganizationalUnit


def create_user(
    db: Session,
    name: str,
    email: str,
    password: str,
    role_codes: list[str] | None = None,
    organizational_unit_codes: list[str] | None = None,
    active: bool = True,
) -> User:
    normalized_email = email.strip().lower()
    user = User(
        name=name.strip(),
        email=normalized_email,
        password_hash=hash_password(password),
        active=active,
    )
    db.add(user)
    db.flush()

    for role_code in role_codes or []:
        role = db.scalar(select(Role).where(Role.code == role_code))
        if role:
            db.add(UserRole(user_id=user.id, role_id=role.id))

    for unit_code in organizational_unit_codes or []:
        unit = db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code == unit_code))
        if unit:
            db.add(UserOrganizationalUnit(user_id=user.id, organizational_unit_id=unit.id))

    return user
