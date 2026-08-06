from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from app.models.documents import Document
from app.models.stock import (
    StockArticle,
    StockArticleSupplierRef,
    StockArticleVehicleCompatibility,
    StockCategory,
    StockInventoryCount,
    StockInventorySession,
    StockInvoiceImport,
    StockInvoiceLine,
    StockLocation,
    StockMovement,
    StockPurchaseOrder,
    StockReceipt,
    StockReceiptInvoiceLink,
    StockSupplier,
)
from app.models.workshop import WorkshopProcess
from app.models.workshop_phased import WorkshopMaterialNeed, WorkshopPhasedProcess
from app.models.vehicles import Vehicle
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


def test_workshop_request_only_moves_stock_when_delivery_is_confirmed(
    authenticated_client, db_session
):
    vehicle = Vehicle(plate="ST-10-CK", active=True, lifecycle_status="active")
    article = StockArticle(internal_ref="WORK-001", name="Filtro oficina", unit="un.")
    location = StockLocation(code="WORKSHOP-TEST", name="Oficina teste", active=True)
    db_session.add_all([vehicle, article, location])
    db_session.flush()
    process = WorkshopPhasedProcess(
        process_type="workshop",
        title="Reparação ST-10-CK",
        creation_mode="operational",
        status="open",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="reparacao",
        priority="normal",
        initial_km=54321,
        metadata_json={},
    )
    db_session.add(process)
    db_session.add(
        StockMovement(
            article_id=article.id,
            movement_type="entry",
            quantity=Decimal("5"),
            unit="un.",
            to_location_id=location.id,
            reason="Stock inicial de teste",
            effective_date=date.today(),
        )
    )
    db_session.commit()

    created = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/material-needs",
        data={"article_id": str(article.id), f"quantity_{article.id}": "2", "origin": "repair"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    need = db_session.scalar(
        select(WorkshopMaterialNeed).where(WorkshopMaterialNeed.process_id == process.id)
    )
    assert need is not None and need.stock_status == "requested"
    assert db_session.scalar(select(func.count(StockMovement.id))) == 1
    db_session.refresh(process)
    assert (process.current_phase_code, process.initial_km, process.status) == (
        "reparacao",
        54321,
        "open",
    )

    queue = authenticated_client.get("/v2-clean/stock/workshop-requests")
    assert queue.status_code == 200
    assert need.stock_request_reference in queue.text
    assert "Filtro oficina" in queue.text

    delivered = authenticated_client.post(
        f"/v2-clean/stock/workshop-requests/{need.stock_request_reference}/deliver",
        data={"location_id": str(location.id)},
        follow_redirects=False,
    )
    assert delivered.status_code == 303
    db_session.expire_all()
    assert db_session.scalar(select(func.count(StockMovement.id))) == 2
    assert db_session.get(WorkshopMaterialNeed, need.id).stock_status == "delivered"
    assert stock_balances(db_session)[(article.id, location.id)] == Decimal("3.000")

    authenticated_client.post(
        f"/v2-clean/stock/workshop-requests/{need.stock_request_reference}/deliver",
        data={"location_id": str(location.id)},
        follow_redirects=False,
    )
    assert db_session.scalar(select(func.count(StockMovement.id))) == 2
    db_session.refresh(process)
    assert (process.current_phase_code, process.initial_km, process.status) == (
        "reparacao",
        54321,
        "open",
    )


def test_article_table_is_short_and_integer_formatted(authenticated_client):
    article_id = _article(authenticated_client, "SHORT-001")

    response = authenticated_client.get("/v2-clean/stock/articles")

    assert response.status_code == 200
    assert '<th class="stock-reference-column">Referência</th>' in response.text
    for heading in ("Designação curta", "Categoria", "Fornecedor", "Disponível", "Estado"):
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
    assert "Artigos do fornecedor" in orders.text
    assert "Seleciona primeiro o fornecedor" in orders.text


def test_article_table_separates_and_sorts_tyre_measure_only_in_tyre_view(
    authenticated_client, db_session
):
    tyre_category = StockCategory(code="tyres-table", name="Pneus", active=True)
    other_category = StockCategory(code="parts-table", name="Peças", active=True)
    db_session.add_all([tyre_category, other_category])
    db_session.flush()
    articles = [
        StockArticle(
            internal_ref="TYRE-195",
            name="195/55R16 87V AQUILA PRO PNEU",
            category_id=tyre_category.id,
            unit="un.",
        ),
        StockArticle(
            internal_ref="TYRE-185",
            name="185/65R15 XL 92V QUATRAC VREDESTEIN",
            category_id=tyre_category.id,
            unit="un.",
        ),
        StockArticle(
            internal_ref="PART-001",
            name="Filtro de óleo",
            category_id=other_category.id,
            unit="un.",
        ),
    ]
    db_session.add_all(articles)
    db_session.commit()

    tyre_page = authenticated_client.get(
        f"/v2-clean/stock/articles?category_id={tyre_category.id}&availability=all"
    )
    assert tyre_page.status_code == 200
    assert "<th class=\"stock-tyre-measure-column\">Medida</th>" in tyre_page.text
    assert "Marca / modelo" in tyre_page.text
    assert "185/65 R15 92V XL" in tyre_page.text
    assert "QUATRAC VREDESTEIN" in tyre_page.text
    assert tyre_page.text.index("TYRE-185") < tyre_page.text.index("TYRE-195")

    mixed_page = authenticated_client.get("/v2-clean/stock/articles?availability=all")
    assert mixed_page.status_code == 200
    assert "Designação curta" in mixed_page.text
    assert "Filtro de óleo" in mixed_page.text
    assert "stock-tyre-measure-column\">Medida" not in mixed_page.text


def test_article_table_defaults_to_articles_with_available_stock(
    authenticated_client, db_session
):
    available_id = _article(authenticated_client, "AVAILABLE-001")
    empty_id = _article(authenticated_client, "EMPTY-001")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    receipt = authenticated_client.post(
        "/api/stock/receipts",
        json={
            "location_id": workshop.id,
            "source_type": "manual",
            "manual_reason": "Teste de disponibilidade",
            "lines": [{"article_id": available_id, "accepted_quantity": 2}],
        },
    )
    assert receipt.status_code == 201

    default_page = authenticated_client.get("/v2-clean/stock/articles")
    all_page = authenticated_client.get("/v2-clean/stock/articles?availability=all")

    assert 'value="in_stock" selected' in default_page.text
    assert "AVAILABLE-001" in default_page.text
    assert "EMPTY-001" not in default_page.text
    assert "AVAILABLE-001" in all_page.text
    assert "EMPTY-001" in all_page.text


def test_articles_can_be_classified_in_bulk(authenticated_client, db_session):
    first_id = _article(authenticated_client, "BULK-CAT-1")
    second_id = _article(authenticated_client, "BULK-CAT-2")
    category = StockCategory(code="bulk-test", name="Categoria em lote", active=True)
    db_session.add(category)
    db_session.commit()

    response = authenticated_client.post(
        "/v2-clean/stock/articles/bulk-category",
        data={
            "article_ids": [str(first_id), str(second_id)],
            "category_id": str(category.id),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "bulk_updated=2" in response.headers["location"]
    db_session.expire_all()
    assert db_session.get(StockArticle, first_id).category_id == category.id
    assert db_session.get(StockArticle, second_id).category_id == category.id


def test_order_catalog_is_supplier_specific_and_can_create_article(
    authenticated_client, db_session
):
    supplier = _supplier(db_session, "Fornecedor Encomenda A")
    other_supplier = _supplier(db_session, "Fornecedor Encomenda B")
    linked_id = _article(authenticated_client, "ORDER-LINKED")
    hidden_id = _article(authenticated_client, "ORDER-HIDDEN")
    category = StockCategory(code="order-filters", name="Filtros", active=True)
    db_session.add(category)
    db_session.flush()
    db_session.get(StockArticle, linked_id).category_id = category.id
    db_session.add_all(
        [
            StockArticleSupplierRef(
                article_id=linked_id,
                supplier_id=supplier.id,
                supplier_ref="REF-A",
                supplier_description="Artigo ligado",
                preferred=True,
            ),
            StockArticleSupplierRef(
                article_id=hidden_id,
                supplier_id=other_supplier.id,
                supplier_ref="REF-B",
                supplier_description="Artigo de outro fornecedor",
                preferred=True,
            ),
        ]
    )
    db_session.commit()
    page = authenticated_client.get("/v2-clean/stock/orders")
    assert "Artigo ORDER-LINKED" in page.text
    assert "REF-A" in page.text
    assert "Pesquisar referência ou descrição" in page.text
    assert "Categorias" in page.text
    assert "<th>Categoria</th>" in page.text
    assert '"category": "Filtros"' in page.text

    workshop = db_session.scalar(
        select(StockLocation).where(StockLocation.code == "WORKSHOP")
    )
    response = authenticated_client.post(
        "/v2-clean/stock/orders",
        data={
            "supplier_id": str(supplier.id),
            "commercial_status": "draft",
            "new_internal_ref": "CREATED-IN-ORDER",
            "new_name": "Artigo criado na encomenda",
            "new_supplier_ref": "SUP-CREATED",
            "new_quantity": "3",
            "new_unit": "un.",
            "new_unit_price": "12.50",
            "new_location_id": str(workshop.id),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    created = db_session.scalar(
        select(StockArticle).where(StockArticle.internal_ref == "CREATED-IN-ORDER")
    )
    assert created is not None
    assert created.primary_supplier_id == supplier.id
    assert db_session.scalar(
        select(StockArticleSupplierRef).where(
            StockArticleSupplierRef.article_id == created.id,
            StockArticleSupplierRef.supplier_id == supplier.id,
        )
    ) is not None


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
    category = StockCategory(name="Filtros inventário", code="INV-FILTERS", active=True)
    db_session.add(category)
    db_session.flush()
    db_session.get(StockArticle, article_id).category_id = category.id
    db_session.commit()
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
    assert "Categorias" in page.text
    assert "Filtros inventário" in page.text
    assert 'data-inventory-category-filter' in page.text
    assert 'data-close-inventory' in page.text


def test_inventory_draft_can_be_partial_and_session_can_target_one_category(
    authenticated_client, db_session
):
    counted_id = _article(authenticated_client, "CATEGORY-COUNTED")
    excluded_id = _article(authenticated_client, "CATEGORY-EXCLUDED")
    counted_category = StockCategory(name="Categoria contada", code="COUNTED", active=True)
    excluded_category = StockCategory(name="Categoria excluída", code="EXCLUDED", active=True)
    db_session.add_all([counted_category, excluded_category])
    db_session.flush()
    db_session.get(StockArticle, counted_id).category_id = counted_category.id
    db_session.get(StockArticle, excluded_id).category_id = excluded_category.id
    db_session.commit()
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))

    inventory_page = authenticated_client.get("/v2-clean/stock/inventory")
    assert inventory_page.status_code == 200
    assert f'<option value="{counted_category.id}">Categoria contada</option>' in (
        inventory_page.text
    )
    assert f'<option value="{excluded_category.id}">Categoria excluída</option>' in (
        inventory_page.text
    )

    created = authenticated_client.post(
        "/v2-clean/stock/inventory",
        data={
            "location_id": workshop.id,
            "category_id": counted_category.id,
            "idempotency_key": "category-draft-001",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    inventory_id = int(created.headers["location"].rstrip("/").split("/")[-1])
    snapshot_ids = set(
        db_session.scalars(
            select(StockInventoryCount.article_id).where(
                StockInventoryCount.session_id == inventory_id
            )
        ).all()
    )
    assert snapshot_ids == {counted_id}

    page = authenticated_client.get(f"/v2-clean/stock/inventory/{inventory_id}")
    assert 'formnovalidate' in page.text
    assert 'name="counted_quantity"' in page.text
    assert 'name="counted_quantity" type="number"' in page.text
    assert 'type="number" min="0" step="1"' in page.text
    assert 'step="1" value="" required' not in page.text

    saved = authenticated_client.post(
        f"/v2-clean/stock/inventory/{inventory_id}/counts",
        data={"action": "save"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    db_session.expire_all()
    assert db_session.get(StockInventorySession, inventory_id).status == "counting"


def test_inventory_can_be_cancelled_then_archived_without_movements(
    authenticated_client, db_session
):
    _article(authenticated_client, "CANCEL-INVENTORY")
    workshop = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    created = authenticated_client.post(
        "/v2-clean/stock/inventory",
        data={"location_id": workshop.id, "idempotency_key": "cancel-inventory-001"},
        follow_redirects=False,
    )
    inventory_id = int(created.headers["location"].rstrip("/").split("/")[-1])
    movements_before = db_session.scalar(select(func.count()).select_from(StockMovement))

    cancelled = authenticated_client.post(
        f"/v2-clean/stock/inventory/{inventory_id}/cancel",
        data={"reason": "Sessão criada por engano"},
        follow_redirects=False,
    )
    db_session.expire_all()
    assert cancelled.status_code == 303
    assert db_session.get(StockInventorySession, inventory_id).status == "cancelled"
    assert db_session.scalar(select(func.count()).select_from(StockMovement)) == movements_before

    archived = authenticated_client.post(
        f"/v2-clean/stock/inventory/{inventory_id}/archive", follow_redirects=False
    )
    db_session.expire_all()
    assert archived.status_code == 303
    assert db_session.get(StockInventorySession, inventory_id).status == "archived_cancelled"
    assert f"#{inventory_id}" not in authenticated_client.get(
        "/v2-clean/stock/inventory"
    ).text
    assert f"#{inventory_id}" in authenticated_client.get(
        "/v2-clean/stock/inventory?scope=archived"
    ).text


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


def test_stock_invoice_removal_is_logical_and_blocked_after_receipt(
    authenticated_client, db_session
):
    removable_document = Document(
        title="Fatura removível",
        document_type="finance_supplier_invoice",
        classification="finance",
        source="stock_test",
        entry_channel="stock",
        original_name="removable.pdf",
        file_name="removable.pdf",
        storage_provider="local",
        storage_path="Stock/removable.pdf",
        status="received",
    )
    linked_document = Document(
        title="Fatura ligada",
        document_type="finance_supplier_invoice",
        classification="finance",
        source="stock_test",
        entry_channel="stock",
        original_name="linked.pdf",
        file_name="linked.pdf",
        storage_provider="local",
        storage_path="Stock/linked.pdf",
        status="received",
    )
    db_session.add_all([removable_document, linked_document])
    db_session.flush()
    removable = StockInvoiceImport(document_id=removable_document.id, status="needs_review")
    linked = StockInvoiceImport(document_id=linked_document.id, status="needs_review")
    db_session.add_all([removable, linked])
    db_session.flush()
    location = db_session.scalar(select(StockLocation).where(StockLocation.code == "WORKSHOP"))
    receipt = StockReceipt(
        location_id=location.id,
        source_type="manual",
        manual_reason="Receção já confirmada",
        status="completed",
    )
    db_session.add(receipt)
    db_session.flush()
    db_session.add(
        StockReceiptInvoiceLink(receipt_id=receipt.id, invoice_import_id=linked.id)
    )
    db_session.commit()

    removed = authenticated_client.post(
        f"/v2-clean/stock/invoices/{removable.id}/remove",
        data={"reason": "Documento duplicado"},
        follow_redirects=False,
    )
    blocked = authenticated_client.post(
        f"/v2-clean/stock/invoices/{linked.id}/remove",
        data={"reason": "Tentativa indevida"},
        follow_redirects=False,
    )
    db_session.expire_all()

    assert removed.status_code == blocked.status_code == 303
    assert db_session.get(StockInvoiceImport, removable.id).status == "cancelled"
    assert db_session.get(Document, removable_document.id).status == "removed"
    assert "invoice_has_receipts" in blocked.headers["location"]
    assert db_session.get(StockInvoiceImport, linked.id).status == "needs_review"


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
    db_session.add(
        StockInvoiceLine(
            invoice_import_id=invoice.id,
            line_number=1,
            supplier_ref="REF-PENDING",
            description="Artigo pendente de receção",
            quantity=Decimal("2"),
            unit="un.",
            unit_cost=Decimal("10"),
            discount=Decimal("0"),
            eco_value=Decimal("0"),
            tax_rate=Decimal("0.23"),
            line_total=Decimal("20"),
        )
    )
    db_session.commit()

    pending = authenticated_client.get(
        f"/api/stock/pending-sources?supplier_id={supplier.id}"
    )
    page = authenticated_client.get("/v2-clean/stock/receipts")

    assert pending.status_code == 200
    assert [item["id"] for item in pending.json()["invoices"]] == [invoice_id]
    assert "FT-PENDING-1" in page.text
    assert "1 artigos" in page.text
    assert "Validar artigos e receber" in page.text
    assert f'/v2-clean/stock/invoices/{invoice_id}#stock-receipt-lines' in page.text


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
