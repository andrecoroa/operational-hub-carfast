from __future__ import annotations

import csv
import json

import pytest

from app.models.documents import Document
from app.models.vehicles import Vehicle
from app.services.invoice_service_history import preview_invoice_service_import
from scripts.package_invoice_service_import import (
    IMPORT_HEADERS,
    build_package,
    import_row,
    write_csv,
)


def write_source_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)


def inputs(tmp_path):
    documents = tmp_path / "documents.csv"
    legacy = tmp_path / "legacy.json"
    dry_run = tmp_path / "dry-run.json"
    write_source_csv(
        documents,
        [
            {"document_id": "10", "eligible_for_counting": "true"},
            {"document_id": "11", "eligible_for_counting": "true"},
        ],
    )
    legacy.write_text(
        json.dumps([{"document_id": 90, "eligible_for_counting": "false"}]),
        encoding="utf-8",
    )
    dry_run.write_text(
        json.dumps(
            {
                "schema": "carfast.invoice-service-remediation-dry-run.v2",
                "blocked_ledger": {"count": 1},
                "summary": {"eligible_documents": 2},
                "services": [
                    {
                        "stable_key": "x:10:1",
                        "vehicle_id": 7,
                        "document_id": 10,
                        "service_code": "BRAKE.PAD",
                        "service_text": "Pastilhas frente",
                        "service_date": "2025-01-02",
                        "amount": "42.00",
                        "source_line_ids": "10:1",
                    }
                ],
                "reconciliations": [
                    {
                        "document_id": 10,
                        "document_projection": "services_classified",
                        "reconciliation_status": "reconciled",
                        "classification_blockers": "",
                    },
                    {
                        "document_id": 11,
                        "document_projection": "services_review_required",
                        "reconciliation_status": "divergent",
                        "classification_blockers": "unexplained_invoice_total_mismatch",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return dry_run, documents, legacy


def test_builds_guarded_pending_batches_and_full_review_queue(tmp_path):
    dry_run, documents, legacy = inputs(tmp_path)
    output = tmp_path / "output"

    manifest = build_package(dry_run, documents, legacy, output)

    assert manifest["proposal_rows"] == 1
    assert manifest["review_documents"] == 1
    assert manifest["technically_classifiable_documents"] == 1
    assert manifest["blocked_rows"] == 1
    with (output / "per_vehicle" / "vehicle_7.csv").open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    assert rows[0]["status"] == "pending_validation"
    assert rows[0]["service_text"] == "Pastilhas frente"
    assert rows[0]["amount"] == "42.00"
    with (output / "review_queue.csv").open(encoding="utf-8-sig") as handle:
        review = list(csv.DictReader(handle, delimiter=";"))
    assert [row["document_id"] for row in review] == ["11"]


def test_rejects_service_outside_allowlist(tmp_path):
    dry_run, documents, legacy = inputs(tmp_path)
    payload = json.loads(dry_run.read_text(encoding="utf-8"))
    payload["services"][0]["document_id"] = 99
    dry_run.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="outside authorized scope"):
        build_package(dry_run, documents, legacy, tmp_path / "output")


def test_rejects_reconciliation_scope_different_from_allowlist(tmp_path):
    dry_run, documents, legacy = inputs(tmp_path)
    payload = json.loads(dry_run.read_text(encoding="utf-8"))
    payload["reconciliations"].pop()
    dry_run.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="Reconciliation scope"):
        build_package(dry_run, documents, legacy, tmp_path / "output")


def test_packaged_row_is_accepted_by_guarded_import_preview(tmp_path, db_session):
    vehicle = Vehicle(plate="PACKAGE-TEST")
    db_session.add(vehicle)
    db_session.flush()
    document = Document(
        title="Synthetic invoice",
        original_name="invoice.pdf",
        file_name="invoice.pdf",
        storage_path="tests/invoice.pdf",
        vehicle_id=vehicle.id,
        classification="invoice",
        document_type="workshop_supplier_invoice",
        source="test",
    )
    db_session.add(document)
    db_session.commit()
    row = import_row(
        {
            "stable_key": "synthetic:1",
            "document_id": document.id,
            "service_code": "BRAKE.PAD",
            "service_text": "Pastilhas frente",
            "service_date": "2025-01-02",
            "amount": "42.00",
            "source_line_ids": f"{document.id}:1",
        }
    )
    path = tmp_path / "vehicle.csv"
    write_csv(path, [row], IMPORT_HEADERS)

    preview = preview_invoice_service_import(
        db_session,
        path.read_bytes(),
        path.name,
        version="test",
        source="invoice_service_remediation",
        allowed_vehicle_id=vehicle.id,
    )

    assert preview["can_apply"] is True
    assert preview["counts"]["create"] == 1
    assert preview["rows"][0]["values"]["status"] == "pending_validation"
