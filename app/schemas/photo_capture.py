from datetime import datetime

from pydantic import BaseModel, Field


class PhotoActionConfigInput(BaseModel):
    schema_version: int = 1
    action_type: str = "take_photo"
    title: str = Field(default="Tirar fotografia", min_length=1, max_length=200)
    instructions: str | None = Field(default=None, max_length=4000)
    min_photos: int = Field(default=1, ge=0, le=50)
    max_photos: int = Field(default=1, ge=1, le=50)
    required: bool = False
    allow_camera: bool = True
    allow_gallery: bool = True
    categories: list[str] = Field(default_factory=lambda: ["other"])
    observation: str = "optional"
    location_enabled: bool = False
    require_new_capture: bool = False
    review_required: bool = False
    retention_policy: str = "operational_evidence"
    max_file_bytes: int = Field(default=15_000_000, ge=100_000, le=50_000_000)


class PhotoDefinitionCreate(BaseModel):
    code: str = Field(min_length=2, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=200)
    change_note: str | None = Field(default=None, max_length=1000)
    config: PhotoActionConfigInput


class PhotoSessionCreate(BaseModel):
    definition_code: str | None = Field(default=None, max_length=120)
    definition_version: int | None = Field(default=None, ge=1)
    config: PhotoActionConfigInput | None = None
    task_id: int | None = None
    task_flow_step_id: int | None = None
    workshop_process_id: int | None = None
    phased_process_id: int | None = None
    phase_id: int | None = None
    vehicle_id: int | None = None
    entity_type: str | None = Field(default=None, max_length=120)
    entity_id: str | None = Field(default=None, max_length=120)


class PhotoReviewInput(BaseModel):
    decision: str
    reason: str | None = Field(default=None, max_length=4000)


class PhotoLocationInput(BaseModel):
    latitude: float
    longitude: float
    accuracy_m: float | None = Field(default=None, ge=0)
    consent: bool = False
    captured_at: datetime | None = None
