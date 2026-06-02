from datetime import datetime

from pydantic import Field, model_validator

from app.schemas.common import ApiModel


class VehicleBase(ApiModel):
    plate: str | None = Field(default=None, max_length=40)
    vin: str | None = Field(default=None, max_length=80)
    rentway_unit_nr: str | None = Field(default=None, max_length=80)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=160)
    version: str | None = Field(default=None, max_length=160)
    year: int | None = None
    lifecycle_status: str | None = Field(default=None, max_length=80)
    operational_status: str | None = Field(default=None, max_length=80)
    current_location_id: int | None = None
    active: bool = True
    notes: str | None = None


class VehicleCreate(VehicleBase):
    @model_validator(mode="after")
    def require_identifier(self):
        if not (self.plate or self.vin or self.rentway_unit_nr):
            raise ValueError("At least one identifier is required: plate, vin or rentway_unit_nr.")
        return self


class VehicleUpdate(ApiModel):
    plate: str | None = Field(default=None, max_length=40)
    vin: str | None = Field(default=None, max_length=80)
    rentway_unit_nr: str | None = Field(default=None, max_length=80)
    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=160)
    version: str | None = Field(default=None, max_length=160)
    year: int | None = None
    lifecycle_status: str | None = Field(default=None, max_length=80)
    operational_status: str | None = Field(default=None, max_length=80)
    current_location_id: int | None = None
    active: bool | None = None
    notes: str | None = None


class VehicleRead(VehicleBase):
    id: int
    created_at: datetime
    updated_at: datetime
