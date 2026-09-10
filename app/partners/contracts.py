from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PartnerReference:
    """Stable internal reference independent from a Python model name."""

    id: int
    version: int = 1
    kind: str = "partner"

    def __post_init__(self) -> None:
        if self.id <= 0:
            raise ValueError("Partner reference id must be positive")
        if self.version != 1 or self.kind != "partner":
            raise ValueError("Unsupported partner reference")

    @property
    def value(self) -> str:
        return f"partner:v{self.version}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> PartnerReference:
        prefix, version, raw_id = value.split(":", 2)
        if prefix != "partner" or version != "v1":
            raise ValueError("Unsupported partner reference")
        return cls(id=int(raw_id))


@dataclass(frozen=True, slots=True)
class PartnerSummary:
    """Permission-safe snapshot used when a live Partners lookup is unavailable."""

    reference: PartnerReference
    display_name: str
    legal_name: str | None
    tax_id: str | None
    primary_email: str | None
    primary_phone: str | None
    active: bool

    def snapshot(self) -> dict[str, str | int | bool | None]:
        return {
            "reference": self.reference.value,
            "partner_id": self.reference.id,
            "display_name": self.display_name,
            "legal_name": self.legal_name,
            "tax_id": self.tax_id,
            "primary_email": self.primary_email,
            "primary_phone": self.primary_phone,
            "active": self.active,
        }
