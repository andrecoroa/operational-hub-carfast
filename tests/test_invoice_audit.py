import json
import hashlib

from app.models.documents import (
    Document,
    DocumentEvent,
    DocumentWorkflowState,
    VehicleDocumentRecordTag,
)
from app.models.vehicles import Vehicle
from app.services.invoice_audit import AUDIT_SCHEMA, build_invoice_audit_dry_run


def _document(**overrides):
    values = {
        "title": "Fatura",
        "document_type": "workshop_supplier_invoice",
        "classification": "invoice",
        "source": "v2_clean_manual",
        "original_name": "fatura.pdf",
        "file_name": "fatura.pdf",
        "storage_provider": "local",
        "storage_path": "Frota/fatura.pdf",
        "status": "extracted",
    }
    values.update(overrides)
    return Document(**values)


def test_dry_run_separates_scope_and_never_writes(db_session) -> None:
    vehicle = Vehicle(plate="AA-00-AA", brand="Test", model="Audit", active=True)
    db_session.add(vehicle)
    db_session.flush()
    technical = _document(vehicle_id=vehicle.id, plate=vehicle.plate)
    stock = _document(
        title="Importação stock",
        source="stock_direct_import",
        original_name="stock.xlsx",
        file_name="stock.xlsx",
    )
    financial = _document(
        title="IUC",
        document_type="finance_supplier_invoice",
        classification="finance",
        original_name="iuc.pdf",
        file_name="iuc.pdf",
    )
    db_session.add_all([technical, stock, financial])
    db_session.flush()
    db_session.add_all(
        [
            DocumentWorkflowState(
                document_id=technical.id,
                invoice_nature="operacional",
                extraction_status="extracted",
                human_confirmed=True,
            ),
            DocumentWorkflowState(
                document_id=stock.id,
                invoice_nature="stock",
                extraction_status="not_requested",
            ),
            DocumentWorkflowState(
                document_id=financial.id,
                invoice_nature="financeira",
                extraction_status="extracted",
            ),
            DocumentEvent(
                document_id=technical.id,
                action="invoice.ocr.extracted",
                old_value=None,
                new_value=json.dumps(
                    {
                        "invoice_lines": [
                            {"description": "Líquido de lava-vidros", "service": "Por classificar"}
                        ]
                    }
                ),
            ),
            VehicleDocumentRecordTag(
                vehicle_id=vehicle.id,
                document_id=technical.id,
                category="other",
                value="glass",
                source_kind="manual",
            ),
        ]
    )
    db_session.commit()

    before = db_session.query(DocumentEvent).count()
    report = build_invoice_audit_dry_run(db_session, verify_files=False)
    after = db_session.query(DocumentEvent).count()

    assert report["schema"] == AUDIT_SCHEMA
    assert report["read_only"] is True
    assert report["write_operations"] == 0
    assert report["summary"]["documents"] == 3
    assert report["summary"]["scope_technical"] == 1
    assert report["summary"]["scope_excluded"] == 2
    assert report["summary"]["unclassified_lines"] == 1
    technical_row = next(row for row in report["documents"] if row["document_id"] == technical.id)
    assert technical_row["human_locked"] is True
    assert "human_classification_locked" in technical_row["blockers"]
    assert "FLUID.WASHER" in technical_row["proposal"]["taxonomy_codes"]
    assert "GLASS.REPLACE" not in technical_row["proposal"]["taxonomy_codes"]
    assert before == after


def test_dry_run_verifies_the_physical_hash_without_updating_the_document(
    db_session, monkeypatch, tmp_path
) -> None:
    content = b"synthetic invoice"
    invoice_path = tmp_path / "invoice.pdf"
    invoice_path.write_bytes(content)
    document = _document(storage_path="invoice.pdf", file_hash="0" * 64)
    db_session.add(document)
    db_session.commit()
    monkeypatch.setattr("app.services.invoice_audit._archive_root", lambda: tmp_path)

    report = build_invoice_audit_dry_run(db_session, hash_files=True)

    row = next(item for item in report["documents"] if item["document_id"] == document.id)
    assert row["verified_hash"] == hashlib.sha256(content).hexdigest()
    assert row["hash_matches"] is False
    assert "physical_file_hash_mismatch" in row["blockers"]
    assert db_session.get(Document, document.id).file_hash == "0" * 64


def test_dry_run_limits_technical_scope_to_invoices_and_reports(db_session) -> None:
    invoice = _document(document_type="workshop_supplier_invoice")
    report = _document(document_type="workshop_report", original_name="report.pdf")
    diagnostic = _document(document_type="workshop_diagnostic", original_name="diag.pdf")
    photo = _document(document_type="workshop_photo", original_name="photo.jpg")
    db_session.add_all([invoice, report, diagnostic, photo])
    db_session.commit()

    result = build_invoice_audit_dry_run(db_session, verify_files=False)

    selected_ids = {row["document_id"] for row in result["documents"]}
    assert selected_ids == {invoice.id, report.id}
    assert result["summary"]["documents"] == 2
    assert result["summary"]["scope_technical"] == 2
