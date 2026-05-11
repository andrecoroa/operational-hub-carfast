from datetime import datetime

from app.schemas.common import ApiModel


class PermissionRead(ApiModel):
    id: int
    code: str
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class RoleRead(ApiModel):
    id: int
    code: str
    name: str
    description: str | None = None
    active: bool
    is_system: bool
    created_at: datetime
    updated_at: datetime

