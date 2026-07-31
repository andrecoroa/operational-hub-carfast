from datetime import date
from decimal import Decimal

from sqlalchemy import select

import app.web.router as base_router
from app.core.config import settings
from app.models import (
    AuditLog,
    Vehicle,
    VehicleExternalSnapshot,
    VehicleImage,
    VehicleManualField,
    VehicleSaleLead,
    VehicleSaleProfile,
    VehicleSalePublication,
)
from app.services.users import create_user


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
            "financial_margin_min": "3000",
        },
    )
    assert page.status_code == 200
    assert "Venda de viaturas" in page.text
    assert "12-AB-34" in page.text
    assert "Devolução 18/10/2026" in page.text
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
