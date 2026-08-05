from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.documents import (
    Document,
    DocumentLink,
    DocumentWorkflowState,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.models.vehicles import Vehicle
from app.services.vehicle_document_history import (
    DOCUMENT_HISTORY_QUICK_CLASSIFICATION_LABELS,
    DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS,
)

INVOICE_TYPES = {"workshop_supplier_invoice", "finance_supplier_invoice"}


def _vehicle_map(db: Session, vehicle_ids: set[int]) -> dict[int, Vehicle]:
    if not vehicle_ids:
        return {}
    return {
        vehicle.id: vehicle
        for vehicle in db.scalars(select(Vehicle).where(Vehicle.id.in_(vehicle_ids))).all()
    }


def vehicles_with_pending_invoices(db: Session) -> list[dict[str, Any]]:
    actual = {
        int(vehicle_id): int(count)
        for vehicle_id, count in db.execute(
            select(Document.vehicle_id, func.count())
            .outerjoin(
                DocumentWorkflowState,
                DocumentWorkflowState.document_id == Document.id,
            )
            .where(
                Document.vehicle_id.is_not(None),
                Document.document_type.in_(INVOICE_TYPES),
                ~Document.status.in_({"classified", "archived", "removed", "deleted"}),
            )
            .group_by(Document.vehicle_id)
        ).all()
    }
    expected = {
        int(vehicle_id): int(count)
        for vehicle_id, count in db.execute(
            select(VehicleDocumentRecord.vehicle_id, func.count())
            .where(
                VehicleDocumentRecord.vehicle_id.is_not(None),
                VehicleDocumentRecord.source_record_type == "pending_import",
                VehicleDocumentRecord.main_group == "invoices",
                VehicleDocumentRecord.status == "pending",
            )
            .group_by(VehicleDocumentRecord.vehicle_id)
        ).all()
    }
    vehicle_ids = set(actual) | set(expected)
    vehicles = _vehicle_map(db, vehicle_ids)
    rows = [
        {
            "vehicle": vehicles.get(vehicle_id),
            "vehicle_id": vehicle_id,
            "actual_pending": actual.get(vehicle_id, 0),
            "expected_pending": expected.get(vehicle_id, 0),
            "total": actual.get(vehicle_id, 0) + expected.get(vehicle_id, 0),
        }
        for vehicle_id in vehicle_ids
        if vehicles.get(vehicle_id)
    ]
    rows.sort(key=lambda row: (-row["total"], row["vehicle"].plate or "", row["vehicle_id"]))
    return rows


def vehicle_work_order_invoice_divergence(db: Session) -> list[dict[str, Any]]:
    work_orders = {
        int(vehicle_id): int(count)
        for vehicle_id, count in db.execute(
            select(VehicleDocumentRecord.vehicle_id, func.count())
            .where(
                VehicleDocumentRecord.vehicle_id.is_not(None),
                VehicleDocumentRecord.main_group == "work_orders",
                ~VehicleDocumentRecord.status.in_({"removed", "deleted"}),
            )
            .group_by(VehicleDocumentRecord.vehicle_id)
        ).all()
    }
    invoices = {
        int(vehicle_id): int(count)
        for vehicle_id, count in db.execute(
            select(Document.vehicle_id, func.count())
            .where(
                Document.vehicle_id.is_not(None),
                Document.document_type.in_(INVOICE_TYPES),
                ~Document.status.in_({"removed", "deleted"}),
            )
            .group_by(Document.vehicle_id)
        ).all()
    }
    confirmed = {
        int(vehicle_id): int(count)
        for vehicle_id, count in db.execute(
            select(Document.vehicle_id, func.count(func.distinct(DocumentLink.document_id)))
            .join(DocumentLink, DocumentLink.document_id == Document.id)
            .where(
                Document.vehicle_id.is_not(None),
                DocumentLink.entity_type == "vehicle_document_record",
                DocumentLink.category == "invoice_work_order",
            )
            .group_by(Document.vehicle_id)
        ).all()
    }
    vehicle_ids = set(work_orders) | set(invoices)
    vehicles = _vehicle_map(db, vehicle_ids)
    rows: list[dict[str, Any]] = []
    for vehicle_id in vehicle_ids:
        work_order_count = work_orders.get(vehicle_id, 0)
        invoice_count = invoices.get(vehicle_id, 0)
        confirmed_count = min(confirmed.get(vehicle_id, 0), work_order_count, invoice_count)
        suggested_count = max(min(work_order_count, invoice_count) - confirmed_count, 0)
        paired = confirmed_count + suggested_count
        fo_without_invoice = max(work_order_count - paired, 0)
        invoice_without_fo = max(invoice_count - paired, 0)
        rows.append(
            {
                "vehicle": vehicles.get(vehicle_id),
                "vehicle_id": vehicle_id,
                "work_orders": work_order_count,
                "invoices": invoice_count,
                "confirmed_pairs": confirmed_count,
                "suggested_pairs": suggested_count,
                "fo_without_invoice": fo_without_invoice,
                "invoice_without_fo": invoice_without_fo,
                "divergence": fo_without_invoice + invoice_without_fo,
            }
        )
    rows = [row for row in rows if row["vehicle"]]
    rows.sort(
        key=lambda row: (
            -row["divergence"],
            -abs(row["work_orders"] - row["invoices"]),
            row["vehicle"].plate or "",
        )
    )
    return rows


def _service_label(category: str, value: str | None, free_text: str | None) -> str:
    category_label = DOCUMENT_HISTORY_QUICK_CLASSIFICATION_LABELS.get(category, category)
    if free_text:
        return f"{category_label}: {free_text}"
    value_label = dict(DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS.get(category, [])).get(
        value or "",
        value or "Por definir",
    )
    return f"{category_label}: {value_label}"


def repeated_vehicle_services(db: Session, *, maximum_tags: int = 5000) -> list[dict[str, Any]]:
    tags = db.scalars(
        select(VehicleDocumentRecordTag)
        .where(
            VehicleDocumentRecordTag.vehicle_id.is_not(None),
            or_(
                VehicleDocumentRecordTag.value.is_not(None),
                VehicleDocumentRecordTag.free_text.is_not(None),
            ),
        )
        .order_by(VehicleDocumentRecordTag.id.desc())
        .limit(maximum_tags)
    ).all()
    document_ids = {tag.document_id for tag in tags if tag.document_id}
    record_ids = {tag.record_id for tag in tags if tag.record_id}
    document_dates = (
        {
            document_id: document_date
            for document_id, document_date in db.execute(
                select(Document.id, Document.document_date).where(Document.id.in_(document_ids))
            ).all()
        }
        if document_ids
        else {}
    )
    record_dates = (
        {
            record_id: document_date
            for record_id, document_date in db.execute(
                select(VehicleDocumentRecord.id, VehicleDocumentRecord.document_date).where(
                    VehicleDocumentRecord.id.in_(record_ids)
                )
            ).all()
        }
        if record_ids
        else {}
    )
    grouped: dict[tuple[int, str, str, str], list[date]] = defaultdict(list)
    for tag in tags:
        occurred_on = document_dates.get(tag.document_id) or record_dates.get(tag.record_id)
        if not occurred_on:
            continue
        signature = (tag.vehicle_id, tag.category, tag.value or "", tag.free_text or "")
        grouped[signature].append(occurred_on)
    vehicle_ids = {key[0] for key, dates in grouped.items() if len(set(dates)) >= 2}
    vehicles = _vehicle_map(db, vehicle_ids)
    rows: list[dict[str, Any]] = []
    for (vehicle_id, category, value, free_text), raw_dates in grouped.items():
        dates = sorted(set(raw_dates))
        if len(dates) < 2 or vehicle_id not in vehicles:
            continue
        gaps = [(right - left).days for left, right in zip(dates, dates[1:], strict=False)]
        minimum_gap = min(gaps)
        interval = (
            "≤ 30 dias"
            if minimum_gap <= 30
            else "≤ 60 dias"
            if minimum_gap <= 60
            else "≤ 90 dias"
            if minimum_gap <= 90
            else "> 90 dias"
        )
        rows.append(
            {
                "vehicle": vehicles[vehicle_id],
                "vehicle_id": vehicle_id,
                "service": _service_label(category, value, free_text),
                "occurrences": len(dates),
                "minimum_gap_days": minimum_gap,
                "interval": interval,
                "first_date": dates[0],
                "last_date": dates[-1],
            }
        )
    rows.sort(
        key=lambda row: (
            row["minimum_gap_days"],
            -row["occurrences"],
            row["vehicle"].plate or "",
            row["service"],
        )
    )
    return rows


def documentation_by_vehicle_overview(db: Session) -> dict[str, list[dict[str, Any]]]:
    return {
        "pending_invoices": vehicles_with_pending_invoices(db),
        "divergence": vehicle_work_order_invoice_divergence(db),
        "repeated_services": repeated_vehicle_services(db),
    }
