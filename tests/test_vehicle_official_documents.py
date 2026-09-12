from sqlalchemy import select

from app.models.documents import Document, VehicleOfficialDocument, VehicleOfficialDocumentFile
from app.models.vehicles import Vehicle


def test_official_document_cards_are_shown_on_vehicle_page(authenticated_client, db_session):
    vehicle = Vehicle(plate="AA-00-AA", active=True)
    db_session.add(vehicle)
    db_session.commit()

    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")

    assert response.status_code == 200
    for label in ("DUA", "DUA autenticado", "Carta Verde", "IPO"):
        assert label in response.text
    assert "As tarefas apenas acompanham a recolha, sem criar cópias." in response.text

    detail = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}")
    assert detail.status_code == 200
    assert "Documentos oficiais" in detail.text
    assert "Arquivo e histórico" in detail.text
    assert "Gerir documentos oficiais" in detail.text
    assert detail.text.count("Em falta") >= 4


def test_dua_is_one_bundle_with_front_and_back(authenticated_client, db_session):
    vehicle = Vehicle(plate="AA-01-AA", active=True)
    db_session.add(vehicle)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/official-documents",
        data={"document_type": "dua", "valid_until": "2099-01-01"},
        files={
            "front_file": ("frente.pdf", b"front", "application/pdf"),
            "back_file": ("verso.pdf", b"back", "application/pdf"),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    bundle = db_session.scalar(select(VehicleOfficialDocument).where(VehicleOfficialDocument.vehicle_id == vehicle.id))
    assert bundle is not None
    assert bundle.document_type == "dua"
    assert bundle.valid_until is None
    links = db_session.scalars(
        select(VehicleOfficialDocumentFile).where(VehicleOfficialDocumentFile.official_document_id == bundle.id)
    ).all()
    assert {link.page_role for link in links} == {"front", "back"}
    assert db_session.scalar(select(Document).where(Document.id == links[0].document_id)).vehicle_id == vehicle.id


def test_expiring_document_requires_validity_and_replacement_preserves_history(authenticated_client, db_session):
    vehicle = Vehicle(plate="AA-02-AA", active=True)
    db_session.add(vehicle)
    db_session.commit()
    url = f"/v2-clean/fleet/{vehicle.id}/official-documents"

    rejected = authenticated_client.post(
        url, data={"document_type": "ipo"},
        files={"front_file": ("ipo.pdf", b"one", "application/pdf")}, follow_redirects=False,
    )
    assert "official_error=validity" in rejected.headers["location"]

    for content, validity in ((b"one", "2027-01-01"), (b"two", "2028-01-01")):
        response = authenticated_client.post(
            url, data={"document_type": "ipo", "valid_until": validity},
            files={"front_file": ("ipo.pdf", content, "application/pdf")}, follow_redirects=False,
        )
        assert response.status_code == 303

    versions = db_session.scalars(
        select(VehicleOfficialDocument)
        .where(VehicleOfficialDocument.vehicle_id == vehicle.id, VehicleOfficialDocument.document_type == "ipo")
        .order_by(VehicleOfficialDocument.id)
    ).all()
    assert [version.status for version in versions] == ["replaced", "current"]
    assert versions[1].replaces_id == versions[0].id
