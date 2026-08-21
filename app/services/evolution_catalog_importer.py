from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.evolution import EvolutionRecord, EvolutionRecordHistory

ALLOWED_TYPES = {
    "improvement",
    "question",
    "error",
    "decision",
    "future_implementation",
    "problem",
    "feature",
}
ALLOWED_STATUSES = {
    "registered",
    "analysis",
    "approved",
    "deferred",
    "rejected",
    "implementation",
    "completed",
}
ALLOWED_PRIORITIES = {"low", "normal", "high", "urgent"}
ALLOWED_FACTUAL_STATES = {
    "em produção",
    "implementado em branch por integrar",
    "em execução",
    "proposta aprovada",
    "apenas mockup/estudo",
    "bloqueado",
}


@dataclass(frozen=True)
class CatalogItem:
    external_key: str
    title: str
    description: str
    module: str
    factual_state: str
    record_type: str
    status: str
    priority: str
    sources: tuple[str, ...]
    dependencies: tuple[str, ...]
    next_step: str
    program_key: str | None = None
    reference_chat: str | None = None
    reference_branch: str | None = None
    reference_commit: str | None = None

    @property
    def origin(self) -> str:
        return f"catalog:{self.external_key}"

    @property
    def notes(self) -> str:
        dependencies = "; ".join(self.dependencies) if self.dependencies else "Nenhuma registada"
        lines = [
            f"Estado factual: {self.factual_state}",
            f"Dependências: {dependencies}",
            f"Próximo passo: {self.next_step}",
            f"Fontes: {'; '.join(self.sources)}",
        ]
        if self.program_key:
            lines.insert(1, f"Programa: {self.program_key}")
        return "\n".join(lines)


@dataclass
class ImportEvent:
    external_key: str
    action: str
    reason: str
    record_id: int | None = None


@dataclass
class ImportReport:
    dry_run: bool
    created: int
    updated: int
    ignored: int
    events: list[ImportEvent]

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "created": self.created,
            "updated": self.updated,
            "ignored": self.ignored,
            "events": [asdict(event) for event in self.events],
        }


def _required_text(raw: dict[str, Any], key: str) -> str:
    value = str(raw.get(key) or "").strip()
    if not value:
        raise ValueError(f"Campo obrigatório vazio: {key}")
    return value


def _text_tuple(raw: dict[str, Any], key: str) -> tuple[str, ...]:
    value = raw.get(key, [])
    if not isinstance(value, list):
        raise ValueError(f"{key} tem de ser uma lista")
    return tuple(str(item).strip() for item in value if str(item).strip())


def load_catalog(path: Path) -> list[CatalogItem]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("O catálogo tem de ser uma lista JSON")

    items: list[CatalogItem] = []
    keys: set[str] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            raise ValueError("Cada entrada do catálogo tem de ser um objeto")
        item = CatalogItem(
            external_key=_required_text(raw, "external_key"),
            title=_required_text(raw, "title"),
            description=_required_text(raw, "description"),
            module=_required_text(raw, "module"),
            factual_state=_required_text(raw, "factual_state").lower(),
            record_type=_required_text(raw, "record_type"),
            status=_required_text(raw, "status"),
            priority=_required_text(raw, "priority"),
            sources=_text_tuple(raw, "sources"),
            dependencies=_text_tuple(raw, "dependencies"),
            next_step=_required_text(raw, "next_step"),
            program_key=str(raw.get("program_key") or "").strip() or None,
            reference_chat=str(raw.get("reference_chat") or "").strip() or None,
            reference_branch=str(raw.get("reference_branch") or "").strip() or None,
            reference_commit=str(raw.get("reference_commit") or "").strip() or None,
        )
        if item.external_key in keys:
            raise ValueError(f"Chave externa duplicada: {item.external_key}")
        if len(item.origin) > 160:
            raise ValueError(f"Origem excede 160 caracteres: {item.external_key}")
        if item.factual_state not in ALLOWED_FACTUAL_STATES:
            raise ValueError(
                f"Estado factual inválido em {item.external_key}: {item.factual_state}"
            )
        if item.record_type not in ALLOWED_TYPES:
            raise ValueError(f"Tipo inválido em {item.external_key}: {item.record_type}")
        if item.status not in ALLOWED_STATUSES:
            raise ValueError(f"Estado Evolução inválido em {item.external_key}: {item.status}")
        if item.priority not in ALLOWED_PRIORITIES:
            raise ValueError(f"Prioridade inválida em {item.external_key}: {item.priority}")
        if item.program_key and item.program_key == item.external_key:
            raise ValueError(f"Um registo não se pode associar a si próprio: {item.external_key}")
        keys.add(item.external_key)
        items.append(item)

    missing_programs = sorted({item.program_key for item in items if item.program_key} - keys)
    if missing_programs:
        raise ValueError(f"Programas principais em falta: {', '.join(missing_programs)}")
    return items


def _values(item: CatalogItem) -> dict[str, str | None]:
    return {
        "record_type": item.record_type,
        "module": item.module,
        "title": item.title,
        "description": item.description,
        "origin": item.origin,
        "priority": item.priority,
        "status": item.status,
        "notes": item.notes,
        "reference_chat": item.reference_chat,
        "reference_branch": item.reference_branch,
        "reference_commit": item.reference_commit,
    }


def import_evolution_catalog(
    db: Session,
    items: list[CatalogItem],
    *,
    apply: bool = False,
) -> ImportReport:
    events: list[ImportEvent] = []
    created = updated = ignored = 0

    for item in items:
        record = db.scalar(select(EvolutionRecord).where(EvolutionRecord.origin == item.origin))
        values = _values(item)
        if record is None:
            title_duplicate = db.scalar(
                select(EvolutionRecord).where(
                    EvolutionRecord.module == item.module,
                    func.lower(EvolutionRecord.title) == item.title.lower(),
                )
            )
            reference_duplicate = None
            if item.reference_commit:
                reference_duplicate = db.scalar(
                    select(EvolutionRecord).where(
                        EvolutionRecord.reference_commit == item.reference_commit,
                        func.lower(EvolutionRecord.title) == item.title.lower(),
                    )
                )
            if reference_duplicate is None and item.reference_chat:
                reference_duplicate = db.scalar(
                    select(EvolutionRecord).where(
                        EvolutionRecord.reference_chat == item.reference_chat,
                        func.lower(EvolutionRecord.title) == item.title.lower(),
                    )
                )
            duplicate = reference_duplicate or title_duplicate
            if duplicate is not None:
                ignored += 1
                events.append(
                    ImportEvent(
                        item.external_key,
                        "ignored",
                        "duplicado não gerido pelo catálogo (título/commit/task)",
                        duplicate.id,
                    )
                )
                continue
            created += 1
            if apply:
                record = EvolutionRecord(**values)
                db.add(record)
                db.flush()
            events.append(
                ImportEvent(
                    item.external_key,
                    "created",
                    "novo registo",
                    record.id if record is not None else None,
                )
            )
            continue

        changes = {
            field: (getattr(record, field), value)
            for field, value in values.items()
            if getattr(record, field) != value
        }
        if not changes:
            ignored += 1
            events.append(ImportEvent(item.external_key, "ignored", "sem alterações", record.id))
            continue

        updated += 1
        if apply:
            for field, (old_value, new_value) in changes.items():
                setattr(record, field, new_value)
                db.add(
                    EvolutionRecordHistory(
                        record_id=record.id,
                        user_id=None,
                        field_name=field,
                        old_value=None if old_value is None else str(old_value),
                        new_value=None if new_value is None else str(new_value),
                    )
                )
            db.flush()
        events.append(
            ImportEvent(
                item.external_key,
                "updated",
                f"campos alterados: {', '.join(sorted(changes))}",
                record.id,
            )
        )

    return ImportReport(not apply, created, updated, ignored, events)
