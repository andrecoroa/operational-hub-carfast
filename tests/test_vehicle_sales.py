from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import select

import app.web.router as base_router
from app.core.config import settings
from app.models import (
    AuditLog,
    Vehicle,
    VehicleExternalSnapshot,
    VehicleFinancialPlan,
    VehicleImage,
    VehicleManualField,
    VehicleSaleLead,
    VehicleSaleProfile,
    VehicleSalePublication,
)
from app.services.users import create_user
from app.web.vehicle_sales import _filter_rows, _sale_row, compact_finance_entity


def test_compact_finance_entity_labels():
    assert compact_finance_entity("Caixa Geral de Depósitos, S.A.") == "CGD"
    assert compact_finance_entity("Santander Consumer Finance") == "Santander"
    assert compact_finance_entity("Banco BPI, S.A.") == "BPI"
    assert compact_finance_entity("CGD Locação Corrente") == "CGD Locação"
    assert compact_finance_entity("LeasePlan Portugal") == "LeasePlan"
    assert compact_finance_entity("Mercedes-Benz Financial") == "Mercedes"


def test_cgd_filter_includes_all_cgd_name_variants():
    rows = []
    for entity in ("CGD", "Caixa Geral de Depósitos, S.A."):
        rows.append(
            {
                "vehicle": SimpleNamespace(
                    plate=entity,
                    rentway_unit_nr=None,
                    vin=None,
                    brand=None,
                    model=None,
                ),
                "finance_entity": entity,
                "finance_entity_key": compact_finance_entity(entity).casefold(),
                "status": "candidate",
                "vehicle_state": "free",
                "registration": None,
                "return_on": None,
                "financial_margin": None,
                "commercial_margin": None,
                "market_trade": None,
                "market_retail": None,
            }
        )
    filters = {
        "q": "",
        "sale_status": "",
        "finance_entity": "CGD",
        "vehicle_state": "",
        "registration_from": "",
        "registration_to": "",
        "return_from": "",
        "return_to": "",
        "financial_margin_min": "",
        "financial_margin_max": "",
        "commercial_margin_min": "",
        "commercial_margin_max": "",
        "market_state": "",
    }

    assert len(_filter_rows(rows, filters)) == 2


def test_unfinanced_vehicle_ignores_legacy_manual_debt():
    vehicle = Vehicle(
        plate="BS-13-UU",
        brand="Mercedes",
        model="Classe A",
        operational_status="active",
        lifecycle_status="active",
        active=True,
    )
    snapshot = VehicleExternalSnapshot(
        data_json={
            "purchase_date": "2025-04-30",
            "acquisition_value": "30.902,40",
            "value_with_tax": "38.010,00",
        }
    )

    row = _sale_row(
        vehicle,
        snapshot,
        {"debt_value": "36.982,78"},
        None,
        None,
    )

    assert row["debt"] is None
    assert row["financial_margin"] is None


def create_sale_vehicle(db_session) -> Vehicle:
    vehicle = Vehicle(
        plate="12-AB-34",
        vin="VF3TESTVEHICLE0001",
        rentway_unit_nr="UNIT123",
        brand="Peugeot",
        model="3008",
        version="1.5 BlueHDi",
        year=2022,
        lifecycle_status="active",
        operational_status="in_contract",
        active=True,
    )
    db_session.add(vehicle)
    db_session.flush()
    db_session.add(
        VehicleExternalSnapshot(
            vehicle_id=vehicle.id,
            source_system="rentway",
            data_json={
                "plate_date": "2022-01-15",
                "purchase_date": "2026-07-01",
                "acquisition_value": "15609.76",
                "value_with_tax": "19200",
                "km": "98450",
                "current_status": "Contrato",
                "document_nr": "CONT-100",
                "return_date": "2026-10-18",
                "finance_entity": "Santander",
            },
        )
    )
    db_session.add_all(
        [
            VehicleManualField(
                vehicle_id=vehicle.id,
                field_code="finance_entity",
                value_json="Santander",
            ),
            VehicleManualField(
                vehicle_id=vehicle.id,
                field_code="debt_value",
                value_json="15000",
            ),
        ]
    )
    db_session.add(
        VehicleFinancialPlan(
            vehicle_id=vehicle.id,
            finance_entity="Santander",
            contract_number="CONT-100",
            outstanding_amount=Decimal("15000"),
            active=True,
        )
    )
    db_session.commit()
    return vehicle


def test_vehicle_sales_filters_bulk_values_and_price_rule(authenticated_client, db_session):
    vehicle = create_sale_vehicle(db_session)

    page = authenticated_client.get(
        "/v2-clean/fleet/sales",
        params={
            "finance_entity": "Santander",
            "vehicle_state": "contract",
            "registration_from": "2022-01-01",
            "registration_to": "2022-12-31",
            "return_from": "2026-10-01",
            "return_to": "2026-10-31",
            "financial_margin_min": "400",
        },
    )
    assert page.status_code == 200
    assert "Venda de viaturas" in page.text
    assert "12-AB-34" in page.text
    assert "Dev. 18/10/2026" in page.text
    assert "Custo CarFast − valor em dívida" in page.text
    assert "Valor comércio − custo CarFast" in page.text

    values = authenticated_client.post(
        "/v2-clean/fleet/sales/bulk",
        data={
            "vehicle_ids": [str(vehicle.id)],
            "action": "market_values",
            "market_trade_value": "21000",
            "market_retail_value": "25200",
            "market_value_source": "Avaliação interna",
            "return_url": "/v2-clean/fleet/sales",
        },
        follow_redirects=False,
    )
    assert values.status_code == 303

    rule = authenticated_client.post(
        "/v2-clean/fleet/sales/bulk",
        data={
            "vehicle_ids": [str(vehicle.id)],
            "action": "price_rule",
            "price_base": "trade",
            "margin_mode": "percentage",
            "margin_value": "5",
            "rounding_mode": "up",
            "rounding_increment": "100",
            "return_url": "/v2-clean/fleet/sales",
        },
        follow_redirects=False,
    )
    assert rule.status_code == 303

    status = authenticated_client.post(
        "/v2-clean/fleet/sales/bulk",
        data={
            "vehicle_ids": [str(vehicle.id)],
            "action": "status",
            "bulk_status": "reserved",
            "return_url": "/v2-clean/fleet/sales",
        },
        follow_redirects=False,
    )
    assert status.status_code == 303

    db_session.expire_all()
    profile = db_session.scalar(
        select(VehicleSaleProfile).where(VehicleSaleProfile.vehicle_id == vehicle.id)
    )
    assert profile is not None
    assert profile.status == "reserved"
    assert profile.market_trade_value == Decimal("21000.00")
    assert profile.market_retail_value == Decimal("25200.00")
    assert profile.selling_price == Decimal("22100.00")
    assert profile.market_value_source == "Avaliação interna"
    assert profile.market_valued_on == date.today()
    assert (
        db_session.scalar(select(AuditLog).where(AuditLog.action == "vehicle.sale.bulk_price_rule"))
        is not None
    )


def test_vehicle_financial_audit_exports_missing_fields_and_latest_rentway_cost(
    authenticated_client,
    db_session,
):
    vehicle = create_sale_vehicle(db_session)
    db_session.add(
        VehicleFinancialPlan(
            vehicle_id=vehicle.id,
            finance_entity="Santander",
            contract_number="FIN-123",
            start_date=date(2026, 7, 1),
            installment_with_vat=Decimal("325.03"),
            outstanding_amount=Decimal("10000"),
            active=True,
        )
    )
    db_session.commit()

    response = authenticated_client.get("/v2-clean/fleet/financial-audit.csv")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "12-AB-34" in response.text
    assert "19200" in response.text
    assert "FIN-123" in response.text
    assert "fim" in response.text
    assert "valor residual" in response.text


def test_vehicle_sale_images_public_snapshot_and_leads(
    authenticated_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(settings, "vehicle_sale_media_root", str(tmp_path))
    base_router.EXTERNAL_PORTAL_RATE_LIMIT.clear()
    vehicle = create_sale_vehicle(db_session)

    saved = authenticated_client.post(
        f"/v2-clean/fleet/sales/{vehicle.id}",
        data={
            "status": "for_sale",
            "market_trade_value": "21000",
            "market_retail_value": "25200",
            "selling_price": "24900",
            "market_value_source": "Avaliação interna",
            "market_valued_on": "2026-07-31",
            "price_base": "retail",
            "margin_mode": "value",
            "margin_value": "-300",
            "rounding_mode": "nearest",
            "rounding_increment": "100",
            "sale_notes": "Nota interna confidencial sobre custo e preparação.",
            "public_notes": "Viatura revista, disponível para entrega.",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    detail = authenticated_client.get(f"/v2-clean/fleet/sales/{vehicle.id}")
    assert detail.status_code == 200
    assert "Nota interna confidencial" in detail.text
    assert "Galeria permanente" in detail.text

    png = b"\x89PNG\r\n\x1a\n" + b"carfast-test-image"
    uploaded = authenticated_client.post(
        f"/v2-clean/fleet/sales/{vehicle.id}/images",
        data={"category": "exterior", "caption": "Vista dianteira"},
        files={"image": ("frente.png", png, "image/png")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303
    db_session.expire_all()
    image = db_session.scalar(select(VehicleImage).where(VehicleImage.vehicle_id == vehicle.id))
    assert image is not None
    assert image.category == "exterior"
    assert (tmp_path / image.storage_path).is_file()

    published = authenticated_client.post(
        f"/v2-clean/fleet/sales/{vehicle.id}/publish",
        data={
            "audience": "retail",
            "expires_on": "2026-12-31",
            "image_ids": [str(image.id)],
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    db_session.expire_all()
    publication = db_session.scalar(
        select(VehicleSalePublication).where(VehicleSalePublication.vehicle_id == vehicle.id)
    )
    assert publication is not None
    assert publication.snapshot_json["sale"]["price"] == "24900.00"
    serialized_snapshot = str(publication.snapshot_json)
    assert "debt" not in serialized_snapshot
    assert "margin" not in serialized_snapshot
    assert "Nota interna confidencial" not in serialized_snapshot
    internal_page = authenticated_client.get(f"/v2-clean/fleet/sales/{vehicle.id}")
    assert internal_page.status_code == 200
    assert publication.token in internal_page.text

    public_page = authenticated_client.get(f"/portal/viaturas/{publication.token}")
    assert public_page.status_code == 200
    assert "Peugeot 3008" in public_page.text
    assert "Viatura revista, disponível para entrega." in public_page.text
    assert "24 900,00 €" in public_page.text
    assert "Custo CarFast" not in public_page.text
    assert "Valor em dívida" not in public_page.text
    assert "Nota interna confidencial" not in public_page.text

    archived_image = authenticated_client.post(
        f"/v2-clean/fleet/sales/{vehicle.id}/images/{image.id}/archive",
        follow_redirects=False,
    )
    assert archived_image.status_code == 303
    public_image = authenticated_client.get(
        f"/portal/viaturas/{publication.token}/imagens/{image.id}"
    )
    assert public_image.status_code == 200
    assert public_image.content == png

    question = authenticated_client.post(
        f"/portal/viaturas/{publication.token}/interesse",
        data={
            "kind": "question",
            "name": "Cliente Externo",
            "email": "cliente@example.com",
            "message": "A viatura tem segunda chave?",
            "consent": "1",
        },
        follow_redirects=False,
    )
    assert question.status_code == 303
    assert "sent=1" in question.headers["location"]

    offer = authenticated_client.post(
        f"/portal/viaturas/{publication.token}/interesse",
        data={
            "kind": "offer",
            "name": "Comerciante",
            "phone": "910000000",
            "buyer_company": "Comércio Auto, Lda.",
            "offer_value": "23500",
            "message": "Proposta válida durante cinco dias.",
            "consent": "1",
        },
        follow_redirects=False,
    )
    assert offer.status_code == 303

    purchase = authenticated_client.post(
        f"/portal/viaturas/{publication.token}/interesse",
        data={
            "kind": "purchase",
            "name": "Comprador Final",
            "email": "comprador@example.com",
            "message": "Pretendo avançar com o pedido de compra.",
            "consent": "1",
        },
        follow_redirects=False,
    )
    assert purchase.status_code == 303

    db_session.expire_all()
    leads = db_session.scalars(
        select(VehicleSaleLead).where(VehicleSaleLead.vehicle_id == vehicle.id)
    ).all()
    assert {lead.kind for lead in leads} == {"question", "offer", "purchase"}
    assert next(lead for lead in leads if lead.kind == "offer").offer_value == Decimal("23500.00")

    revoked = authenticated_client.post(
        f"/v2-clean/fleet/sales/{vehicle.id}/publications/{publication.id}/revoke",
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    unavailable = authenticated_client.get(f"/portal/viaturas/{publication.token}")
    assert unavailable.status_code == 410
    assert "Link indisponível" in unavailable.text


def test_vehicle_sale_internal_routes_require_authentication(client):
    response = client.get("/v2-clean/fleet/sales", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_vehicle_sales_financial_data_requires_management_permission(client, db_session):
    create_user(
        db_session,
        name="Consulta Frota",
        email="viewer.sales@carfast.local",
        password="Secret123!",
        role_codes=["viewer"],
        organizational_unit_codes=["carfast"],
    )
    db_session.commit()
    login = client.post(
        "/login",
        data={"email": "viewer.sales@carfast.local", "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    client.post("/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False)

    response = client.get("/v2-clean/fleet/sales", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/v2-clean?error=forbidden"
