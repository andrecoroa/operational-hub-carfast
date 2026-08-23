from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ServiceDeskReference:
    capability: str
    id: int
    version: int = 1

    def __post_init__(self) -> None:
        if self.capability not in {"task", "process", "email"} or self.id <= 0 or self.version != 1:
            raise ValueError("Unsupported Service Desk reference")

    @property
    def value(self) -> str:
        return f"service-desk:{self.capability}:v{self.version}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> ServiceDeskReference:
        module, capability, version, raw_id = value.split(":", 3)
        if module != "service-desk" or version != "v1":
            raise ValueError("Unsupported Service Desk reference")
        return cls(capability, int(raw_id))


@dataclass(frozen=True, slots=True)
class EmailOriginCommand:
    message_id: str
    sender: str | None
    recipients: list | None
    subject: str | None
    received_at: datetime | None
    mailbox: str | None
    source_url: str | None
    rule_code: str | None = None


@dataclass(frozen=True, slots=True)
class WorkSummary:
    reference: ServiceDeskReference
    title: str
    status: str
    assigned_user_id: int | None = None
    assigned_team_id: int | None = None
    due_at: datetime | None = None

    def snapshot(self) -> dict[str, str | int | None]:
        return {
            "reference": self.reference.value,
            "title": self.title,
            "status": self.status,
            "assigned_user_id": self.assigned_user_id,
            "assigned_team_id": self.assigned_team_id,
            "due_at": self.due_at.isoformat() if self.due_at else None,
        }
