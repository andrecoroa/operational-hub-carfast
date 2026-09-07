import json
from datetime import date

from sqlalchemy import func, select

from app.models.documents import (
    Document,
    DocumentEvent,
    DocumentWorkflowState,
    VehicleDocumentRecordTag,
)
from app.models.vehicles import Vehicle
from app.services.invoice_audit_readonly_export import (
    build_readonly_export,
    reconcile_scope_rows,
)


def _document(vehicle_id: int, number: str, file_hash: str) -> Document:
    return Document(
        document_type="workshop_supplier_invoice",
        original_name=f"{number}.pdf",
        file_name=f"{number}.pdf",
        storage_path=f"archive/{number}.pdf",
        vehicle_id=vehicle_id,
        plate="AA-00-AA",
        supplier_name="Baia & Filho",
        contract_number=number,
        document_date=date(2025, 1, 10),
        file_hash=file_hash,
        status="extracted",
    )


def test_readonly_export_preserves_human_data_and_does_not_write(db_session):
    vehicle = Vehicle(plate="AA-00-AA", vin="VF7TEST0000000001")
    db_session.add(vehicle)
    db_session.flush()
    document = _document(vehicle.id, "FT-1", "hash-1")
    db_session.add(document)
    db_session.flush()
    workflow = DocumentWorkflowState(
        document_id=document.id,
        invoice_nature="operacional",
        human_confirmed=True,
    )
    tag = VehicleDocumentRecordTag(
        vehicle_id=vehicle.id,
        document_id=document.id,
        category="maintenance",
        value="revision",
        source_kind="manual",
    )
    event = DocumentEvent(
        document_id=document.id,
        action="invoice.ocr.extracted",
        new_value=json.dumps(
            {
                "document_number": "FT-1",
                "supplier_name": "Cruz & Allen",
                "supplier_nif": "500000001",
                "plate": "AA-00-AA",
                "vin": "VF7TEST0000000001",
                "total_with_vat": "123.45",
                "invoice_lines": [
                    {"description": "Óleo motor 0W30"},
                    {"description": "Filtro de óleo"},
                    {"description": "Filtro de habitáculo"},
                ],
            }
        ),
    )
    db_session.add_all([workflow, tag, event])
    db_session.commit()
    counts_before = {
        "documents": db_session.scalar(select(func.count()).select_from(Document)),
        "events": db_session.scalar(select(func.count()).select_from(DocumentEvent)),
        "tags": db_session.scalar(select(func.count()).select_from(VehicleDocumentRecordTag)),
    }

    bundle = build_readonly_export(
        db_session,
        [{"document_id": document.id, "technical_blocker": "false", "human_protected": "true"}],
        run_id="test-run",
        expected_documents=1,
        expected_blockers=0,
        expected_human_protected=1,
    )

    assert bundle.manifest["acceptance_passed"] is True
    assert bundle.manifest["database_writes"] == 0
    assert bundle.documents[0]["supplier_group"] == "BAIA_FILHO_CRUZ_ALLEN"
    assert bundle.documents[0]["workflow_human_confirmed"] is True
    assert bundle.documents[0]["eligible_for_counting"] is False
    assert json.loads(bundle.documents[0]["human_tags_json"])[0]["value"] == "revision"
    assert {row["event_taxonomy_code"] for row in bundle.services} >= {
        "MAINT.PLAN",
        "FILTER.CABIN",
    }
    assert counts_before == {
        "documents": db_session.scalar(select(func.count()).select_from(Document)),
        "events": db_session.scalar(select(func.count()).select_from(DocumentEvent)),
        "tags": db_session.scalar(select(func.count()).select_from(VehicleDocumentRecordTag)),
    }


def test_export_marks_duplicate_missing_extraction_and_count_mismatch(db_session):
    vehicle = Vehicle(plate="BB-00-BB")
    db_session.add(vehicle)
    db_session.flush()
    first = _document(vehicle.id, "FT-10", "same-hash")
    second = _document(vehicle.id, "FT-10-COPY", "same-hash")
    db_session.add_all([first, second])
    db_session.flush()
    db_session.add(
        DocumentEvent(
            document_id=first.id,
            action="invoice.ocr.extracted",
            new_value=json.dumps({"invoice_lines": [{"description": "Filtro de óleo"}]}),
        )
    )
    db_session.commit()

    bundle = build_readonly_export(
        db_session,
        [
            {"document_id": first.id, "technical_blocker": "false", "human_protected": "false"},
            {"document_id": second.id, "technical_blocker": "true", "human_protected": "false"},
        ],
        run_id="test-duplicates",
        expected_documents=1278,
        expected_blockers=103,
        expected_human_protected=9,
    )

    assert bundle.manifest["acceptance_passed"] is False
    assert bundle.manifest["count_mismatches"]["scope_documents"]["actual"] == 2
    assert {row["primary_queue"] for row in bundle.documents} == {"DUPLICATE_CHAIN"}
    assert "MISSING_EXTRACTION" in bundle.documents[1]["issue_codes"]


def test_reconciliation_closes_mathematically_without_inventing_reasons():
    rows, counts = reconcile_scope_rows(
        [{"document_id": 1}, {"document_id": 2}, {"document_id": 3}],
        [{"document_id": 2}, {"document_id": 3}, {"document_id": 4}],
    )

    assert counts == {
        "old_total": 3,
        "current_total": 3,
        "common": 2,
        "old_only": 1,
        "current_only": 1,
        "net_difference": 0,
    }
    assert rows[0]["reconciliation_state"] == "old_only_reason_unproven"
    assert rows[-1]["reconciliation_state"] == "current_only_reason_unproven"
    assert all(not row["reason_code"] for row in rows)
