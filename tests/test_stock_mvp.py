from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import func, select

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
)
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess, WorkshopTechnicalReading
from app.models.workshop_phased import WorkshopPhasedProcess, WorkshopPhasedProcessPhase
from app.services.stock import low_stock_rows, parse_dispnal_invoice, stock_balances


def _document(name: str, *, file_hash: str | None = None) -> Document:
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
    )


def _review_payload(invoice_number: str, *, supplier_ref: str = "DISP-001", create=True):
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
                "create_article": create,
                "internal_ref": "PNEU-TESTE" if create else None,
                "article_name": "Pneu de teste" if create else None,
                "supplier_ref": supplier_ref,
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
        "snapshot": {
            "vehicle_status": vehicle.operational_status,
            "process_status": process.status,
            "process_km": process.km_entry,
            "process_decision": process.decision,
            "process_closed": process.closed_at,
            "phased_status": phased.status,
            "phased_phase": phased.current_phase_code,
            "phased_km": phased.initial_km,
            "phased_closed": phased.closed_at,
            "phase_status": phase.status,
            "reading_km": reading.odometer_km,
            "reading_status": reading.status,
            "document_status": workshop_document.status,
            "document_hash": workshop_document.file_hash,
            "document_path": workshop_document.storage_path,
        },
    }


def _assert_workshop_unchanged(db_session, isolation):
    db_session.expire_all()
    vehicle = db_session.get(Vehicle, isolation["vehicle"])
    process = db_session.get(WorkshopProcess, isolation["process"])
    phased = db_session.get(WorkshopPhasedProcess, isolation["phased"])
    phase = db_session.get(WorkshopPhasedProcessPhase, isolation["phase"])
    reading = db_session.get(WorkshopTechnicalReading, isolation["reading"])
    document = db_session.get(Document, isolation["document"])
    assert {
        "vehicle_status": vehicle.operational_status,
        "process_status": process.status,
        "process_km": process.km_entry,
        "process_decision": process.decision,
        "process_closed": process.closed_at,
        "phased_status": phased.status,
        "phased_phase": phased.current_phase_code,
        "phased_km": phased.initial_km,
        "phased_closed": phased.closed_at,
        "phase_status": phase.status,
        "reading_km": reading.odometer_km,
        "reading_status": reading.status,
        "document_status": document.status,
        "document_hash": document.file_hash,
        "document_path": document.storage_path,
    } == isolation["snapshot"]


def test_document_classification_creates_pending_import_without_stock(
    authenticated_client, db_session
):
    document = _document("fatura-classificada")
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
    invoice_import = db_session.scalar(
        select(StockInvoiceImport).where(StockInvoiceImport.document_id == document.id)
    )
    assert state.invoice_nature == "stock"
    assert invoice_import.status == "needs_review"
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 0
    assert stock_balances(db_session) == {}


def test_end_to_end_partial_receipts_movements_and_workshop_isolation(
    authenticated_client, db_session
):
    isolation = _isolation_fixture(db_session)
    document = _document("ft-8643", file_hash="a" * 64)
    db_session.add(document)
    db_session.commit()

    imported = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={
            "document_id": document.id,
            "classification": "stock_invoice",
            "extracted_data": {"content_hash": "a" * 64},
        },
    )
    assert imported.status_code == 200
    import_id = imported.json()["id"]

    validated = authenticated_client.post(
        f"/api/stock/invoice-imports/{import_id}/validate",
        json=_review_payload("8643/2026"),
    )
    assert validated.status_code == 200
    assert validated.json()["stock_changed"] is False
    db_session.expire_all()
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 1
    assert stock_balances(db_session) == {}
    _assert_workshop_unchanged(db_session, isolation)

    invoice_line = db_session.scalar(
        select(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == import_id)
    )
    article_id = invoice_line.article_id
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    airport = db_session.scalar(select(StockLocation).where(StockLocation.code == "AIRPORT"))
    first_receipt = authenticated_client.post(
        f"/api/stock/invoice-imports/{import_id}/receipts",
        json={
            "location_id": workshop.id,
            "lines": [{"invoice_line_id": invoice_line.id, "received_quantity": "4"}],
        },
    )
    assert first_receipt.status_code == 200
    assert first_receipt.json()["status"] == "partial"
    db_session.expire_all()
    assert stock_balances(db_session)[(article_id, workshop.id)] == Decimal("4.000")
    assert stock_balances(db_session).get((article_id, airport.id), Decimal("0")) == 0
    supplier_reference = db_session.scalar(
        select(StockArticleSupplierRef).where(StockArticleSupplierRef.article_id == article_id)
    )
    assert supplier_reference.last_cost == Decimal("10.0000")
    assert supplier_reference.last_purchase_at is not None
    _assert_workshop_unchanged(db_session, isolation)

    missing_responsible = authenticated_client.post(
        f"/api/stock/invoice-imports/{import_id}/receipts",
        json={
            "location_id": airport.id,
            "lines": [{"invoice_line_id": invoice_line.id, "received_quantity": "6"}],
        },
    )
    assert missing_responsible.status_code == 422

    final_receipt = authenticated_client.post(
        f"/api/stock/invoice-imports/{import_id}/receipts",
        json={
            "location_id": airport.id,
            "responsible_name": "Responsável Aeroporto",
            "lines": [{"invoice_line_id": invoice_line.id, "received_quantity": "6"}],
        },
    )
    assert final_receipt.status_code == 200
    assert final_receipt.json()["status"] == "completed"

    for payload in (
        {
            "article_id": article_id,
            "movement_type": "exit",
            "quantity": "1",
            "from_location_id": workshop.id,
            "reason": "Saída manual de teste",
        },
        {
            "article_id": article_id,
            "movement_type": "return",
            "quantity": "1",
            "from_location_id": airport.id,
            "reason": "Devolução ao fornecedor",
        },
        {
            "article_id": article_id,
            "movement_type": "adjustment",
            "quantity": "2",
            "to_location_id": workshop.id,
            "reason": "Acerto inventário contado",
        },
        {
            "article_id": article_id,
            "movement_type": "transfer",
            "quantity": "1",
            "from_location_id": workshop.id,
            "to_location_id": airport.id,
            "reason": "Transferência física",
        },
    ):
        result = authenticated_client.post("/api/stock/movements", json=payload)
        assert result.status_code == 201, result.text
    _assert_workshop_unchanged(db_session, isolation)


def test_known_supplier_reference_is_reused_and_import_is_idempotent(
    authenticated_client, db_session
):
    first_document = _document("first-known-reference", file_hash="b" * 64)
    second_document = _document("second-known-reference", file_hash="c" * 64)
    db_session.add_all([first_document, second_document])
    db_session.commit()
    first = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={
            "document_id": first_document.id,
            "classification": "stock_invoice",
            "extracted_data": {},
        },
    ).json()
    same = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={
            "document_id": first_document.id,
            "classification": "stock_invoice",
            "extracted_data": {},
        },
    ).json()
    assert same["id"] == first["id"]
    assert (
        authenticated_client.post(
            f"/api/stock/invoice-imports/{first['id']}/validate",
            json=_review_payload("REF-1/2026"),
        ).status_code
        == 200
    )
    db_session.expire_all()
    original_line = db_session.scalar(
        select(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == first["id"])
    )

    second = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={
            "document_id": second_document.id,
            "classification": "stock_invoice",
            "extracted_data": {},
        },
    ).json()
    payload = _review_payload("REF-2/2026", create=False)
    validated = authenticated_client.post(
        f"/api/stock/invoice-imports/{second['id']}/validate", json=payload
    )
    assert validated.status_code == 200, validated.text
    db_session.expire_all()
    reused_line = db_session.scalar(
        select(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == second["id"])
    )
    assert reused_line.article_id == original_line.article_id
    assert db_session.scalar(select(func.count()).select_from(StockArticle)) == 1
    assert db_session.scalar(select(func.count()).select_from(StockArticleSupplierRef)) == 1


def test_divergent_totals_stay_in_review_and_create_no_receipt_or_movement(
    authenticated_client, db_session
):
    document = _document("divergent")
    db_session.add(document)
    db_session.commit()
    invoice_import = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice", "extracted_data": {}},
    ).json()
    payload = _review_payload("DIV-1/2026")
    payload["gross_total"] = "200.00"
    response = authenticated_client.post(
        f"/api/stock/invoice-imports/{invoice_import['id']}/validate", json=payload
    )
    assert response.status_code == 422
    db_session.expire_all()
    record = db_session.get(StockInvoiceImport, invoice_import["id"])
    assert record.status == "needs_review"
    assert "Totais divergentes" in record.error_details
    assert db_session.scalar(select(func.count()).select_from(StockReceipt)) == 0
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 0


def test_low_stock_alert_and_movement_immutability(authenticated_client, db_session):
    document = _document("immutable")
    db_session.add(document)
    db_session.commit()
    import_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice", "extracted_data": {}},
    ).json()["id"]
    assert (
        authenticated_client.post(
            f"/api/stock/invoice-imports/{import_id}/validate",
            json=_review_payload("IMM-1/2026"),
        ).status_code
        == 200
    )
    db_session.expire_all()
    line = db_session.scalar(
        select(StockInvoiceLine).where(StockInvoiceLine.invoice_import_id == import_id)
    )
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    assert (
        authenticated_client.post(
            f"/api/stock/invoice-imports/{import_id}/receipts",
            json={
                "location_id": workshop.id,
                "lines": [{"invoice_line_id": line.id, "received_quantity": "2"}],
            },
        ).status_code
        == 200
    )
    db_session.expire_all()
    db_session.add(
        StockMinimum(
            article_id=line.article_id, location_id=workshop.id, minimum_quantity=Decimal("3")
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
        "/v2-clean/stock/invoices",
        "/v2-clean/stock/movements",
    ],
)
def test_clean_stock_pages_render_and_use_responsive_navigation(authenticated_client, path):
    response = authenticated_client.get(path)
    assert response.status_code == 200
    assert 'class="stock-nav"' in response.text
    assert "Stock" in response.text


def test_dispnal_parser_ports_the_tested_importer_fields():
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
    assert Decimal(parsed["lines"][0]["discount"]) == Decimal("0.1")
    assert parsed["lines"][0]["eco_value"] == "1.00"
    assert parsed["lines"][0]["tax_rate"] == "0.23"
