from app.models.documents import DiagnosticDocument, DiagnosticExtraction, Document
from scripts.export_vehicle_document_audit_readonly import build_vehicle_document_audit


def test_export_is_sanitized_and_flags_document_gaps(db_session):
    document = Document(
        title="sensitive title",
        original_name="private.pdf",
        file_name="private.pdf",
        storage_provider="local",
        storage_path="/definitely/missing/private.pdf",
        document_type="diagnostic_report",
        status="received",
    )
    db_session.add(document)
    db_session.flush()
    diagnostic = DiagnosticDocument(
        document_id=document.id,
        diagnostic_type="generic",
        ocr_status="failed",
    )
    db_session.add(diagnostic)
    db_session.flush()
    db_session.add(
        DiagnosticExtraction(
            diagnostic_document_id=diagnostic.id,
            extractor_name="test",
            extractor_version="1",
            parser_name="test",
            parser_version="1",
            source_sha256="0" * 64,
            source_page_count=1,
            extraction_method="ocr",
            extraction_status="failed",
        )
    )
    db_session.flush()

    summary, rows = build_vehicle_document_audit(db_session, verify_local_files=True)

    row = next(item for item in rows if item["document_id"] == document.id)
    assert row["ocr_failed"] is True
    assert row["local_file_missing"] is True
    assert row["vehicle_unassociated"] is True
    assert "title" not in row
    assert "storage_path" not in row
    assert summary["database_writes"] == 0


def test_export_excludes_invoices(db_session):
    invoice = Document(
        original_name="invoice.pdf",
        file_name="invoice.pdf",
        storage_provider="local",
        storage_path="/missing/invoice.pdf",
        document_type="workshop_supplier_invoice",
        status="received",
    )
    db_session.add(invoice)
    untyped = Document(
        original_name="unknown.pdf",
        file_name="unknown.pdf",
        storage_provider="local",
        storage_path="/missing/unknown.pdf",
        document_type=None,
        status="received",
    )
    db_session.add(untyped)
    db_session.flush()

    _summary, rows = build_vehicle_document_audit(db_session)

    assert all(row["document_id"] != invoice.id for row in rows)
    assert any(row["document_id"] == untyped.id for row in rows)
