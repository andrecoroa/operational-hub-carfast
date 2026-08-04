from decimal import Decimal

from sqlalchemy import func, select

from app.models.documents import Document
from app.models.stock import (
    StockArticleVehicleCompatibility,
    StockInventorySession,
    StockInvoiceImport,
    StockLocation,
    StockMovement,
    StockPurchaseOrder,
    StockReceipt,
    StockSupplier,
)
from app.models.workshop import WorkshopProcess
from app.services.stock import stock_balances
from app.services.users import create_user


def _article(client, reference: str) -> int:
    response = client.post(
        "/api/stock/articles",
        json={"internal_ref": reference, "name": f"Artigo {reference}", "unit": "un."},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _supplier(db_session, name: str = "Fornecedor Stock Final") -> StockSupplier:
    supplier = StockSupplier(name=name, tax_id=f"TEST-{name[-4:]}", active=True)
    db_session.add(supplier)
    db_session.commit()
    return supplier


def _login(client, email: str, password: str) -> None:
    response = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert response.status_code == 303
    client.post("/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False)


def test_article_table_is_short_and_integer_formatted(authenticated_client):
    article_id = _article(authenticated_client, "SHORT-001")

    response = authenticated_client.get("/v2-clean/stock/articles")

    assert response.status_code == 200
    for heading in (
        "Referência",
        "Designação curta",
        "Categoria",
        "Fornecedor",
        "Disponível",
        "Estado",
    ):
        assert f"<th>{heading}</th>" in response.text
    assert "<th>Custo" not in response.text
    assert "<th>Mínimo" not in response.text
    assert ".000" not in response.text

    detail = authenticated_client.get(f"/v2-clean/stock/articles/{article_id}")
    assert "Referência:" in detail.text
    assert 'value="SHORT-001" readonly' in detail.text
    assert "Descrição detalhada" in detail.text

    orders = authenticated_client.get("/v2-clean/stock/orders")
    assert "<th>Referência</th><th>Descrição</th>" in orders.text
    assert 'data-description="Artigo SHORT-001"' in orders.text


def test_receipt_responsible_is_always_the_authenticated_user(
    authenticated_client, db_session
):
    article_id = _article(authenticated_client, "RESP-LOGIN")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))

    response = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": workshop.id,
            "source_type": "manual",
            "manual_reason": "Entrega de teste",
            "responsible_name": "Nome introduzido pelo cliente",
            "lines": [{"article_id": article_id, "accepted_quantity": 1}],
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["responsible_name"] == "Admin Testes"
    db_session.expire_all()
    receipt = db_session.get(StockReceipt, response.json()["id"])
    assert receipt.responsible_name == "Admin Testes"
    assert receipt.confirmed_by_id is not None

    page = authenticated_client.get("/v2-clean/stock/receipts")
    assert 'value="Admin Testes" readonly' in page.text
    assert 'name="responsible_name"' not in page.text


def test_blind_inventory_html_and_api_do_not_expose_snapshot(authenticated_client, db_session):
    article_id = _article(authenticated_client, "BLIND-001")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    receipt = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": workshop.id,
            "source_type": "manual",
            "manual_reason": "Carga inicial controlada",
            "lines": [{"article_id": article_id, "accepted_quantity": 17, "unit_cost": 2}],
        },
    )
    assert receipt.status_code == 201, receipt.text
    created = authenticated_client.post(
        "/api/stock/inventory-sessions",
        json={"location_id": workshop.id, "idempotency_key": "blind-html-001"},
    )
    inventory_id = created.json()["id"]

    page = authenticated_client.get(f"/v2-clean/stock/inventory/{inventory_id}")
    api = authenticated_client.get(f"/api/stock/inventory-sessions/{inventory_id}")

    assert page.status_code == 200
    assert "Esperado" not in page.text
    assert "Mínimo" not in page.text
    assert "expected_snapshot" not in page.text
    assert "expected_quantity" not in api.text
    assert "difference_quantity" not in api.text


def test_inventory_confirmation_is_idempotent(authenticated_client, db_session):
    article_id = _article(authenticated_client, "IDEMP-COUNT")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    inventory_id = authenticated_client.post(
        "/api/stock/inventory-sessions",
        json={"location_id": workshop.id, "idempotency_key": "inventory-confirm-once"},
    ).json()["id"]
    close = authenticated_client.post(
        f"/api/stock/inventory-sessions/{inventory_id}/counts?close=true",
        json={"counts": [{"article_id": article_id, "counted_quantity": 4}]},
    )
    assert close.status_code == 200, close.text
    payload = {"confirmations": [{"article_id": article_id, "justification": "Contagem assinada"}]}
    first = authenticated_client.post(
        f"/api/stock/inventory-sessions/{inventory_id}/confirm", json=payload
    )
    second = authenticated_client.post(
        f"/api/stock/inventory-sessions/{inventory_id}/confirm", json=payload
    )

    assert first.status_code == second.status_code == 200
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == 1
    assert stock_balances(db_session)[(article_id, workshop.id)] == Decimal("4.000")


def test_purchase_order_partial_then_total_receipt(authenticated_client, db_session):
    article_id = _article(authenticated_client, "ORDER-001")
    supplier = _supplier(db_session)
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    order_response = authenticated_client.post(
        "/api/stock/purchase-orders",
        json={
            "supplier_id": supplier.id,
            "commercial_status": "confirmed",
            "lines": [
                {
                    "article_id": article_id,
                    "supplier_ref": "SUP-ORDER-001",
                    "quantity": 5,
                    "unit": "un.",
                    "unit_price": "12.34",
                    "location_id": workshop.id,
                }
            ],
        },
    )
    assert order_response.status_code == 201, order_response.text
    order_id = order_response.json()["id"]
    order_line_id = authenticated_client.get(f"/api/stock/purchase-orders/{order_id}").json()[
        "lines"
    ][0]["id"]

    def receive(quantity: int, reference: str):
        return authenticated_client.post(
            "/api/stock/receipts",
            json={
                "supplier_id": supplier.id,
                "location_id": workshop.id,
                "purchase_order_id": order_id,
                "source_type": "delivery_note",
                "source_reference": reference,
                "idempotency_key": reference,
                "lines": [
                    {
                        "article_id": article_id,
                        "purchase_order_line_id": order_line_id,
                        "supplier_ref": "SUP-ORDER-001",
                        "accepted_quantity": quantity,
                        "unit_cost": "12.34",
                    }
                ],
            },
        )

    assert receive(2, "GT-PART-1").status_code == 201
    db_session.expire_all()
    assert db_session.get(StockPurchaseOrder, order_id).receiving_status == "partial"
    assert receive(3, "GT-PART-2").status_code == 201
    db_session.expire_all()
    assert db_session.get(StockPurchaseOrder, order_id).receiving_status == "complete"
    assert stock_balances(db_session)[(article_id, workshop.id)] == Decimal("5.000")


def test_workshop_evidence_confirms_never_validates_or_mutates_workshop(
    authenticated_client, db_session
):
    article_id = _article(authenticated_client, "COMPAT-001")
    before = db_session.scalar(select(func.count()).select_from(WorkshopProcess))
    payload = {
        "article_id": article_id,
        "brand": "Peugeot",
        "model": "208",
        "version": "II",
        "engine": "1.2 PureTech",
        "generation_period": "2019–",
        "workshop_process_reference": "OF-2026-001",
    }

    first = authenticated_client.post("/api/stock/compatibilities/workshop-evidence", json=payload)
    second = authenticated_client.post("/api/stock/compatibilities/workshop-evidence", json=payload)

    assert first.status_code == second.status_code == 201
    assert first.json()["status"] == "confirmed"
    assert first.json()["automatically_validated"] is False
    assert first.json()["id"] == second.json()["id"]
    assert (
        db_session.scalar(select(func.count()).select_from(StockArticleVehicleCompatibility)) == 1
    )
    assert db_session.scalar(select(func.count()).select_from(WorkshopProcess)) == before


def test_conference_listing_lazy_loads_document_only_in_modal(authenticated_client, db_session):
    document = Document(
        title="Fatura modal",
        document_type="workshop_supplier_invoice",
        classification="invoice",
        source="stock_test",
        entry_channel="stock",
        original_name="modal.pdf",
        file_name="modal.pdf",
        storage_provider="local",
        storage_path="Stock/modal.pdf",
        status="received",
    )
    db_session.add(document)
    db_session.commit()
    invoice_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()["id"]
    invoice_import = db_session.get(StockInvoiceImport, invoice_id)
    invoice_import.raw_extraction_json = {
        "supplier_name": "Fornecedor extraído",
        "invoice_number": "FT-EXTRAIDA-1",
        "invoice_date": "2026-08-03",
        "gross_total": "27.68",
        "lines": [
            {
                "line_number": 1,
                "supplier_ref": "REF-MODAL",
                "description": "Artigo extraído",
                "quantity": "2",
                "unit": "un.",
                "unit_cost": "12.50",
                "discount": "0.10",
                "tax_rate": "0.23",
                "line_total": "27.68",
            }
        ]
    }
    db_session.commit()

    listing = authenticated_client.get("/v2-clean/stock/invoices")
    modal = authenticated_client.get(f"/v2-clean/stock/invoices/{invoice_id}/modal")
    invoice_import = db_session.get(StockInvoiceImport, invoice_id)
    invoice_import.status = "validated"
    db_session.commit()
    review = authenticated_client.get(f"/v2-clean/stock/invoices/{invoice_id}")

    assert "<iframe" not in listing.text
    assert "Ver e conferir" in listing.text
    assert "<iframe" in modal.text
    assert f"/v2-clean/stock/invoices/{invoice_id}/document" in modal.text
    assert "REF-MODAL" in modal.text
    assert "12.50 €" in modal.text
    assert "27.68 €" in modal.text
    assert "Fornecedor extraído" in modal.text
    assert "FT-EXTRAIDA-1" in modal.text
    assert "03/08/2026" in modal.text
    assert "Referência</th><th>Descrição" in modal.text
    assert "navpanes=0" in modal.text
    assert "Rever extração e validar artigos" in modal.text
    responsible_field = review.text.split("Responsável pela receção", 1)[1].split("</label>", 1)[0]
    assert "Admin Testes" in responsible_field
    assert "readonly" in responsible_field
    assert "name=" not in responsible_field


def test_validated_invoice_is_pending_until_a_physical_receipt(
    authenticated_client, db_session
):
    supplier = _supplier(db_session)
    document = Document(
        title="Fatura a receber",
        document_type="workshop_supplier_invoice",
        classification="invoice",
        source="stock_test",
        entry_channel="stock",
        original_name="pending-receipt.pdf",
        file_name="pending-receipt.pdf",
        storage_provider="local",
        storage_path="Stock/pending-receipt.pdf",
        status="received",
    )
    db_session.add(document)
    db_session.commit()
    invoice_id = authenticated_client.post(
        "/api/stock/invoice-imports",
        json={"document_id": document.id, "classification": "stock_invoice"},
    ).json()["id"]
    invoice = db_session.get(StockInvoiceImport, invoice_id)
    invoice.supplier_id = supplier.id
    invoice.invoice_number = "FT-PENDING-1"
    invoice.status = "validated"
    invoice.conference_status = "conferred"
    db_session.commit()

    pending = authenticated_client.get(
        f"/api/stock/pending-sources?supplier_id={supplier.id}"
    )
    page = authenticated_client.get("/v2-clean/stock/receipts")

    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()["invoices"]] == [invoice_id]
    assert "FT-PENDING-1" in page.text
    assert "Preparar receção" in page.text


def test_fractional_quantities_are_rejected(authenticated_client, db_session):
    article_id = _article(authenticated_client, "INTEGER-ONLY")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    response = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": workshop.id,
            "source_type": "manual",
            "manual_reason": "Teste de validação",
            "lines": [{"article_id": article_id, "accepted_quantity": "1.5"}],
        },
    )
    assert response.status_code == 422
    assert "inteiras" in response.text


def test_operator_can_count_but_cannot_confirm_inventory(client, db_session):
    email = "stock.operator.final@carfast.local"
    password = "Secret123!"
    create_user(
        db_session,
        name="Operador Stock Final",
        email=email,
        password=password,
        role_codes=["operator"],
        organizational_unit_codes=["stock"],
    )
    db_session.commit()
    _login(client, email, password)
    article_id = _article(client, "AUTH-COUNT")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    created = client.post("/api/stock/inventory-sessions", json={"location_id": workshop.id})
    assert created.status_code == 201, created.text
    inventory_id = created.json()["id"]
    assert (
        client.post(
            f"/api/stock/inventory-sessions/{inventory_id}/counts?close=true",
            json={"counts": [{"article_id": article_id, "counted_quantity": 1}]},
        ).status_code
        == 200
    )

    forbidden = client.post(
        f"/api/stock/inventory-sessions/{inventory_id}/confirm",
        json={"confirmations": [{"article_id": article_id, "justification": "Teste"}]},
    )

    assert forbidden.status_code == 403
    assert db_session.get(StockInventorySession, inventory_id).status == "review"
