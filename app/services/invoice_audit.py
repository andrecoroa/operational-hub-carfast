from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.documents import (
    Document,
    DocumentEvent,
    DocumentWorkflowState,
    VehicleDocumentRecordTag,
)
from app.services.invoice_service_classifier import classify_invoice_service_text


AUDIT_SCHEMA = "carfast.invoice-audit-dry-run.v1"
SUPPORTED_EXTRACTION_ACTIONS = frozenset(
    {
        "invoice.ocr.extracted",
        "invoice.ocr.reprocessed",
        "invoice.lines.extracted",
        "invoice.extracted",
        "document.ocr.extracted",
        "ocr.extracted",
    }
)
TECHNICAL_DOCUMENT_TYPES = frozenset(
    {"workshop_supplier_invoice", "workshop_report"}
)
CONTROL_DOCUMENT_TYPES = frozenset(
    {"finance_supplier_invoice", "stock_supplier_invoice"}
)
AUDIT_DOCUMENT_TYPES = TECHNICAL_DOCUMENT_TYPES | CONTROL_DOCUMENT_TYPES


def _archive_root() -> Path:
    configured = str(settings.document_archive_root or "").strip()
    root = Path(configured).expanduser() if configured else Path(__file__).resolve().parents[2] / "uploads" / "documents"
    if not root.is_absolute():
        root = Path(__file__).resolve().parents[2] / root
    return root.resolve()


def _resolve_document_file(document: Document, root: Path) -> Path | None:
    raw_path = str(document.storage_path or "").strip()
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_file() else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _event_payloads(db: Session, document_ids: list[int]) -> dict[int, dict[str, Any]]:
    payloads: dict[int, dict[str, Any]] = {}
    if not document_ids:
        return payloads
    events = db.scalars(
        select(DocumentEvent)
        .where(
            DocumentEvent.document_id.in_(document_ids),
            DocumentEvent.action.in_(SUPPORTED_EXTRACTION_ACTIONS),
        )
        .order_by(DocumentEvent.id)
    ).all()
    for event in events:
        try:
            value = json.loads(event.new_value or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(value, list):
            value = {"invoice_lines": value}
        if isinstance(value, dict):
            payloads.setdefault(event.document_id, {}).update(value)
    return payloads


def _invoice_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_lines = (
        payload.get("invoice_lines")
        or payload.get("line_items")
        or payload.get("lines")
        or payload.get("items")
        or []
    )
    if not isinstance(raw_lines, list):
        return []
    return [line if isinstance(line, dict) else {"description": str(line)} for line in raw_lines]


def _scope(document: Document, state: DocumentWorkflowState | None) -> tuple[str, str]:
    nature = str(state.invoice_nature or "").strip().lower() if state else ""
    document_type = str(document.document_type or "").strip().lower()
    source = str(document.source or "").strip().lower()
    if nature == "stock" or source == "stock_direct_import" or "stock" in document_type:
        return "excluded", "stock"
    if nature == "financeira" or document_type == "finance_supplier_invoice":
        return "excluded", "financial"
    if document_type == "workshop_supplier_invoice":
        return "technical", "operational_invoice"
    if document_type == "workshop_report":
        return "technical", "workshop_report"
    return "review", "nature_unconfirmed"


def build_invoice_audit_dry_run(
    db: Session,
    *,
    verify_files: bool = True,
    hash_files: bool = False,
) -> dict[str, Any]:
    """Inventory invoices and proposals using SELECTs and filesystem reads only."""

    documents = list(
        db.scalars(
            select(Document)
            .where(
                or_(
                    Document.document_type.in_(AUDIT_DOCUMENT_TYPES),
                    Document.source == "stock_direct_import",
                )
            )
            .order_by(Document.id)
        ).all()
    )
    document_ids = [document.id for document in documents]
    states = {
        state.document_id: state
        for state in db.scalars(
            select(DocumentWorkflowState).where(DocumentWorkflowState.document_id.in_(document_ids))
        ).all()
    } if document_ids else {}
    tags: dict[int, list[VehicleDocumentRecordTag]] = {}
    if document_ids:
        for tag in db.scalars(
            select(VehicleDocumentRecordTag).where(VehicleDocumentRecordTag.document_id.in_(document_ids))
        ).all():
            if tag.document_id:
                tags.setdefault(tag.document_id, []).append(tag)
    payloads = _event_payloads(db, document_ids)
    root = _archive_root()
    rows: list[dict[str, Any]] = []
    counters: Counter[str] = Counter()

    for document in documents:
        state = states.get(document.id)
        scope, scope_reason = _scope(document, state)
        lines = _invoice_lines(payloads.get(document.id, {}))
        line_text = " ".join(
            str(line.get("description") or line.get("descricao") or line.get("text") or "")
            for line in lines
        )
        source_text = " ".join(
            str(value)
            for value in (
                document.title,
                document.original_name,
                document.supplier_name,
                document.contract_number,
                document.reservation_number,
                line_text,
            )
            if value
        )
        proposal = classify_invoice_service_text(source_text)
        saved_tags = tags.get(document.id, [])
        human_locked = bool(state and state.human_confirmed) or any(
            tag.source_kind != "auto_suggested" for tag in saved_tags
        )
        path = _resolve_document_file(document, root) if verify_files else None
        file_state = "not_checked" if not verify_files else "present" if path else "missing"
        verified_hash = _sha256(path) if hash_files and path else None
        hash_matches = (
            None
            if not verified_hash or not document.file_hash
            else verified_hash.casefold() == document.file_hash.casefold()
        )
        blockers = list(proposal.blocked_reasons)
        if scope == "technical" and not lines:
            blockers.append("technical_invoice_without_lines")
        if verify_files and not path:
            blockers.append("physical_file_missing")
        if hash_matches is False:
            blockers.append("physical_file_hash_mismatch")
        if human_locked:
            blockers.append("human_classification_locked")
        extraction_status = (
            str(state.extraction_status) if state else str(document.status or "unknown")
        )
        if extraction_status in {"failed", "not_requested", "queued", "processing"}:
            blockers.append(f"extraction_{extraction_status}")
        unclassified_lines = sum(
            1
            for line in lines
            if str(line.get("service") or line.get("servico") or "").strip().casefold()
            in {"", "por classificar"}
        )
        counters[f"scope_{scope}"] += 1
        counters[f"scope_reason_{scope_reason}"] += 1
        counters[f"file_{file_state}"] += 1
        if not lines:
            counters["without_lines"] += 1
        if blockers:
            counters["with_blockers"] += 1
        counters["extracted_lines"] += len(lines)
        counters["unclassified_lines"] += unclassified_lines
        rows.append(
            {
                "document_id": document.id,
                "scope": scope,
                "scope_reason": scope_reason,
                "document_type": document.document_type,
                "source": document.source,
                "supplier": document.supplier_name,
                "original_name": document.original_name,
                "vehicle_id": document.vehicle_id,
                "plate": document.plate,
                "file_state": file_state,
                "stored_hash": document.file_hash,
                "verified_hash": verified_hash,
                "hash_matches": hash_matches,
                "extraction_status": extraction_status,
                "line_count": len(lines),
                "unclassified_line_count": unclassified_lines,
                "human_locked": human_locked,
                "saved_tags": [
                    {
                        "category": tag.category,
                        "value": tag.value,
                        "source_kind": tag.source_kind,
                    }
                    for tag in saved_tags
                ],
                "proposal": proposal.as_dict(),
                "blockers": list(dict.fromkeys(blockers)),
            }
        )

    return {
        "schema": AUDIT_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "read_only": True,
        "write_operations": 0,
        "archive_root": str(root),
        "summary": {"documents": len(rows), **dict(sorted(counters.items()))},
        "documents": rows,
    }
