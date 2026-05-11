from datetime import datetime

from pydantic import Field

from app.schemas.common import ApiModel


class OrganizationalUnitBase(ApiModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    unit_type: str = Field(min_length=2, max_length=40)
    parent_id: int | None = None
    description: str | None = None
    active: bool = True
    sort_order: int = 0


class OrganizationalUnitCreate(OrganizationalUnitBase):
    pass


class OrganizationalUnitUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    unit_type: str | None = Field(default=None, min_length=2, max_length=40)
    parent_id: int | None = None
    description: str | None = None
    active: bool | None = None
    sort_order: int | None = None


class OrganizationalUnitRead(OrganizationalUnitBase):
    id: int
    created_at: datetime
    updated_at: datetime


class TeamBase(ApiModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    organizational_unit_id: int | None = None
    active: bool = True


class TeamCreate(TeamBase):
    pass


class TeamUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    organizational_unit_id: int | None = None
    active: bool | None = None


class TeamRead(TeamBase):
    id: int
    created_at: datetime
    updated_at: datetime

