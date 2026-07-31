import re
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import hash_password
from app.main import app
from app.models import (
    PortalInvitation,
    PortalOrganization,
    PortalPublicationAccess,
    PortalUser,
    Vehicle,
    VehicleSaleLead,
    VehicleSaleProfile,
    VehicleSalePublication,
)


def csrf_from(response) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match
    return match.group(1)


def invitation_token_from(response) -> str:
    match = re.search(r"/portal/convite/([A-Za-z0-9_-]+)", response.text)
    assert match
    return match.group(1)


def create_publication_vehicle(db_session) -> Vehicle:
    vehicle = Vehicle(
        plate="45-ZZ-90",
        vin="PORTALTESTVEHICLE1",
        rentway_unit_nr="PORTAL-001",
        brand="Renault",
        model="Austral",
        version="E-Tech",
        year=2024,
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(vehicle)
    db_session.flush()
    db_session.add(
        VehicleSaleProfile(
            vehicle_id=vehicle.id,
            status="for_sale",
            market_trade_value=Decimal("24500.00"),
            market_retail_value=Decimal("28900.00"),
            selling_price=Decimal("24500.00"),
            public_notes="Viatura preparada para comércio.",
        )
    )
    db_session.commit()
    return vehicle


def create_organization_and_invitation(authenticated_client):
    page = authenticated_client.get("/v2-clean/fleet/sales-access")
    assert page.status_code == 200
    csrf = csrf_from(page)
    created = authenticated_client.post(
        "/v2-clean/fleet/sales-access/organizations",
        data={
            "csrf_token": csrf,
            "name": "Comércio Auto Norte",
            "tax_number": "PT 509 000 111",
            "organization_type": "trade",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303

    page = authenticated_client.get("/v2-clean/fleet/sales-access")
    csrf = csrf_from(page)
    invitation = authenticated_client.post(
        "/v2-clean/fleet/sales-access/invitations",
        data={
            "csrf_token": csrf,
            "organization_id": "1",
            "name": "Maria Compras",
            "email": "maria@comercio.example",
            "expires_days": "7",
            "permissions": [
                "portal.access",
                "vehicles.catalog.view",
                "vehicles.trade_price.view",
                "vehicle_reports.download",
                "vehicles.questions.create",
                "offers.create",
                "offers.view_organization",
                "purchase_requests.create",
                "support_requests.create",
            ],
        },
    )
    assert invitation.status_code == 200
    return invitation_token_from(invitation)


def accept_invitation(token: str) -> TestClient:
    portal_client = TestClient(app)
    page = portal_client.get(f"/portal/convite/{token}")
    assert page.status_code == 200
    accepted = portal_client.post(
        f"/portal/convite/{token}",
        data={
            "csrf_token": csrf_from(page),
            "password": "StrongPortal123!",
            "password_confirmation": "StrongPortal123!",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    assert accepted.headers["location"] == "/portal"
    return portal_client


def test_portal_invitation_is_separate_from_internal_auth(
    authenticated_client,
    db_session,
):
    token = create_organization_and_invitation(authenticated_client)

    invitation = db_session.scalar(select(PortalInvitation))
    assert invitation is not None
    assert invitation.token_hash != token
    assert len(invitation.token_hash) == 64

    portal_client = accept_invitation(token)
    home = portal_client.get("/portal")
    assert home.status_code == 200
    assert "Maria Compras" in home.text
    assert "Comércio Auto Norte" in home.text

    internal = portal_client.get("/v2-clean", follow_redirects=False)
    assert internal.status_code == 303
    assert internal.headers["location"].startswith("/login")

    reused = portal_client.get(f"/portal/convite/{token}")
    assert reused.status_code == 410

    admin_page = authenticated_client.get("/v2-clean/fleet/sales-access")
    suspended = authenticated_client.post(
        "/v2-clean/fleet/sales-access/organizations/1/status",
        data={"csrf_token": csrf_from(admin_page), "status": "suspended"},
        follow_redirects=False,
    )
    assert suspended.status_code == 303
    revoked_session = portal_client.get("/portal/viaturas", follow_redirects=False)
    assert revoked_session.status_code == 303
    assert revoked_session.headers["location"].startswith("/portal/entrar")


def test_restricted_catalog_and_authenticated_offer(
    authenticated_client,
    db_session,
):
    vehicle = create_publication_vehicle(db_session)
    token = create_organization_and_invitation(authenticated_client)
    portal_client = accept_invitation(token)

    organization = db_session.scalar(
        select(PortalOrganization).where(
            PortalOrganization.name == "Comércio Auto Norte"
        )
    )
    assert organization is not None
    published = authenticated_client.post(
        f"/v2-clean/fleet/sales/{vehicle.id}/publish",
        data={
            "audience": "trade",
            "visibility": "selected_organizations",
            "organization_ids": [str(organization.id)],
        },
        follow_redirects=False,
    )
    assert published.status_code == 303

    db_session.expire_all()
    publication = db_session.scalar(
        select(VehicleSalePublication).where(
            VehicleSalePublication.vehicle_id == vehicle.id
        )
    )
    assert publication is not None
    assert publication.visibility == "selected_organizations"
    assert db_session.scalar(
        select(PortalPublicationAccess).where(
            PortalPublicationAccess.publication_id == publication.id,
            PortalPublicationAccess.organization_id == organization.id,
        )
    )

    anonymous = TestClient(app)
    restricted = anonymous.get(
        f"/portal/viaturas/{publication.token}",
        follow_redirects=False,
    )
    assert restricted.status_code == 303
    assert restricted.headers["location"].startswith("/portal/entrar")

    other_organization = PortalOrganization(
        name="Comerciante sem atribuição",
        tax_number="PT500000333",
        organization_type="trade",
        status="active",
    )
    db_session.add(other_organization)
    db_session.flush()
    db_session.add(
        PortalUser(
            organization_id=other_organization.id,
            name="Outro Comerciante",
            email="outro@comercio.example",
            password_hash=hash_password("StrongPortal123!"),
            permissions_json=[
                "portal.access",
                "vehicles.catalog.view",
                "vehicles.trade_price.view",
                "vehicle_reports.download",
            ],
            active=True,
        )
    )
    db_session.commit()
    other_client = TestClient(app)
    other_login_page = other_client.get("/portal/entrar")
    other_client.post(
        "/portal/entrar",
        data={
            "csrf_token": csrf_from(other_login_page),
            "email": "outro@comercio.example",
            "password": "StrongPortal123!",
        },
        follow_redirects=False,
    )
    other_detail = other_client.get(f"/portal/viaturas/{publication.token}")
    assert other_detail.status_code == 403
    assert "Renault Austral" not in other_client.get("/portal/viaturas").text

    catalog = portal_client.get("/portal/viaturas")
    assert catalog.status_code == 200
    assert "Renault Austral" in catalog.text
    assert "24 500,00 €" in catalog.text

    detail = portal_client.get(f"/portal/viaturas/{publication.token}")
    assert detail.status_code == 200
    assert "Maria Compras" in detail.text
    csrf = csrf_from(detail)
    offered = portal_client.post(
        f"/portal/viaturas/{publication.token}/interesse",
        data={
            "csrf_token": csrf,
            "kind": "offer",
            "name": "Identidade falsificada",
            "email": "outra@example.com",
            "buyer_company": "Outra empresa",
            "offer_value": "23800",
            "message": "Proposta da empresa autenticada.",
            "consent": "1",
        },
        follow_redirects=False,
    )
    assert offered.status_code == 303

    db_session.expire_all()
    portal_user = db_session.scalar(
        select(PortalUser).where(PortalUser.email == "maria@comercio.example")
    )
    lead = db_session.scalar(
        select(VehicleSaleLead).where(
            VehicleSaleLead.publication_id == publication.id
        )
    )
    assert lead is not None
    assert lead.name == "Maria Compras"
    assert lead.email == "maria@comercio.example"
    assert lead.company == "Comércio Auto Norte"
    assert lead.portal_user_id == portal_user.id
    assert lead.portal_organization_id == organization.id

    interactions = portal_client.get("/portal/interacoes")
    assert interactions.status_code == 200
    assert "CF-VENDA-" in interactions.text
    assert "23 800,00 €" in interactions.text


def test_portal_permissions_are_enforced_server_side(
    authenticated_client,
    db_session,
):
    vehicle = create_publication_vehicle(db_session)
    organization = PortalOrganization(
        name="Consulta Limitada",
        tax_number="PT500000222",
        organization_type="trade",
        status="active",
    )
    db_session.add(organization)
    db_session.flush()
    user = PortalUser(
        organization_id=organization.id,
        name="Utilizador Consulta",
        email="consulta@portal.example",
        password_hash=hash_password("StrongPortal123!"),
        permissions_json=[
            "portal.access",
            "vehicles.catalog.view",
            "vehicles.trade_price.view",
            "vehicle_reports.download",
        ],
        active=True,
    )
    db_session.add(user)
    db_session.commit()

    published = authenticated_client.post(
        f"/v2-clean/fleet/sales/{vehicle.id}/publish",
        data={
            "audience": "trade",
            "visibility": "authenticated_trade",
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    db_session.expire_all()
    publication = db_session.scalar(
        select(VehicleSalePublication).where(
            VehicleSalePublication.vehicle_id == vehicle.id
        )
    )

    portal_client = TestClient(app)
    login_page = portal_client.get("/portal/entrar")
    missing_csrf = portal_client.post(
        "/portal/entrar",
        data={
            "email": user.email,
            "password": "StrongPortal123!",
            "next_url": "/portal/viaturas",
        },
        follow_redirects=False,
    )
    assert "error=csrf" in missing_csrf.headers["location"]
    logged_in = portal_client.post(
        "/portal/entrar",
        data={
            "csrf_token": csrf_from(login_page),
            "email": user.email,
            "password": "StrongPortal123!",
            "next_url": "/portal/viaturas",
        },
        follow_redirects=False,
    )
    assert logged_in.status_code == 303

    detail = portal_client.get(f"/portal/viaturas/{publication.token}")
    assert detail.status_code == 200
    assert 'option value="offer"' not in detail.text
    forbidden = portal_client.post(
        f"/portal/viaturas/{publication.token}/interesse",
        data={
            "csrf_token": csrf_from(detail),
            "kind": "offer",
            "offer_value": "22000",
            "consent": "1",
        },
        follow_redirects=False,
    )
    assert forbidden.status_code == 303
    assert "error=forbidden_action" in forbidden.headers["location"]
    assert (
        db_session.scalar(
            select(VehicleSaleLead).where(
                VehicleSaleLead.publication_id == publication.id
            )
        )
        is None
    )


def test_public_request_and_public_sale_remain_available(client, db_session):
    home = client.get("/portal")
    assert home.status_code == 200
    assert "Registar pedido" in home.text
    request_page = client.get("/portal/pedido")
    assert request_page.status_code == 200
    assert "Registar pedido" in request_page.text

    vehicle = create_publication_vehicle(db_session)
    publication = VehicleSalePublication(
        vehicle_id=vehicle.id,
        token="public-test-token",
        audience="retail",
        visibility="public_link",
        status="published",
        snapshot_json={
            "vehicle": {
                "reference": "CF-V-TEST",
                "brand": "Renault",
                "model": "Austral",
            },
            "sale": {
                "audience_label": "Cliente final",
                "availability_label": "Para venda",
                "price": "28900.00",
            },
        },
        selected_image_ids_json=[],
        view_count=0,
    )
    db_session.add(publication)
    db_session.commit()

    public_page = client.get("/portal/viaturas/public-test-token")
    assert public_page.status_code == 200
    assert "Renault Austral" in public_page.text
