from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.auth import require_permission
from app.api.deps import DbSession
from app.models.admin import Permission, Role
from app.schemas.admin import PermissionRead, RoleRead

router = APIRouter(prefix="/admin")
AdminAccess = Annotated[object, Depends(require_permission("admin.manage"))]


@router.get("/roles", response_model=list[RoleRead])
def list_roles(db: DbSession, _: AdminAccess):
    return db.scalars(select(Role).order_by(Role.name)).all()


@router.get("/permissions", response_model=list[PermissionRead])
def list_permissions(db: DbSession, _: AdminAccess):
    return db.scalars(select(Permission).order_by(Permission.code)).all()
