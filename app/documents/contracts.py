from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class DocumentReference:
    id: int
    version: int = 1

    def __post_init__(self) -> None:
        if self.id <= 0 or self.version != 1:
            raise ValueError("Unsupported document reference")

    @property
    def value(self) -> str:
        return f"document:v{self.version}:{self.id}"

    @classmethod
    def parse(cls, value: str) -> DocumentReference:
        kind, version, raw_id = value.split(":", 2)
        if kind != "document" or version != "v1":
            raise ValueError("Unsupported document reference")
        return cls(int(raw_id))


@dataclass(frozen=True, slots=True)
class SourceReference:
    module: str
    entity_type: str
    entity_id: str
    display_snapshot: str | None = None

    def __post_init__(self) -> None:
        if not self.module.strip() or not self.entity_type.strip() or not self.entity_id.strip():
            raise ValueError("Source reference fields are required")


@dataclass(frozen=True, slots=True)
class LinkIngestionRequest:
    title: str
    storage_path: str
    storage_provider: str
    source: str
    entry_channel: str
    document_type: str
    classification: str
    status: str = "received"
    original_name: str | None = None
    file_name: str | None = None
    storage_key: str | None = None
    external_url: str | None = None
    folder_path: str | None = None
    source_sender: str | None = None
    source_subject: str | None = None
    document_date: date | None = None
    uploaded_by_id: int | None = None
    vehicle_id: int | None = None
    plate: str | None = None


@dataclass(frozen=True, slots=True)
class DocumentSummary:
    reference: DocumentReference
    title: str
    status: str
    classification: str | None
    document_type: str | None
    storage_provider: str
    storage_path: str
    file_hash: str | None
    archived: bool

    def snapshot(self) -> dict[str, str | int | bool | None]:
        return {
            "reference": self.reference.value,
            "document_id": self.reference.id,
            "title": self.title,
            "status": self.status,
            "classification": self.classification,
            "document_type": self.document_type,
            "storage_provider": self.storage_provider,
            "file_hash": self.file_hash,
            "archived": self.archived,
        }
