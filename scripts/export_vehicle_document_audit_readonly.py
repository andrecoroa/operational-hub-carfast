from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.models.documents import (
    DiagnosticDocument,
    DiagnosticExtraction,
    Document,
    DocumentWorkflowState,
    VehicleDocumentRecord,
)
from app.services.document_workflow import legacy_workflow_values


INVOICE_TYPES = {"workshop_supplier_invoice", "finance_supplier_invoice"}
CASE_COLUMNS = (
    "document_id",
    "document_type",
    "classification",
    "legacy_status",
    "ingestion_status",
    "association_status",
    "extraction_status",
    "validation_status",
    "destination_status",
    "ocr_status",
    "workflow_state_missing",
    "ocr_not_requested",
    "ocr_pending",
    "ocr_failed",
    "extraction_incomplete",
    "extracted_not_applied",
    "file_locator_missing",
    "local_file_missing",
    "remote_file_unverified",
    "vehicle_unassociated",
    "record_unassociated",
)


def _populated(value: Any) -> bool:
    return value not in (None, "", [], {})


def _latest_extractions(db, diagnostic_ids: set[int]) -> dict[int, DiagnosticExtraction]:
    if not diagnostic_ids:
        return {}
    rows = db.scalars(
        select(DiagnosticExtraction)
        .where(DiagnosticExtraction.diagnostic_document_id.in_(diagnostic_ids))
        .order_by(DiagnosticExtraction.id)
    ).all()
    return {row.diagnostic_document_id: row for row in rows}


def build_vehicle_document_audit(db, *, verify_local_files: bool = False) -> tuple[dict, list[dict]]:
    documents = db.scalars(
        select(Document).where(Document.document_type.not_in(INVOICE_TYPES))
    ).all()
    states = {
        row.document_id: row
        for row in db.scalars(select(DocumentWorkflowState)).all()
    }
    diagnostics = {
        row.document_id: row for row in db.scalars(select(DiagnosticDocument)).all()
    }
    latest = _latest_extractions(db, {row.id for row in diagnostics.values()})
    record_document_ids = {
        row.document_id
        for row in db.scalars(select(VehicleDocumentRecord)).all()
        if row.document_id is not None and row.vehicle_id is not None
    }

    cases: list[dict] = []
    for document in documents:
        state = states.get(document.id)
        workflow = legacy_workflow_values(document)
        if state:
            workflow.update(
                {key: getattr(state, key) for key in (
                    "ingestion_status", "association_status", "extraction_status",
                    "validation_status", "destination_status",
                )}
            )
        diagnostic = diagnostics.get(document.id)
        extraction = latest.get(diagnostic.id) if diagnostic else None
        ocr_status = (diagnostic.ocr_status if diagnostic else None) or "not_applicable"
        extraction_status = workflow["extraction_status"]
        normalized = extraction.normalized_data_json if extraction else None
        extracted_has_values = isinstance(normalized, dict) and any(_populated(v) for v in normalized.values())
        applied_has_values = bool(
            diagnostic
            and any(
                _populated(value)
                for value in (
                    diagnostic.report_number,
                    diagnostic.odometer_km,
                    diagnostic.report_datetime,
                    diagnostic.detected_plate,
                    diagnostic.detected_vin,
                )
            )
        )
        locator_missing = not any((document.storage_path, document.storage_key, document.external_url))
        local_missing = False
        if verify_local_files and document.storage_provider == "local" and document.storage_path:
            local_missing = not Path(document.storage_path).is_file()
        remote_unverified = document.storage_provider != "local" and not locator_missing
        case = {
            "document_id": document.id,
            "document_type": document.document_type or "",
            "classification": document.classification or "",
            "legacy_status": document.status or "",
            "ingestion_status": workflow["ingestion_status"],
            "association_status": workflow["association_status"],
            "extraction_status": extraction_status,
            "validation_status": workflow["validation_status"],
            "destination_status": workflow["destination_status"],
            "ocr_status": ocr_status,
            "workflow_state_missing": state is None,
            "ocr_not_requested": bool(diagnostic and ocr_status == "not_requested"),
            "ocr_pending": bool(diagnostic and ocr_status in {"queued", "processing"}),
            "ocr_failed": bool(diagnostic and ocr_status in {"failed", "error", "needs_review"}),
            "extraction_incomplete": bool(
                diagnostic
                and extraction_status == "extracted"
                and (not extraction or not extracted_has_values)
            ),
            "extracted_not_applied": bool(extracted_has_values and not applied_has_values),
            "file_locator_missing": locator_missing,
            "local_file_missing": local_missing,
            "remote_file_unverified": remote_unverified,
            "vehicle_unassociated": document.vehicle_id is None or workflow["association_status"] != "associated",
            "record_unassociated": document.id not in record_document_ids,
        }
        cases.append(case)

    flag_counts = Counter()
    type_counts = Counter()
    extraction_counts = Counter()
    for case in cases:
        type_counts[case["document_type"] or "unknown"] += 1
        extraction_counts[case["extraction_status"]] += 1
        for column in CASE_COLUMNS[10:]:
            if case[column]:
                flag_counts[column] += 1
    summary = {
        "contract_version": "vehicle-document-audit-readonly/1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only",
        "scope": "non_invoice_documents",
        "documents": len(cases),
        "by_document_type": dict(sorted(type_counts.items())),
        "by_extraction_status": dict(sorted(extraction_counts.items())),
        "flags": dict(sorted(flag_counts.items())),
        "database_writes": 0,
    }
    return summary, cases


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoria documental sem escrita na base de dados.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--verify-local-files", action="store_true")
    args = parser.parse_args()
    with SessionLocal() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        summary, cases = build_vehicle_document_audit(
            db, verify_local_files=args.verify_local_files
        )
        db.rollback()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    cases_path = args.output_dir / "cases.csv"
    with cases_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CASE_COLUMNS, delimiter=";")
        writer.writeheader()
        writer.writerows(cases)
    summary_path = args.output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = {
        "contract_version": summary["contract_version"],
        "mode": "read_only",
        "database_writes": 0,
        "files": {"cases.csv": _sha256(cases_path), "summary.json": _sha256(summary_path)},
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
