from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.api.routes import stock as stock_api
from app.models.admin import Permission, Role, RolePermission
from app.models.documents import Document, DocumentWorkflowState
from app.models.stock import (
    StockArticle,
    StockArticleSupplierRef,
    StockInvoiceImport,
    StockInvoiceLine,
    StockLocation,
    StockMinimum,
    StockMovement,
    StockReceipt,
    StockReceiptInvoiceLink,
    StockReceiptLine,
)
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess, WorkshopTechnicalReading
from app.models.workshop_phased import WorkshopPhasedProcess, WorkshopPhasedProcessPhase
from app.services.stock import (
    low_stock_rows,
    parse_caetano_parts_invoice,
    parse_dispnal_invoice,
    parse_torres_cunha_invoice,
    stock_balances,
)


def _document(
    name: str, *, file_hash: str | None = None, vehicle_id: int | None = None
) -> Document:
    return Document(
        title=name,
        document_type="workshop_supplier_invoice",
        classification="invoice",
        source="stock_test",
        entry_channel="document_inbox",
        original_name=f"{name}.pdf",
        file_name=f"{name}.pdf",
        storage_provider="local",
        storage_path=f"Stock/{name}.pdf",
        file_hash=file_hash,
        status="received",
        vehicle_id=vehicle_id,
    )


def _review_payload(invoice_number: str):
    return {
        "supplier_tax_id": "504670409",
        "supplier_name": "Dispnal Pneus, S.A.",
        "invoice_number": invoice_number,
        "invoice_date": "2026-07-28",
        "net_total": "100.00",
        "tax_total": "23.00",
        "gross_total": "123.00",
        "lines": [
            {
                "line_number": 1,
                "supplier_ref": "DISP-001",
                "description": "Pneu Petlas 215/70 R15C",
                "quantity": "10",
                "unit": "un.",
                "unit_cost": "10",
                "discount": "0.10",
                "eco_value": "1",
                "tax_rate": "0.23",
                "line_total": "123.00",
            }
        ],
    }


def _create_article(authenticated_client, reference="PNEU-TESTE") -> int:
    response = authenticated_client.post(
        "/api/stock/articles",
        json={
            "internal_ref": reference,
            "name": "Pneu de teste",
            "unit": "un.",
            "classification": "pneu",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _isolation_fixture(db_session):
    vehicle = Vehicle(
        plate="ST-00-CK",
        vin="VF3STOCKISOLATION001",
        lifecycle_status="active",
        operational_status="in_maintenance",
        active=True,
    )
    db_session.add(vehicle)
    db_session.flush()
    process = WorkshopProcess(
        vehicle_id=vehicle.id,
        title="Processo imutável durante operações Stock",
        status="in_progress",
        km_entry=84521,
        decision="repair",
    )
    phased = WorkshopPhasedProcess(
        process_type="repair",
        title="Processo faseado isolado",
        creation_mode="operational",
        status="active",
        vehicle_id=vehicle.id,
        current_phase_code="diagnosis",
        initial_km=84521,
    )
    db_session.add_all([process, phased])
    db_session.flush()
    phase = WorkshopPhasedProcessPhase(
        process_id=phased.id,
        phase_code="diagnosis",
        name="Diagnóstico",
        status="in_progress",
        sort_order=1,
    )
    reading = WorkshopTechnicalReading(
        process_id=process.id,
        vehicle_id=vehicle.id,
        reading_type="technical",
        reading_date=date(2026, 7, 28),
        odometer_km=84521,
        status="active",
    )
    workshop_document = Document(
        title="Fotografia original da Oficina",
        document_type="workshop_photo",
        classification="workshop",
        source="workshop",
        original_name="foto.jpg",
        file_name="foto.jpg",
        storage_provider="local",
        storage_path="Oficina/foto.jpg",
        status="classified",
        vehicle_id=vehicle.id,
        workshop_process_id=process.id,
        file_hash="photo-original-hash",
    )
    db_session.add_all([phase, reading, workshop_document])
    db_session.commit()
    return {
        "vehicle": vehicle.id,
        "process": process.id,
        "phased": phased.id,
        "phase": phase.id,
        "reading": reading.id,
        "document": workshop_document.id,
        "snapshot": (
            vehicle.operational_status,
            process.status,
            process.km_entry,
            process.decision,
            process.closed_at,
            phased.status,
            phased.current_phase_code,
            phased.initial_km,
            phased.closed_at,
            phase.status,
            reading.odometer_km,
            reading.status,
            workshop_document.status,
            workshop_document.file_hash,
            workshop_document.storage_path,
        ),
    }


def _assert_workshop_unchanged(db_session, isolation):
    db_session.expire_all()
    vehicle = db_session.get(Vehicle, isolation["vehicle"])
    process = db_session.get(WorkshopProcess, isolation["process"])
    phased = db_session.get(WorkshopPhasedProcess, isolation["phased"])
    phase = db_session.get(WorkshopPhasedProcessPhase, isolation["phase"])
    reading = db_session.get(WorkshopTechnicalReading, isolation["reading"])
    document = db_session.get(Document, isolation["document"])
    assert (
        vehicle.operational_status,
        process.status,
        process.km_entry,
        process.decision,
        process.closed_at,
        phased.status,
        phased.current_phase_code,
        phased.initial_km,
        phased.closed_at,
        phase.status,
        reading.odometer_km,
        reading.status,
        document.status,
        document.file_hash,
        document.storage_path,
    ) == isolation["snapshot"]


def test_stock_invoice_classification_archives_and_removes_operational_association(
    authenticated_client, db_session
):
    vehicle = Vehicle(
        plate="FS-00-01",
        vin="VF3STOCKDOCUMENT001",
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(vehicle)
    db_session.flush()
    document = _document("fatura-classificada", vehicle_id=vehicle.id)
    db_session.add(document)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/documentation/invoices/{document.id}/nature",
        data={"nature": "stock", "decision_reason": "Compra para armazém"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    state = db_session.scalar(
        select(DocumentWorkflowState).where(DocumentWorkflowState.document_id == document.id)
    )
    document = db_session.get(Document, document.id)
    assert state.invoice_nature == "stock"
    assert state.destination_status == "archive"
    assert document.classification == "finance"
    assert document.document_type == "finance_supplier_invoice"
    assert document.status == "archived"
    assert document.archived is True
    assert document.vehicle_id is None
    assert document.workshop_process_id is None
    assert db_session.scalar(select(func.count()).select_from(StockInvoiceImport)) == 1
    assert db_session.scalar(select(func.count()).select_from(StockArticle)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_direct_stock_invoice_import_classifies_and_opens_review(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    from app.web import stock as stock_web

    monkeypatch.setattr(stock_web, "document_archive_root", lambda: tmp_path)
    monkeypatch.setattr(
        stock_web,
        "extract_stock_invoice",
        lambda _db, record: setattr(record, "status", "needs_review") or {},
    )
    response = authenticated_client.post(
        "/v2-clean/stock/invoices/import",
        files={"file": ("FT-100.pdf", b"%PDF-1.4\nstock test", "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/stock/invoices/")
    document = db_session.scalar(select(Document).where(Document.original_name == "FT-100.pdf"))
    state = db_session.scalar(
        select(DocumentWorkflowState).where(DocumentWorkflowState.document_id == document.id)
    )
    invoice_import = db_session.scalar(
        select(StockInvoiceImport).where(StockInvoiceImport.document_id == document.id)
    )
    assert state.invoice_nature == "stock"
    assert state.human_confirmed is True
    assert document.source == "stock_direct_import"
    assert document.vehicle_id is None
    assert document.archived is True
    assert invoice_import.status == "needs_review"
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_direct_stock_invoice_import_keeps_unreadable_pdf_for_manual_review(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    from app.web import stock as stock_web

    monkeypatch.setattr(stock_web, "document_archive_root", lambda: tmp_path)
    response = authenticated_client.post(
        "/v2-clean/stock/invoices/import",
        files={"file": ("danificada.pdf", b"%PDF-1.4\nsem estrutura", "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/stock/invoices/")
    invoice_import = db_session.scalar(
        select(StockInvoiceImport)
        .join(Document, Document.id == StockInvoiceImport.document_id)
        .where(Document.original_name == "danificada.pdf")
    )
    assert invoice_import.status == "needs_review"
    assert "revisão manual" in invoice_import.error_details


def test_direct_stock_invoice_import_survives_extractor_database_failure(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    from sqlalchemy.exc import ProgrammingError

    from app.web import stock as stock_web

    monkeypatch.setattr(stock_web, "document_archive_root", lambda: tmp_path)

    def fail_extraction(_db, _invoice_import):
        raise ProgrammingError("extract", {}, RuntimeError("modelo indisponível"))

    monkeypatch.setattr(stock_web, "extract_stock_invoice", fail_extraction)
    response = authenticated_client.post(
        "/v2-clean/stock/invoices/import",
        files={"file": ("FT-modelo.pdf", b"%PDF-1.4\nstock", "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/stock/invoices/")
    invoice_import = db_session.scalar(
        select(StockInvoiceImport)
        .join(Document, Document.id == StockInvoiceImport.document_id)
        .where(Document.original_name == "FT-modelo.pdf")
    )
    assert invoice_import.status == "needs_review"
    assert "ProgrammingError" in invoice_import.error_details


def test_manual_stock_invoice_extraction_survives_unexpected_failure(
    authenticated_client, db_session, monkeypatch
):
    from app.web import stock as stock_web

    document = _document("FT-manual-extraction")
    db_session.add(document)
    db_session.flush()
    invoice_import = StockInvoiceImport(
        document_id=document.id,
        status="needs_review",
    )
    db_session.add(invoice_import)
    db_session.commit()

    def fail_extraction(_db, _invoice_import):
        raise RuntimeError("falha técnica simulada")

    monkeypatch.setattr(stock_web, "extract_stock_invoice", fail_extraction)
    response = authenticated_client.post(
        f"/v2-clean/stock/invoices/{invoice_import.id}/extract",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "extraction_review=1" in response.headers["location"]
    db_session.refresh(invoice_import)
    assert invoice_import.status == "needs_review"
    assert "RuntimeError" in invoice_import.error_details


def test_direct_stock_invoice_import_persists_recognized_decimal_extraction(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    from app.services import stock as stock_service
    from app.web import stock as stock_web

    monkeypatch.setattr(stock_web, "document_archive_root", lambda: tmp_path)
    monkeypatch.setattr(
        stock_service,
        "_pdf_lines",
        lambda _path: (["fatura reconhecida"], "b" * 64),
    )
    monkeypatch.setattr(
        stock_service,
        "parse_stock_invoice",
        lambda _lines, content_hash: {
            "extractor_name": "recognized_test",
            "extractor_version": "v1",
            "content_hash": content_hash,
            "supplier_name": "Fornecedor teste",
            "invoice_number": "FT-DECIMAL",
            "net_total": Decimal("10.00"),
            "tax_total": Decimal("2.30"),
            "gross_total": Decimal("12.30"),
            "lines": [
                {
                    "line_number": 1,
                    "supplier_ref": "ART-1",
                    "description": "Artigo teste",
                    "quantity": Decimal("2.000"),
                    "unit": "un.",
                    "unit_cost": Decimal("5.0000"),
                    "discount": Decimal("0"),
                    "eco_value": Decimal("0"),
                    "tax_rate": Decimal("0.23"),
                    "line_total": Decimal("12.30"),
                }
            ],
        },
    )

    response = authenticated_client.post(
        "/v2-clean/stock/invoices/import",
        files={"file": ("reconhecida.pdf", b"%PDF-1.4\nstock", "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/stock/invoices/")
    invoice_import = db_session.scalar(
        select(StockInvoiceImport).where(StockInvoiceImport.extractor_name == "recognized_test")
    )
    assert invoice_import.error_details is None
    assert invoice_import.raw_extraction_json["net_total"] == "10.00"
    assert invoice_import.raw_extraction_json["lines"][0]["quantity"] == "2.000"


def test_direct_stock_invoice_import_reports_storage_failure(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    from app.web import stock as stock_web

    blocked_root = tmp_path / "arquivo"
    blocked_root.write_text("não é uma pasta", encoding="utf-8")
    monkeypatch.setattr(stock_web, "document_archive_root", lambda: blocked_root)
    response = authenticated_client.post(
        "/v2-clean/stock/invoices/import",
        files={"file": ("FT-erro.pdf", b"%PDF-1.4\nstock", "application/pdf")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/stock/invoices?error=")
    assert db_session.scalar(select(func.count()).select_from(StockInvoiceImport)) == 0


def test_direct_stock_invoice_batch_keeps_valid_files_when_one_is_invalid(
    authenticated_client, db_session, tmp_path, monkeypatch
):
    from app.web import stock as stock_web

    monkeypatch.setattr(stock_web, "document_archive_root", lambda: tmp_path)
    monkeypatch.setattr(
        stock_web,
        "extract_stock_invoice",
        lambda _db, record: setattr(record, "status", "needs_review") or {},
    )
    response = authenticated_client.post(
        "/v2-clean/stock/invoices/import",
        files=[
            ("file", ("FT-LOTE-1.pdf", b"%PDF-1.4\none", "application/pdf")),
            ("file", ("ignorar.txt", b"not a pdf", "text/plain")),
            ("file", ("FT-LOTE-2.pdf", b"%PDF-1.4\ntwo", "application/pdf")),
        ],
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "batch_imported=2" in response.headers["location"]
    assert "batch_failed=1" in response.headers["location"]
    assert db_session.scalar(select(func.count()).select_from(StockInvoiceImport)) == 2


def test_blind_inventory_reveals_snapshot_only_after_close_and_confirms_difference(
    authenticated_client, db_session
):
    article_id = _create_article(authenticated_client, "COUNT-001")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    created = authenticated_client.post(
        "/api/stock/inventory-sessions",
        json={"location_id": workshop.id, "idempotency_key": "count-001"},
    )
    assert created.status_code == 201, created.text
    inventory_id = created.json()["id"]
    blind = authenticated_client.get(f"/api/stock/inventory-sessions/{inventory_id}")
    assert "expected_quantity" not in blind.text
    assert "difference_quantity" not in blind.text
    closed = authenticated_client.post(
        f"/api/stock/inventory-sessions/{inventory_id}/counts?close=true",
        json={"counts": [{"article_id": article_id, "counted_quantity": "7"}]},
    )
    assert closed.status_code == 200, closed.text
    assert (
        authenticated_client.get(f"/api/stock/inventory-sessions/{inventory_id}").json()["items"][
            0
        ]["expected_quantity"]
        == 0
    )
    confirmed = authenticated_client.post(
        f"/api/stock/inventory-sessions/{inventory_id}/confirm",
        json={"confirmations": [{"article_id": article_id, "justification": "Inventário mensal"}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    movement = db_session.scalar(
        select(StockMovement).where(StockMovement.article_id == article_id)
    )
    assert movement.movement_type == "adjustment"
    assert movement.quantity == Decimal("7.000")
    assert movement.to_location_id == workshop.id
    assert stock_balances(db_session, article_ids=[article_id])[
        (article_id, workshop.id)
    ] == Decimal("7.000")


def test_extract_and_validate_are_document_only(authenticated_client, db_session, monkeypatch):
    document = _document("document-only", file_hash="a" * 64)
    db_session.add(document)
    db_session.commit()
    invoice_import = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()

    def fake_extract(_db, record):
        record.raw_extraction_json = _review_payload("DOC-1/2026")
        record.status = "needs_review"
        return record.raw_extraction_json

    monkeypatch.setattr(stock_api, "extract_stock_invoice", fake_extract)
    extracted = authenticated_client.post(
        f"/api/stock/invoice-imports/{invoice_import['id']}/extract"
    )
    assert extracted.status_code == 200
    validated = authenticated_client.post(
        f"/api/stock/invoice-imports/{invoice_import['id']}/validate",
        json=_review_payload("DOC-1/2026"),
    )
    assert validated.status_code == 200, validated.text
    assert validated.json()["stock_changed"] is False
    db_session.expire_all()
    line = db_session.scalar(
        select(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == invoice_import["id"])
    )
    assert line.quantity == Decimal("10.000")
    assert line.article_id is None
    assert db_session.scalar(select(func.count()).select_from(StockArticle)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockArticleSupplierRef)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockReceiptLine)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 0
    assert stock_balances(db_session) == {}


def test_invoice_rounding_difference_warns_without_blocking_document_values(
    authenticated_client, db_session
):
    document = _document("rounding-warning")
    db_session.add(document)
    db_session.commit()
    invoice_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()["id"]
    payload = _review_payload("ROUND-1/2026")
    payload["lines"][0]["line_total"] = "123.01"
    payload["gross_total"] = "123.01"

    response = authenticated_client.post(
        f"/api/stock/invoice-imports/{invoice_id}/validate", json=payload
    )

    assert response.status_code == 200, response.text
    db_session.expire_all()
    invoice_import = db_session.get(StockInvoiceImport, invoice_id)
    invoice_line = db_session.scalar(
        select(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == invoice_id)
    )
    assert invoice_import.status == "validated"
    assert invoice_import.gross_total == Decimal("123.0100")
    assert invoice_line.line_total == Decimal("123.0100")
    assert "valores documentais foram guardados sem alteração" in invoice_import.error_details
    assert invoice_import.raw_extraction_json["reconciliation"]["status"] == "divergent"


def test_invoice_preview_creates_article_and_confirms_physical_receipt(
    authenticated_client, db_session
):
    document = _document("guided-stock-receipt")
    db_session.add(document)
    db_session.commit()
    invoice_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()["id"]
    validated = authenticated_client.post(
        f"/api/stock/invoice-imports/{invoice_id}/validate",
        json=_review_payload("GUIDED-1/2026"),
    )
    assert validated.status_code == 200, validated.text
    invoice_import = db_session.get(StockInvoiceImport, invoice_id)
    invoice_line = db_session.scalar(
        select(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == invoice_id)
    )
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))

    preview = authenticated_client.get(f"/v2-clean/stock/invoices/{invoice_id}")
    assert preview.status_code == 200
    assert "Artigos e quantidades recebidas" in preview.text
    assert "Confirmar receção física" in preview.text
    response = authenticated_client.post(
        f"/v2-clean/stock/invoices/{invoice_id}/receive",
        data={
            "invoice_line_id": str(invoice_line.id),
            "article_id": "",
            "internal_ref": "PNEU-GUIDED",
            "article_name": "Pneu guiado",
            "classification": "pneu",
            "accepted_quantity": "4",
            "divergence_reason": "Receção parcial",
            "location_id": str(workshop.id),
            "source_type": "invoice",
            "source_reference": "GUIDED-1/2026",
            "notes": "Confirmado fisicamente",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "received=" in response.headers["location"]
    db_session.expire_all()
    article = db_session.scalar(
        select(StockArticle).where(StockArticle.internal_ref == "PNEU-GUIDED")
    )
    invoice_line = db_session.get(StockInvoiceLine, invoice_line.id)
    assert article.name == "Pneu guiado"
    assert article.primary_supplier_id == invoice_import.supplier_id
    assert invoice_line.article_id == article.id
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 1
    assert db_session.scalar(select(func.count()).select_from(StockReceiptInvoiceLink)) == 1
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 1
    assert stock_balances(db_session)[(article.id, workshop.id)] == Decimal("4.000")


def test_receipts_start_only_from_physical_stock_action_and_can_link_one_invoice_many_times(
    authenticated_client, db_session
):
    isolation = _isolation_fixture(db_session)
    article_id = _create_article(authenticated_client)
    document = _document("physical-link")
    db_session.add(document)
    db_session.commit()
    invoice_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()["id"]
    assert (
        authenticated_client.post(
            f"/api/stock/invoice-imports/{invoice_id}/validate",
            json=_review_payload("PHYS-1/2026"),
        ).status_code
        == 200
    )
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    airport = db_session.scalar(select(StockLocation).where(StockLocation.code == "AIRPORT"))

    first = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": workshop.id,
            "source_type": "delivery_note",
            "source_reference": "GT-100",
            "invoice_import_ids": [invoice_id],
            "lines": [
                {
                    "article_id": article_id,
                    "supplier_ref": "DISP-001",
                    "accepted_quantity": "4",
                    "unit_cost": "10",
                }
            ],
        },
    )
    assert first.status_code == 201, first.text
    second = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": airport.id,
            "source_type": "manual",
            "manual_reason": "Entrega sem documento",
            "responsible_name": "Responsável Aeroporto",
            "invoice_import_ids": [invoice_id],
            "lines": [{"article_id": article_id, "accepted_quantity": "3", "unit_cost": "11"}],
        },
    )
    assert second.status_code == 201, second.text
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 2
    assert db_session.scalar(select(func.count()).select_from(StockReceiptInvoiceLink)) == 2
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 2
    assert stock_balances(db_session)[(article_id, workshop.id)] == Decimal("4.000")
    assert stock_balances(db_session)[(article_id, airport.id)] == Decimal("3.000")
    _assert_workshop_unchanged(db_session, isolation)


def test_linking_invoice_after_receipt_is_idempotent_and_never_changes_stock(
    authenticated_client, db_session
):
    article_id = _create_article(authenticated_client, "FILTRO-TESTE")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    receipt_id = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": workshop.id,
            "source_type": "manual",
            "manual_reason": "Receção física sem documento",
            "lines": [{"article_id": article_id, "accepted_quantity": "2", "unit_cost": "5"}],
        },
    ).json()["id"]
    document = _document("later-link")
    db_session.add(document)
    db_session.commit()
    invoice_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()["id"]
    before = stock_balances(db_session).copy()
    for _ in range(2):
        response = authenticated_client.post(
            f"/api/stock/receipts/{receipt_id}/invoice-links/{invoice_id}"
        )
        assert response.status_code == 200
        assert response.json()["stock_changed"] is False
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(StockReceiptInvoiceLink)) == 1
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 1
    assert stock_balances(db_session) == before


def test_receipt_idempotency_and_airport_responsibility(authenticated_client, db_session):
    article_id = _create_article(authenticated_client, "OLEO-IDEMP")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    airport = db_session.scalar(select(StockLocation).where(StockLocation.code == "AIRPORT"))
    payload = {
        "location_id": workshop.id,
        "source_type": "delivery_note",
        "source_reference": "GT-IDEMP",
        "idempotency_key": "receipt-idempotency-test",
        "lines": [{"article_id": article_id, "accepted_quantity": "2", "unit_cost": "8"}],
    }
    first = authenticated_client.post("/api/stock/receipts", json=payload)
    second = authenticated_client.post("/api/stock/receipts", json=payload)
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 1
    missing_responsible = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": airport.id,
            "source_type": "manual",
            "lines": [{"article_id": article_id, "accepted_quantity": "1"}],
        },
    )
    assert missing_responsible.status_code == 422


def test_legacy_invoice_driven_receipt_endpoint_cannot_create_stock(
    authenticated_client, db_session
):
    document = _document("legacy-endpoint")
    db_session.add(document)
    db_session.commit()
    invoice_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()["id"]
    response = authenticated_client.post(
        f"/api/stock/invoice-imports/{invoice_id}/receipts", json={}
    )
    assert response.status_code in {404, 405}
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_low_stock_alert_and_movement_immutability(authenticated_client, db_session):
    article_id = _create_article(authenticated_client, "IMMUTABLE")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    assert (
        authenticated_client.post(
            "/api/stock/receipts",
            json={
                "location_id": workshop.id,
                "source_type": "manual",
                "manual_reason": "Receção física sem documento",
                "lines": [{"article_id": article_id, "accepted_quantity": "2", "unit_cost": "4"}],
            },
        ).status_code
        == 201
    )
    db_session.add(
        StockMinimum(
            article_id=article_id,
            location_id=workshop.id,
            minimum_quantity=Decimal("3"),
        )
    )
    db_session.commit()
    assert len(low_stock_rows(db_session)) == 1
    movement = db_session.scalar(select(StockMovement).order_by(StockMovement.id))
    movement.reason = "Tentativa de edição"
    with pytest.raises(ValueError, match="imutáveis"):
        db_session.commit()
    db_session.rollback()
    movement = db_session.get(StockMovement, movement.id)
    db_session.delete(movement)
    with pytest.raises(ValueError, match="imutáveis"):
        db_session.commit()
    db_session.rollback()


def test_existing_profiles_receive_stock_permissions(db_session):
    grants = {
        role_code: {
            permission_code
            for (permission_code,) in db_session.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .join(Role, Role.id == RolePermission.role_id)
                .where(Role.code == role_code)
            ).all()
        }
        for role_code in ("viewer", "operator", "manager", "admin")
    }
    assert "stock.read" in grants["viewer"]
    assert {"stock.read", "stock.operate"} <= grants["operator"]
    assert {"stock.read", "stock.operate", "stock.manage"} <= grants["manager"]
    assert {"stock.read", "stock.operate", "stock.manage"} <= grants["admin"]


@pytest.mark.parametrize(
    "path",
    [
        "/v2-clean/stock",
        "/v2-clean/stock/articles",
        "/v2-clean/stock/suppliers",
        "/v2-clean/stock/receipts",
        "/v2-clean/stock/invoices",
        "/v2-clean/stock/current",
        "/v2-clean/stock/movements",
    ],
)
def test_clean_stock_pages_render_and_explain_physical_boundary(authenticated_client, path):
    response = authenticated_client.get(path)
    assert response.status_code == 200
    assert 'class="stock-nav"' in response.text
    assert "Stock" in response.text
    if path.endswith("/receipts"):
        assert "Só quantidades fisicamente aceites" in response.text
    if path.endswith("/invoices"):
        assert "cria artigos, receções, movimentos ou existências" in response.text


def test_stock_filters_accept_empty_optional_ids(authenticated_client):
    articles = authenticated_client.get(
        "/v2-clean/stock/articles",
        params={"category_id": "", "supplier_id": "", "location_id": ""},
    )
    current = authenticated_client.get(
        "/v2-clean/stock/current",
        params={"location_id": ""},
    )

    assert articles.status_code == 200
    assert current.status_code == 200


def test_dispnal_parser_keeps_documentary_fields_only():
    lines = [
        "Dispnal Pneus, S.A. | NIF 504670409",
        "N.º 8643/2026",
        "ABC1234567 | PNEU PETLAS 215/70 R15C | 10,00 | UN | 10,00 | 10,00 | 1,00 | 23,00 | 90,00",
        "IVA | 23,00",
        "Total ( EUR ) | 123,00",
    ]
    parsed = parse_dispnal_invoice(lines, "f" * 64)
    assert parsed["supplier_tax_id"] == "504670409"
    assert parsed["invoice_number"] == "8643/2026"
    assert parsed["lines"][0]["supplier_ref"] == "ABC1234567"
    assert "article_id" not in parsed["lines"][0]
    assert "receipt_id" not in parsed


def test_dispnal_parser_accepts_native_or_ocr_text_layout():
    lines = [
        "Dispnal Pneus, S.A.",
        "Contribuinte N.º: 504670409",
        "Fatura FT N.º 15319/2026",
        "EUR 1,00 999 3044 509285970 0,00 0,00 30 Dias 2026-07-01 2026-07-31",
        "15210516190VM 195/55R16 XL 91V TL PXCM PNEU TOYO 4,0 UN 60,00 0,00 1,48 23,00 240,00",
        "IVA (23,00) 245,92 56,56",
        "Total ( EUR ) 302,48",
    ]

    parsed = parse_dispnal_invoice(lines, "c" * 64)

    assert parsed["invoice_number"] == "15319/2026"
    assert parsed["invoice_date"] == "2026-07-01"
    assert parsed["due_date"] == "2026-07-31"
    assert parsed["net_total"] == "245,92"
    assert parsed["tax_total"] == "56,56"
    assert parsed["gross_total"] == "302,48"
    assert parsed["lines"][0]["description"] == "195/55R16 XL 91V TL PXCM PNEU TOYO"


def test_torres_parser_ignores_duplicate_copy_and_keeps_ecovalue():
    lines = [
        "Fatura | nº | 6701/2026",
        "ORIGINAL | FT | 2026A1/6701",
        "Torres | & | Cunha | Peças | Auto | Lda.",
        "Contribuinte: | 503699292",
        "65621-5L | 3J.3 | OLEO | SINT. | 0W20 | 2,00 | UNI | 39,98 | 81,04 | 23,00",
        "23,00% | 100,82 | 23,19",
        "Total | 124,01",
        "DUPLICADO | FT | 2026A1/6701",
        "65621-5L | 3J.3 | OLEO | SINT. | 0W20 | 2,00 | UNI | 39,98 | 81,04 | 23,00",
    ]
    parsed = parse_torres_cunha_invoice(lines, "a" * 64)
    assert parsed["invoice_number"] == "6701/2026"
    assert parsed["gross_total"] == "124,01"
    assert len(parsed["lines"]) == 1
    assert Decimal(parsed["lines"][0]["eco_value"]) == Decimal("1.08")


def test_caetano_parser_preserves_repeated_article_lines():
    lines = [
        "Nº | Documento | JFM/547307/2026 | Carfast | Rent-A-Car",
        "Armazem | 1034",
        "PSA | 1682952480 | E:FILTRO | GASÓL | Armazem | 1034 | "
        "5,00Uds | 29,54 | 54,00 | 67,94 | 23,00",
        "PSA | 1682952480 | E:FILTRO | GASÓL | Armazem | 1034 | "
        "5,00Uds | 29,54 | 54,00 | 67,94 | 23,00",
        "0,00 | 0,00 | 268,72 | 315,46 | 61,81 | 330,53",
    ]
    parsed = parse_caetano_parts_invoice(lines, "b" * 64)
    assert parsed["supplier_tax_id"] == "504639668"
    assert parsed["invoice_number"] == "JFM/547307/2026"
    assert parsed["gross_total"] == "330,53"
    assert len(parsed["lines"]) == 2
