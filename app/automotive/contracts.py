from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AutomotiveReference:
    kind: str
    id: int
    version: int = 1

    def __post_init__(self) -> None:
        if (
            self.kind not in {"vehicle", "workshop-process", "sale-profile"}
            or self.id <= 0
            or self.version != 1
        ):
            raise ValueError("Unsupported Automotive reference")

    @property
    def value(self) -> str:
        return f"automotive:{self.kind}:v{self.version}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> AutomotiveReference:
        module, kind, version, raw_id = value.split(":", 3)
        if module != "automotive" or version != "v1":
            raise ValueError("Unsupported Automotive reference")
        return cls(kind, int(raw_id))


@dataclass(frozen=True, slots=True)
class VehicleSummary:
    reference: AutomotiveReference
    plate: str | None
    vin: str | None
    display_name: str
    lifecycle_status: str | None
    operational_status: str | None


@dataclass(frozen=True, slots=True)
class WorkshopProcessSnapshot:
    reference: AutomotiveReference
    vehicle_reference: AutomotiveReference | None
    plate_snapshot: str | None
    status: str
    phase_code: str | None
    responsible_user_id: int | None
    opened_at: datetime | None
    scheduled_at: datetime | None
    received_at: datetime | None
    closed_at: datetime | None
