from io import BytesIO
from pathlib import Path

from openpyxl import Workbook
import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.documents import (
    DiagnosticDocument,
    Document,
    DocumentWorkflowState,
    VehicleDocumentRecord,
)
from app.models.imports import ImportBatch, ImportFile
from app.models.vehicles import Vehicle


def _rentway_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Vehicles"
    sheet.append(
        [
            "platenr",
            "chassinr",
            "unitnr",
            "brandid",
            "modelid",
            "CurrentStatus",
        ]
    )
    sheet.append(
        [
            "AA-10-BB",
            "VF3TEST0000000001",
            "9901",
            "PEUGEOT",
            "208",
            "FREE",
        ]
    )
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _work_orders_workbook() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"]
    )
    sheet.append(
        ["FO-991", "2026-07-20", "AA-10-BB", "CarFast Oficina", "Revisão"]
    )
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _triage_document(index: int) -> Document:
    return Document(
        title=f"Entrada universal {index:02d}",
        document_type="unknown_document",
        classification="triage",
        source="email" if index % 2 else "v2_clean_manual",
        entry_channel="email" if index % 2 else "document_inbox",
        original_name=f"entrada_{index:02d}.pdf",
        file_name=f"entrada_{index:02d}.pdf",
        storage_provider="local",
        storage_path=f"Frota/_POR_ASSOCIAR/entrada_{index:02d}.pdf",
        status="unclassified" if index % 2 else "pending_triage",
    )


def test_new_documentation_navigation_and_legacy_center_coexist(
    authenticated_client,
):
    center = authenticated_client.get("/v2-clean/documentation")
    legacy = authenticated_client.get("/v2-clean/documents")

    assert center.status_code == 200
    assert "Centro de documentação" in center.text
    assert "Triagem" in center.text
    assert "Modelos de extração" in center.text
    assert legacy.status_code == 200
    assert "gestão v2" in legacy.text


@pytest.mark.parametrize(
    "path",
    [
        "/v2-clean/documentation/imports",
        "/v2-clean/documentation/imports/rentway",
        "/v2-clean/documentation/imports/reports",
        "/v2-clean/documentation/imports/invoices",
        "/v2-clean/documentation/imports/other",
        "/v2-clean/documentation/invoices",
        "/v2-clean/documentation/archive",
        "/v2-clean/documentation/extraction-models",
    ],
)
def test_documentation_workspaces_render(authenticated_client, path):
    response = authenticated_client.get(path)

    assert response.status_code == 200
    assert "Centro de documentação" in response.text


def test_clean_invoices_lists_expected_records_and_allows_manual_association(
    authenticated_client,
    db_session,
):
    vehicle = Vehicle(
        plate="AA-10-BB",
        vin="VF3EXPECTED0000001",
        rentway_unit_nr="9901",
    )
    pending = VehicleDocumentRecord(
        source_record_type="pending_import",
        main_group="invoices",
        status="pending",
        external_reference="HFO/3000/2026",
        supplier_name="Fornecedor Teste",
        source_system="pending_document_import",
        metadata_json={"supplier_nif": "500000000", "expected_total": "123,45"},
    )
    db_session.add_all([vehicle, pending])
    db_session.commit()

    page = authenticated_client.get("/v2-clean/documentation/invoices")
    associated = authenticated_client.post(
        f"/v2-clean/documents/pending/{pending.id}/associate",
        data={"identifier": "9901", "return_to": "clean"},
        follow_redirects=False,
    )
    db_session.expire_all()

    assert page.status_code == 200
    assert "Faturas esperadas" in page.text
    assert "HFO/3000/2026" in page.text
    assert "500000000" in page.text
    assert associated.status_code == 303
    assert associated.headers["location"].startswith(
        "/v2-clean/documentation/invoices"
    )
    assert db_session.get(VehicleDocumentRecord, pending.id).vehicle_id == vehicle.id


def test_reports_workspace_exposes_batch_reprocessing(
    authenticated_client,
    db_session,
):
    document = Document(
        title="Diagnóstico pendente",
        document_type="diagnostic_report",
        original_name="diagnostico.pdf",
        file_name="diagnostico.pdf",
        storage_provider="local",
        storage_path="diagnostico.pdf",
        status="received",
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DiagnosticDocument(
            document_id=document.id,
            diagnostic_type="vehicle_diagnostic",
            diagnostic_status="received",
            association_status="unassociated",
            ocr_status="not_requested",
            validation_status="pending",
        )
    )
    db_session.commit()

    page = authenticated_client.get(
        "/v2-clean/documentation/imports/reports?tab=diagnostics"
    )

    assert page.status_code == 200
    assert "Lotes de diagnósticos" in page.text
    assert "Extração pendente" in page.text
    assert "/v2-clean/diagnostics/batches/reprocess" in page.text


def test_extraction_models_lists_builtin_extractors_without_database_mappings(
    authenticated_client,
):
    page = authenticated_client.get("/v2-clean/documentation/extraction-models")

    assert page.status_code == 200
    assert "Extratores incorporados" in page.text
    assert "Diagnósticos Autel" in page.text
    assert "Diagnósticos Stellantis" in page.text
    assert "OCR de faturas" in page.text


@pytest.mark.parametrize(
    "path",
    [
        "/v2-clean/documentation",
        "/v2-clean/documentation/triage",
        "/v2-clean/documentation/imports",
        "/v2-clean/documentation/imports/rentway",
        "/v2-clean/documentation/imports/reports",
        "/v2-clean/documentation/imports/invoices",
        "/v2-clean/documentation/imports/other",
        "/v2-clean/documentation/invoices",
        "/v2-clean/diagnostics",
        "/v2-clean/documentation/archive",
        "/v2-clean/documentation/extraction-models",
    ],
)
def test_documentation_pages_use_compact_module_header(authenticated_client, path):
    response = authenticated_client.get(path)

    assert response.status_code == 200
    assert '<header class="doc-arch-header">' in response.text


def test_documentation_headers_keep_only_essential_metrics(authenticated_client):
    center = authenticated_client.get("/v2-clean/documentation")
    invoices = authenticated_client.get("/v2-clean/documentation/invoices")

    assert 'aria-label="Indicadores essenciais"' in center.text
    assert "Importações recentes" not in center.text
    assert "Diagnósticos pendentes" not in center.text
    assert 'class="doc-arch-kpis doc-arch-kpis-four"' in invoices.text
    assert "Sem associação" not in invoices.text


def test_rentway_import_actions_are_scoped_to_active_page(authenticated_client):
    work_orders = authenticated_client.get(
        "/v2-clean/documentation/imports/rentway?tab=work_orders"
    )
    fleet = authenticated_client.get(
        "/v2-clean/documentation/imports/rentway?tab=fleet"
    )

    assert ">+ Importar<" not in work_orders.text
    assert 'data-import-kind="work_order_details"' in work_orders.text
    assert 'data-import-kind="work_orders"' in work_orders.text
    assert '<select name="import_kind"' not in work_orders.text
    assert 'data-import-kind="fleet"' in fleet.text
    assert 'data-import-kind="work_orders"' not in fleet.text


@pytest.mark.parametrize(
    ("path", "expected_action", "excluded_action"),
    [
        (
            "/v2-clean/documentation/imports/reports?tab=service_box",
            "Importar relatórios",
            "Importar faturas",
        ),
        (
            "/v2-clean/documentation/imports/invoices",
            "Importar faturas",
            "Importar relatórios",
        ),
        (
            "/v2-clean/documentation/imports/other",
            "Importar outros documentos",
            "Importar faturas",
        ),
    ],
)
def test_each_import_workspace_exposes_only_its_own_import_action(
    authenticated_client,
    path,
    expected_action,
    excluded_action,
):
    response = authenticated_client.get(path)

    assert response.status_code == 200
    assert expected_action in response.text
    assert excluded_action not in response.text


def test_triage_is_universal_and_server_paginated(
    authenticated_client,
    db_session,
):
    db_session.add_all([_triage_document(index) for index in range(31)])
    db_session.commit()

    first = authenticated_client.get(
        "/v2-clean/documentation/triage?page=1&page_size=10"
    )
    second = authenticated_client.get(
        "/v2-clean/documentation/triage?page=2&page_size=10"
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert "31 registos" in first.text
    assert "Entrada universal 30" in first.text
    assert "Entrada universal 20" in second.text
    assert "Entrada universal 30" not in second.text
    assert "Email" in first.text


def test_invoice_nature_endpoint_requires_single_valid_nature(
    authenticated_client,
    db_session,
):
    document = Document(
        title="Fatura por decidir",
        document_type="workshop_supplier_invoice",
        classification="invoice",
        source="v2_clean_manual",
        original_name="fatura.pdf",
        file_name="fatura.pdf",
        storage_provider="local",
        storage_path="Frota/_POR_ASSOCIAR/fatura.pdf",
        status="received",
    )
    db_session.add(document)
    db_session.commit()

    invalid = authenticated_client.post(
        f"/v2-clean/documentation/invoices/{document.id}/nature",
        data={"nature": "operacional,financeira"},
        follow_redirects=False,
    )
    valid = authenticated_client.post(
        f"/v2-clean/documentation/invoices/{document.id}/nature",
        data={
            "nature": "financeira",
            "suggested_nature": "financeira",
            "suggestion_confidence": "0,91",
        },
        follow_redirects=False,
    )
    db_session.expire_all()

    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]
    assert valid.status_code == 303
    state = db_session.scalar(
        select(DocumentWorkflowState).where(
            DocumentWorkflowState.document_id == document.id
        )
    )
    stored = db_session.get(Document, document.id)
    assert state.invoice_nature == "financeira"
    assert state.suggestion_confidence == 0.91
    assert stored.document_type == "finance_supplier_invoice"
    assert stored.archived is True


def test_rentway_preview_does_not_write_and_confirm_uses_durable_source(
    authenticated_client,
    db_session,
    monkeypatch,
    tmp_path,
):
    archive_root = tmp_path / "documents"
    monkeypatch.setattr(settings, "document_archive_root", str(archive_root))
    content = _rentway_workbook()

    preview_response = authenticated_client.post(
        "/v2-clean/documentation/imports/rentway/preview",
        data={"import_kind": "fleet"},
        files={
            "file": (
                "rentway_fleet.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        follow_redirects=False,
    )
    db_session.expire_all()

    assert preview_response.status_code == 303
    assert "/preview/" in preview_response.headers["location"]
    assert db_session.scalar(select(func.count()).select_from(Vehicle)) == 0
    assert db_session.scalar(select(func.count()).select_from(ImportBatch)) == 0

    preview_page = authenticated_client.get(preview_response.headers["location"])
    assert preview_page.status_code == 200
    assert "nenhum dado foi gravado" in preview_page.text
    token = preview_response.headers["location"].rsplit("/", 1)[-1]
    confirmed = authenticated_client.post(
        "/v2-clean/documentation/imports/rentway/confirm",
        data={"preview_token": token},
        follow_redirects=False,
    )
    db_session.expire_all()

    vehicle = db_session.scalar(select(Vehicle).where(Vehicle.plate == "AA-10-BB"))
    batch = db_session.scalar(
        select(ImportBatch).where(ImportBatch.import_type == "rentway_fleet")
    )
    import_file = db_session.scalar(
        select(ImportFile).where(ImportFile.batch_id == batch.id)
    )
    assert confirmed.status_code == 303
    assert vehicle is not None
    assert batch.status == "completed"
    assert Path(import_file.storage_path).is_file()
    assert str(archive_root) in import_file.storage_path


def test_rentway_workspace_keeps_separate_work_order_buttons(
    authenticated_client,
):
    page = authenticated_client.get(
        "/v2-clean/documentation/imports/rentway?tab=work_orders"
    )

    assert page.status_code == 200
    assert "Importar folhas" in page.text
    assert "Importar detalhes" in page.text
    assert "Importar conjunto" not in page.text


def test_structured_rentway_confirmation_creates_reprocessable_batch(
    authenticated_client,
    db_session,
    monkeypatch,
    tmp_path,
):
    archive_root = tmp_path / "documents"
    monkeypatch.setattr(settings, "document_archive_root", str(archive_root))
    vehicle = Vehicle(
        plate="AA-10-BB",
        vin="VF3WORKORDER000001",
        rentway_unit_nr="9901",
        brand="PEUGEOT",
        model="208",
        lifecycle_status="active",
        operational_status="free",
    )
    db_session.add(vehicle)
    db_session.commit()

    preview = authenticated_client.post(
        "/v2-clean/documentation/imports/rentway/preview",
        data={"import_kind": "work_orders"},
        files={
            "file": (
                "folhas_obra.xlsx",
                _work_orders_workbook(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        follow_redirects=False,
    )
    token = preview.headers["location"].rsplit("/", 1)[-1]
    confirmed = authenticated_client.post(
        "/v2-clean/documentation/imports/rentway/confirm",
        data={"preview_token": token},
        follow_redirects=False,
    )
    db_session.expire_all()

    batch = db_session.scalar(
        select(ImportBatch).where(
            ImportBatch.import_type == "rentway_work_orders"
        )
    )
    import_file = db_session.scalar(
        select(ImportFile).where(ImportFile.batch_id == batch.id)
    )
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.external_reference == "FO-991"
        )
    )
    assert preview.status_code == 303
    assert confirmed.status_code == 303
    assert batch.status == "completed"
    assert record is not None
    assert Path(import_file.storage_path).is_file()

    reprocessed = authenticated_client.post(
        f"/v2-clean/documentation/imports/rentway/batches/{batch.id}/reprocess",
        follow_redirects=False,
    )
    db_session.expire_all()

    assert reprocessed.status_code == 303
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(ImportBatch)
            .where(ImportBatch.import_type == "rentway_work_orders")
        )
        == 2
    )
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(VehicleDocumentRecord)
            .where(VehicleDocumentRecord.external_reference == "FO-991")
        )
        == 1
    )
