"""Read-only documentary evidence for historical workshop printouts.

Comparable invoices are context, never proof of materials used in the current
intervention. Work-order lines are displayed verbatim with their own quantities.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import VehicleDocumentRecord, VehicleDocumentRecordTag
from app.models.workshop_phased import WorkshopPhasedProcess


def historical_workshop_document_evidence(
    db: Session,
    process: WorkshopPhasedProcess,
    *,
    intervention_date: str,
    service_type: str,
) -> dict[str, object]:
    empty: dict[str, object] = {"work_order": None, "work_order_lines": [], "equivalent_invoices": []}
    if process.creation_mode != "historical" or not process.vehicle_id:
        return empty
    try:
        on_date = date.fromisoformat(intervention_date)
    except ValueError:
        return empty

    work_orders = db.scalars(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == process.vehicle_id,
            VehicleDocumentRecord.main_group == "work_orders",
            VehicleDocumentRecord.document_date == on_date,
        )
    ).all()
    # An ambiguous date must not silently bind another intervention's FO.
    work_order = work_orders[0] if len(work_orders) == 1 else None
    work_order_lines: list[dict[str, object]] = []
    if work_order and isinstance(work_order.metadata_json, dict):
        raw_lines = work_order.metadata_json.get("work_order_lines")
        if isinstance(raw_lines, list):
            for item in raw_lines:
                if not isinstance(item, dict):
                    continue
                work_order_lines.append(
                    {
                        "description": str(item.get("description") or "-"),
                        "reference": str(item.get("reference") or "-"),
                        "quantity": str(item.get("quantity") if item.get("quantity") not in (None, "") else "-"),
                    }
                )

    normalized_type = service_type.casefold()
    service_code = (
        "degradation" if "degrada" in normalized_type
        else "revision" if "revis" in normalized_type
        else None
    )
    equivalent_invoices: list[dict[str, object]] = []
    if service_code:
        invoices = db.scalars(
            select(VehicleDocumentRecord)
            .join(VehicleDocumentRecordTag, VehicleDocumentRecordTag.record_id == VehicleDocumentRecord.id)
            .where(
                VehicleDocumentRecord.vehicle_id == process.vehicle_id,
                VehicleDocumentRecord.main_group == "invoices",
                VehicleDocumentRecord.document_date < on_date,
                VehicleDocumentRecordTag.category == "maintenance",
                VehicleDocumentRecordTag.value == service_code,
            )
            .distinct()
            .order_by(VehicleDocumentRecord.document_date.desc(), VehicleDocumentRecord.id.desc())
            .limit(4)
        ).all()
        for invoice in invoices:
            metadata = invoice.metadata_json if isinstance(invoice.metadata_json, dict) else {}
            lines = metadata.get("invoice_lines") or metadata.get("lines") or []
            equivalent_invoices.append(
                {
                    "date": invoice.document_date.strftime("%d/%m/%Y"),
                    "reference": invoice.external_reference or invoice.title or f"Registo #{invoice.id}",
                    "supplier": invoice.supplier_name or "-",
                    "document_id": invoice.document_id,
                    "line_count": len(lines) if isinstance(lines, list) else 0,
                }
            )

    return {
        "work_order": work_order,
        "work_order_lines": work_order_lines,
        "equivalent_invoices": equivalent_invoices,
    }
