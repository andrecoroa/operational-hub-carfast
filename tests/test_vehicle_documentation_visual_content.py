from datetime import date
import html
from pathlib import Path
import re

from app.core.config import settings
from app.models.admin import Permission, Role, RolePermission
from app.models.documents import Document, VehicleDocumentRecord
from app.models.vehicles import Vehicle
from app.services.documentation_vehicle_view import vehicle_document_inventory
from app.services.users import create_user
from app.web import router
from sqlalchemy import select


ROOT = Path(__file__).resolve().parents[1]


def _seed_vehicle_document_states(db_session):
    vehicle = Vehicle(
        plate="DOC-26-VH",
        vin="VF7DOC26000000001",
        brand="Citroën",
        model="C4",
        active=True,
    )
    db_session.add(vehicle)
    db_session.flush()
    document = Document(
        title="Documento confidencial",
        document_type="registration_certificate",
        classification="fleet",
        source="upload",
        original_name="registration.pdf",
        file_name="registration.pdf",
        storage_provider="local",
        storage_path="fixtures/registration.pdf",
        status="classified",
        confidentiality_level="management",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        document_date=date(2025, 1, 1),
        archived=False,
    )
    record = VehicleDocumentRecord(
        vehicle_id=vehicle.id,
        source_record_type="archive",
        main_group="base_vehicle",
        subtype="inspection_certificate",
        title="Inspeção periódica",
        document_date=date(2024, 1, 1),
        end_date=date(2025, 1, 1),
        status="pending",
        has_physical_file=False,
    )
    db_session.add_all([document, record])
    db_session.commit()
    return vehicle, document, record


def test_vehicle_document_inventory_exposes_explainable_attention_states(db_session) -> None:
    vehicle, _document, _record = _seed_vehicle_document_states(db_session)

    row = next(item for item in vehicle_document_inventory(db_session) if item["vehicle_id"] == vehicle.id)

    assert row["documents"] == 1
    assert row["records"] == 1
    assert row["expired"] == 1
    assert row["confidential"] == 1
    assert row["missing"] == 1
    assert row["total"] == 2


def test_vehicle_document_overview_filters_and_preview_are_composed(
    authenticated_client, db_session, monkeypatch
) -> None:
    vehicle, document, _record = _seed_vehicle_document_states(db_session)
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", True)

    overview = authenticated_client.get(
        "/v2-clean/documentation/by-vehicle?q=DOC-26&attention=expired"
    )
    preview = authenticated_client.get(
        f"/v2-clean/documentation/by-vehicle/{vehicle.id}?selected=document:{document.id}"
    )

    assert overview.status_code == 200
    assert "vehicle-document-workbench" in overview.text
    assert "Viaturas e documentação associada" in overview.text
    assert "DOC-26-VH" in overview.text
    assert "1 expirado(s)" in overview.text
    assert "1 confidencial" in overview.text
    assert "1 em falta" in overview.text
    assert preview.status_code == 200
    assert "vehicle-document-preview-grid" in preview.text
    assert "registration_certificate" in preview.text
    assert "Confidencial — gestão" in preview.text
    assert "Não partilhado por omissão" in preview.text
    assert "nenhum documento segue para venda, portal ou email por omissão" in preview.text
    assert "fixtures/registration.pdf" not in preview.text
    assert "storage_path" not in preview.text
    assert "storage_key" not in preview.text


def test_vehicle_document_visual_content_has_fail_closed_destinations_and_return_context() -> None:
    preview = (ROOT / "app/templates/clean_documentation_vehicle_preview.html").read_text(
        encoding="utf-8"
    )
    router_source = (ROOT / "app/web/router.py").read_text(encoding="utf-8")

    assert "Selecionar para venda / portal" in preview
    assert "Anexar explicitamente por Email" in preview
    assert "Não partilhado por omissão" in router_source
    assert "can_view_management_documents(request)" in router_source
    assert "include_confidential=can_view_confidential_summary" in router_source
    assert "max_age_seconds=8 * 60 * 60" in router_source
    assert "can_publish_documents" in preview
    assert "can_email_documents" in preview
    assert "resolved_return = resolve_return_context" in router_source


def test_vehicle_document_return_context_is_signed_and_preserves_filters(
    authenticated_client, db_session, monkeypatch
) -> None:
    vehicle, _document, _record = _seed_vehicle_document_states(db_session)
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", True)

    overview = authenticated_client.get(
        "/v2-clean/documentation/by-vehicle?q=DOC-26&attention=expired"
    )
    token = html.unescape(
        re.search(r"return_context=([^\"]+)", overview.text).group(1)
    )
    preview = authenticated_client.get(
        f"/v2-clean/documentation/by-vehicle/{vehicle.id}?return_context={token}"
    )

    assert preview.status_code == 200
    assert 'href="/v2-clean/documentation/by-vehicle?q=DOC-26&amp;attention=expired#vehicle-document-list-title"' in preview.text


def test_non_management_user_cannot_infer_or_render_confidential_document(
    client, db_session, monkeypatch
) -> None:
    vehicle, _document, _record = _seed_vehicle_document_states(db_session)
    confidential_only = Vehicle(
        plate="SECRET-ONLY",
        vin="VF7SECRET000000001",
        active=True,
    )
    db_session.add(confidential_only)
    db_session.flush()
    db_session.add(
        Document(
            title="Título ultra confidencial",
            document_type="management_report",
            classification="fleet",
            source="upload",
            original_name="secret.pdf",
            file_name="secret.pdf",
            storage_provider="local",
            storage_path="secret/hidden.pdf",
            status="classified",
            confidentiality_level="management",
            vehicle_id=confidential_only.id,
            plate=confidential_only.plate,
            archived=False,
        )
    )
    role = Role(code="document_viewer_test", name="Document viewer", active=True)
    db_session.add(role)
    db_session.flush()
    permissions = list(
        db_session.scalars(
            select(Permission).where(
                Permission.code.in_(
                    {
                        "dashboard.read",
                        "documents.read",
                        "vehicles.read",
                        "navigation.documentation.access",
                    }
                )
            )
        )
    )
    db_session.add_all(
        [RolePermission(role_id=role.id, permission_id=permission.id) for permission in permissions]
    )
    create_user(
        db_session,
        name="Document Viewer",
        email="document.viewer@carfast.local",
        password="Secret123!",
        role_codes=[role.code],
        organizational_unit_codes=["carfast"],
    )
    db_session.commit()
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", True)
    monkeypatch.setattr(router, "can_view_management_documents", lambda _request: False)
    login = client.post(
        "/login",
        data={"email": "document.viewer@carfast.local", "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    client.post("/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False)

    overview = client.get("/v2-clean/documentation/by-vehicle")
    preview = client.get(f"/v2-clean/documentation/by-vehicle/{vehicle.id}")
    secret_preview = client.get(
        f"/v2-clean/documentation/by-vehicle/{confidential_only.id}"
    )

    assert overview.status_code == 200
    assert "SECRET-ONLY" not in overview.text
    assert "Título ultra confidencial" not in overview.text
    assert "1 confidencial" not in overview.text
    assert preview.status_code == 200
    assert "Documento confidencial" not in preview.text
    assert "Confidencial — gestão" not in preview.text
    assert "Selecionar para venda / portal" not in preview.text
    assert "Anexar explicitamente por Email" not in preview.text
    assert secret_preview.status_code == 200
    assert "Título ultra confidencial" not in secret_preview.text
    assert "secret/hidden.pdf" not in secret_preview.text


def test_vehicle_document_feature_flag_off_preserves_legacy_composition(
    authenticated_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "visual_foundation_enabled", False)
    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", False)

    response = authenticated_client.get("/v2-clean/documentation/by-vehicle")

    assert response.status_code == 200
    assert "vehicle-document-workbench" not in response.text
    assert "vehicle-document-list-card" not in response.text
    assert "<h1>Por viatura</h1>" in response.text


def test_vehicle_document_css_keeps_global_overflow_local_and_mobile_targets() -> None:
    css = (ROOT / "app/static/css/visual-v2.css").read_text(encoding="utf-8")

    assert ".vehicle-document-table-wrap{overflow-x:auto}" in css
    assert ".vehicle-document-table{min-width:980px}" in css
    assert 'content:"Deslize para consultar todos os campos →"' in css
    assert ".vehicle-document-filters :is(input,select,button,.button-link){width:100%;height:48px" in css
    assert ".vehicle-document-workbench .doc-arch-nav a" in css
    assert ".vehicle-document-workbench .doc-vehicle-preview-link" in css
    assert ".vehicle-document-workbench .doc-arch-pagination a" in css
    assert "display:inline-flex;min-height:44px;align-items:center" in css
    assert ".vehicle-document-header>.button-link{width:100%;min-height:48px}" in css
