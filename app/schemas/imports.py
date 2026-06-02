from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel


class ImportBatchCreate(ApiModel):
    source_system: str = Field(min_length=2, max_length=80)
    import_type: str = Field(min_length=2, max_length=80)
    status: str = Field(default="pending", max_length=40)
    detail: str | None = None


class ImportBatchUpdate(ApiModel):
    status: str | None = Field(default=None, max_length=40)
    total_rows: int | None = None
    created_rows: int | None = None
    updated_rows: int | None = None
    skipped_rows: int | None = None
    error_rows: int | None = None
    detail: str | None = None


class ImportBatchRead(ApiModel):
    id: int
    source_system: str
    import_type: str
    status: str
    imported_by_id: int | None
    started_at: datetime
    finished_at: datetime | None
    total_rows: int
    created_rows: int
    updated_rows: int
    skipped_rows: int
    error_rows: int
    detail: str | None
    created_at: datetime
    updated_at: datetime


class ImportRawRowCreate(ApiModel):
    row_number: int
    external_reference: str | None = None
    raw_json: dict[str, Any]
    row_hash: str | None = None


class ImportRawRowRead(ImportRawRowCreate):
    id: int
    batch_id: int
    created_at: datetime
    updated_at: datetime


class ImportErrorCreate(ApiModel):
    row_number: int | None = None
    entity_type: str | None = Field(default=None, max_length=120)
    error_message: str
    raw_json: dict[str, Any] | None = None


class ImportErrorRead(ImportErrorCreate):
    id: int
    batch_id: int
    created_at: datetime
    updated_at: datetime
