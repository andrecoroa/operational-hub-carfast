from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel


class SettingsCatalogBase(ApiModel):
    code: str = Field(min_length=2, max_length=80)
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None
    active: bool = True


class SettingsCatalogCreate(SettingsCatalogBase):
    pass


class SettingsCatalogUpdate(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    active: bool | None = None


class SettingsCatalogRead(SettingsCatalogBase):
    id: int
    created_at: datetime
    updated_at: datetime


class SettingsValueBase(ApiModel):
    code: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    description: str | None = None
    active: bool = True
    sort_order: int = 0
    color: str | None = None
    is_system: bool = False
    metadata_json: dict[str, Any] | None = None


class SettingsValueCreate(SettingsValueBase):
    pass


class SettingsValueUpdate(ApiModel):
    label: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    active: bool | None = None
    sort_order: int | None = None
    color: str | None = None
    metadata_json: dict[str, Any] | None = None


class SettingsValueRead(SettingsValueBase):
    id: int
    catalog_id: int
    created_at: datetime
    updated_at: datetime
