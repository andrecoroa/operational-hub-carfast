from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.documents import (
    Document,
    DocumentEvent,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.services.audit import record_audit
from app.services.vehicle_document_history import (
    DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS,
    add_quick_classification,
)

SERVICE_CATEGORIES = ("maintenance", "pads", "discs", "tyres", "ipo", "other")


def _normalized_values(category: str, values: list[str]) -> list[str]:
    allowed = {code for code, _label in DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS[category]}
    cleaned = list(dict.fromkeys(value.strip() for value in values if value and value.strip()))
    invalid = [value for value in cleaned if value not in allowed]
    if invalid:
        raise ValueError(f"invalid_service:{category}:{invalid[0]}")
    if len(cleaned) > 1 and "undefined" in cleaned:
        cleaned.remove("undefined")
    return cleaned


def _custom_values(value: str) -> list[str]:
    return list(
        dict.fromkeys(
            item.strip()[:240] for item in re.split(r"[,;\n]+", value or "") if item.strip()
        )
    )


def _tag_snapshot(tags: list[VehicleDocumentRecordTag]) -> list[dict[str, str | None]]:
    return [
        {
            "category": tag.category,
            "value": tag.value,
            "free_text": tag.free_text,
            "source_kind": tag.source_kind,
        }
        for tag in tags
    ]


def service_classification_snapshot(
    db: Session,
    *,
    vehicle_id: int,
    record_id: int | None = None,
    document_id: int | None = None,
) -> list[dict[str, str | None]]:
    conditions: list[Any] = [VehicleDocumentRecordTag.vehicle_id == vehicle_id]
    if record_id is not None:
        conditions.append(VehicleDocumentRecordTag.record_id == record_id)
    elif document_id is not None:
        conditions.append(VehicleDocumentRecordTag.document_id == document_id)
    else:
        raise ValueError("service_target_required")
    tags = db.scalars(
        select(VehicleDocumentRecordTag)
        .where(*conditions)
        .where(VehicleDocumentRecordTag.category.in_(SERVICE_CATEGORIES))
        .order_by(VehicleDocumentRecordTag.id.asc())
    ).all()
    return _tag_snapshot(list(tags))


def save_service_classifications(
    db: Session,
    *,
    vehicle_id: int,
    values_by_category: dict[str, list[str]],
    other_custom: str,
    user_id: int | None,
    record_id: int | None = None,
    document_id: int | None = None,
    manual_note: str | None = None,
) -> list[dict[str, str | None]]:
    """Replace the shared service tags without changing workflow decisions.

    Both the vehicle file and the central treatment preview call this operation.
    The tags remain the only current projection of the service classifier.
    """

    if bool(record_id) == bool(document_id):
        raise ValueError("single_service_target_required")
    if set(values_by_category) - set(SERVICE_CATEGORIES):
        raise ValueError("invalid_service_category")

    document: Document | None = None
    record: VehicleDocumentRecord | None = None
    if document_id:
        document = db.get(Document, document_id)
        if not document or document.vehicle_id != vehicle_id:
            raise ValueError("vehicle_required_for_services")
    else:
        record = db.get(VehicleDocumentRecord, record_id)
        if not record or record.vehicle_id != vehicle_id:
            raise ValueError("vehicle_required_for_services")

    normalized = {
        category: _normalized_values(category, list(values_by_category.get(category, [])))
        for category in SERVICE_CATEGORIES
    }
    custom_values = _custom_values(other_custom)
    before = service_classification_snapshot(
        db,
        vehicle_id=vehicle_id,
        record_id=record_id,
        document_id=document_id,
    )

    target_condition = (
        VehicleDocumentRecordTag.record_id == record_id
        if record_id
        else VehicleDocumentRecordTag.document_id == document_id
    )
    db.execute(
        delete(VehicleDocumentRecordTag).where(
            VehicleDocumentRecordTag.vehicle_id == vehicle_id,
            target_condition,
            VehicleDocumentRecordTag.category.in_(SERVICE_CATEGORIES),
        )
    )
    for category, values in normalized.items():
        for value in values:
            add_quick_classification(
                db,
                vehicle_id=vehicle_id,
                record_id=record_id,
                document_id=document_id,
                category=category,
                value=value,
                free_text=None,
                user_id=user_id,
            )
    for free_text in custom_values:
        add_quick_classification(
            db,
            vehicle_id=vehicle_id,
            record_id=record_id,
            document_id=document_id,
            category="other",
            value=None,
            free_text=free_text,
            user_id=user_id,
        )

    if record is not None and manual_note is not None:
        record.metadata_json = {
            **(record.metadata_json if isinstance(record.metadata_json, dict) else {}),
            "manual_note": manual_note.strip(),
        }
        record.updated_by_id = user_id
    after = service_classification_snapshot(
        db,
        vehicle_id=vehicle_id,
        record_id=record_id,
        document_id=document_id,
    )
    entity_type = "document" if document is not None else "vehicle_document_record"
    entity_id = document.id if document is not None else record.id
    if document is not None:
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="document.services.saved",
                old_value=json.dumps(before, ensure_ascii=False),
                new_value=json.dumps(after, ensure_ascii=False),
                user_id=user_id,
            )
        )
    record_audit(
        db,
        action="document.services.saved",
        entity_type=entity_type,
        entity_id=entity_id,
        before_json={"services": before},
        after_json={"services": after},
        detail="Classificador comum de serviços atualizado.",
        user_id=user_id,
    )
    return after
