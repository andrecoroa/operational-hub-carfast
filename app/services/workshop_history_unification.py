from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.models.workshop_phased import (
    WorkshopPhasedProcess,
    WorkshopProcessSourceLink,
)

GLOBAL_REFERENCE_PREFIX = "OF"
GLOBAL_REFERENCE_DIGITS = 6


def normalize_workshop_reference(value: str) -> str:
    """Normalize a reference for lookup without losing its displayed spelling."""

    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def format_unified_workshop_reference(sequence: int) -> str:
    if sequence < 1:
        raise ValueError("A sequência global da Oficina deve ser positiva.")
    return f"{GLOBAL_REFERENCE_PREFIX}-{sequence:0{GLOBAL_REFERENCE_DIGITS}d}"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _legacy_opened_at(process: WorkshopProcess) -> tuple[datetime, list[str]]:
    issues: list[str] = []
    if process.opened_on:
        return datetime.combine(process.opened_on, time.min, tzinfo=UTC), issues
    if process.created_at:
        issues.append("missing_opened_on_used_created_at")
        return _aware(process.created_at), issues
    issues.append("missing_opened_date")
    return datetime.max.replace(tzinfo=UTC), issues


def _phased_opened_at(process: WorkshopPhasedProcess) -> tuple[datetime, list[str]]:
    issues: list[str] = []
    moment = process.opened_at or process.received_at or process.created_at
    if process.opened_at is None:
        issues.append("missing_opened_at_used_fallback")
    if moment is None:
        issues.append("missing_opened_date")
        return datetime.max.replace(tzinfo=UTC), issues
    return _aware(moment), issues


def _legacy_reference(process: WorkshopProcess, opened_at: datetime) -> str:
    return f"OFI-{opened_at.year}-{process.id:06d}"


def _legacy_proposed_status(process: WorkshopProcess) -> tuple[str, list[str]]:
    status = str(process.status or "").strip().casefold()
    if status in {"cancelled", "canceled", "cancelado", "anulado"}:
        return "cancelled", []
    if status in {"closed", "fechado", "completed", "complete", "concluido", "concluído"}:
        return "closed", []
    return "closed", ["legacy_non_terminal_status_requires_review"]


@dataclass
class WorkshopHistoryPlanItem:
    sequence: int | None
    canonical_reference: str | None
    target_process_id: int | None
    event_at: datetime
    vehicle_id: int | None
    plate: str | None
    title: str
    original_status: str
    proposed_status: str
    plan_operation: str
    source_records: list[str] = field(default_factory=list)
    legacy_references: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    existing_sequence: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["event_at"] = self.event_at.isoformat()
        payload["source_records"] = list(self.source_records)
        payload["legacy_references"] = list(dict.fromkeys(self.legacy_references))
        payload["issues"] = sorted(set(self.issues))
        return payload


@dataclass
class WorkshopHistoryPlan:
    items: list[WorkshopHistoryPlanItem]
    summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "write_operations": 0,
            "numbering_format": format_unified_workshop_reference(1),
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
        }


def build_workshop_history_unification_plan(
    db: Session,
    *,
    start_at: int = 1,
) -> WorkshopHistoryPlan:
    """Build a deterministic, read-only plan for unifying old and phased processes."""

    if start_at < 1:
        raise ValueError("start_at deve ser positivo.")

    vehicles = {vehicle.id: vehicle for vehicle in db.scalars(select(Vehicle)).all()}
    phased_processes = list(
        db.scalars(select(WorkshopPhasedProcess).order_by(WorkshopPhasedProcess.id)).all()
    )
    legacy_processes = list(db.scalars(select(WorkshopProcess).order_by(WorkshopProcess.id)).all())
    source_links = list(db.scalars(select(WorkshopProcessSourceLink)).all())
    legacy_links = {
        link.source_entity_id: link
        for link in source_links
        if link.source_system == "carfast_legacy" and link.source_entity_type == "workshop_process"
    }

    items_by_target: dict[int, WorkshopHistoryPlanItem] = {}
    plan_items: list[WorkshopHistoryPlanItem] = []

    for process in phased_processes:
        event_at, issues = _phased_opened_at(process)
        vehicle = vehicles.get(process.vehicle_id)
        reference = process.public_reference or f"OFI-{event_at.year}-{process.id:06d}"
        item = WorkshopHistoryPlanItem(
            sequence=None,
            canonical_reference=None,
            target_process_id=process.id,
            event_at=event_at,
            vehicle_id=process.vehicle_id,
            plate=process.plate_snapshot or (vehicle.plate if vehicle else None),
            title=process.title,
            original_status=process.status,
            proposed_status=process.status,
            plan_operation=(
                "keep_canonical" if process.canonical_sequence else "renumber_existing"
            ),
            source_records=[f"workshop_phased_process:{process.id}"],
            legacy_references=[reference],
            issues=issues,
            existing_sequence=process.canonical_sequence,
        )
        if not process.vehicle_id:
            item.issues.append("missing_vehicle")
        plan_items.append(item)
        items_by_target[process.id] = item

    for process in legacy_processes:
        event_at, issues = _legacy_opened_at(process)
        proposed_status, status_issues = _legacy_proposed_status(process)
        issues.extend(status_issues)
        reference = _legacy_reference(process, event_at)
        link = legacy_links.get(str(process.id))
        if link and link.process_id in items_by_target:
            linked = items_by_target[link.process_id]
            linked.source_records.append(f"workshop_process:{process.id}")
            linked.legacy_references.extend(
                value for value in (link.source_reference, reference) if value
            )
            linked.issues.extend(issues)
            continue

        vehicle = vehicles.get(process.vehicle_id)
        item = WorkshopHistoryPlanItem(
            sequence=None,
            canonical_reference=None,
            target_process_id=None,
            event_at=event_at,
            vehicle_id=process.vehicle_id,
            plate=vehicle.plate if vehicle else None,
            title=process.title,
            original_status=process.status,
            proposed_status=proposed_status,
            plan_operation="create_historical",
            source_records=[f"workshop_process:{process.id}"],
            legacy_references=[reference],
            issues=issues,
        )
        if not vehicle:
            item.issues.append("missing_vehicle")
        plan_items.append(item)

    # Same vehicle and calendar date is a useful review signal, but never an
    # automatic merge rule: a vehicle may legitimately have two interventions.
    possible_duplicates: dict[tuple[int, date], list[WorkshopHistoryPlanItem]] = {}
    for item in plan_items:
        if item.vehicle_id is None or item.event_at == datetime.max.replace(tzinfo=UTC):
            continue
        possible_duplicates.setdefault((item.vehicle_id, item.event_at.date()), []).append(item)
    for group in possible_duplicates.values():
        if len(group) < 2:
            continue
        if not any(
            source.startswith("workshop_process:")
            for item in group
            for source in item.source_records
        ):
            continue
        for item in group:
            item.issues.append("possible_duplicate_same_vehicle_and_date")
            if item.plan_operation == "create_historical":
                item.plan_operation = "review_before_import"

    plan_items.sort(
        key=lambda item: (
            item.event_at,
            item.source_records[0] if item.source_records else "",
            item.target_process_id or 0,
        )
    )

    used_sequences: set[int] = set()
    for item in plan_items:
        if item.existing_sequence is None:
            continue
        if item.existing_sequence in used_sequences:
            item.issues.append("duplicate_existing_canonical_sequence")
            continue
        used_sequences.add(item.existing_sequence)
        item.sequence = item.existing_sequence
        item.canonical_reference = format_unified_workshop_reference(item.sequence)

    next_sequence = start_at
    for item in plan_items:
        if item.sequence is not None:
            continue
        while next_sequence in used_sequences:
            next_sequence += 1
        item.sequence = next_sequence
        item.canonical_reference = format_unified_workshop_reference(next_sequence)
        used_sequences.add(next_sequence)
        next_sequence += 1

    summary = {
        "phased_records": len(phased_processes),
        "legacy_records": len(legacy_processes),
        "logical_processes": len(plan_items),
        "existing_links": len(legacy_processes)
        - sum(
            1
            for item in plan_items
            if any(source.startswith("workshop_process:") for source in item.source_records)
            and item.target_process_id is None
        ),
        "to_create": sum(item.target_process_id is None for item in plan_items),
        "to_renumber": sum(item.plan_operation == "renumber_existing" for item in plan_items),
        "review_required": sum(bool(item.issues) for item in plan_items),
        "possible_duplicates": sum(
            "possible_duplicate_same_vehicle_and_date" in item.issues for item in plan_items
        ),
    }
    return WorkshopHistoryPlan(items=plan_items, summary=summary)
