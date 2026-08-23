from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class StockReference:
    kind: str
    id: int
    version: int = 1

    def __post_init__(self) -> None:
        if (
            self.kind not in {"article", "movement", "order", "receipt"}
            or self.id <= 0
            or self.version != 1
        ):
            raise ValueError("Unsupported Stock reference")

    @property
    def value(self) -> str:
        return f"stock:{self.kind}:v{self.version}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> StockReference:
        module, kind, version, raw_id = value.split(":", 3)
        if module != "stock" or version != "v1":
            raise ValueError("Unsupported Stock reference")
        return cls(kind, int(raw_id))


@dataclass(frozen=True, slots=True)
class MaterialRequestReference:
    source_module: str
    request_id: str
    process_reference: str | None = None

    def __post_init__(self) -> None:
        if not self.source_module or not self.request_id:
            raise ValueError("Material request source and id are required")


@dataclass(frozen=True, slots=True)
class StockBalanceSnapshot:
    article: StockReference
    location_id: int
    quantity: Decimal
