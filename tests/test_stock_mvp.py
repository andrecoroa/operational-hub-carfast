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
from app.services.stock import low_stock_rows, parse_dispnal_invoice, stock_balances


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
