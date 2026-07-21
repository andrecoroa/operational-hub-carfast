import hashlib
import json
import zipfile
from datetime import date
from pathlib import Path
from io import BytesIO

import fitz
from openpyxl import Workbook
from sqlalchemy import select

from app.core.config import settings
from app.models.documents import (
    Document,
    DocumentEvent,
    DocumentLink,
    VehicleDocumentAuditField,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.models.vehicles import Vehicle, VehicleIdentifier, VehicleManualField
from app.services.vehicle_document_history import document_center_module_context, vehicle_document_module_context
from app.web.router import _batch_document_vehicle, local_document_storage_folder


def _make_workbook(headers: list[str], rows: list[list[object]]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _make_rentway_export_workbook(title: str, headers: list[str], rows: list[list[object]]) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([title])
    sheet.append([""])
    sheet.append([f"{len(rows)} resultados"])
    sheet.append([None for _ in headers])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _make_zip(files: dict[str, bytes]) -> BytesIO:
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    stream.seek(0)
    return stream


def _make_pdf(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    content = document.tobytes()
    document.close()
    return content


def _create_vehicle(db_session):
    vehicle = Vehicle(
        plate="CC-11-AA",
        vin="VINCC11AA123456789",
        brand="PEUGEOT",
        model="2008",
        version="ALLURE",
        rentway_unit_nr="911",
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(vehicle)
    db_session.commit()
    db_session.refresh(vehicle)
    return vehicle


def test_clean_document_storage_uses_configured_archive_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "document_archive_root", str(tmp_path))

    storage_folder = local_document_storage_folder(
        "Frota/BB-69-TE_VR7EFYHT2PJ697244/00_Importacoes_Estruturadas",
        plate="BB-69-TE",
        vin="VR7EFYHT2PJ697244",
    )

    assert storage_folder == tmp_path / "Frota" / "BB-69-TE_VR7EFYHT2PJ697244" / "00_Importacoes_Estruturadas"


def test_clean_document_batch_zip_associates_pending_and_deduplicates(
    authenticated_client,
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "document_archive_root", str(tmp_path))
    vehicle = _create_vehicle(db_session)
    pdf = _make_pdf("Fatura FT-4458\nData 15/05/2026\nOleo motor 5W30 45,00\nFiltro de oleo 12,00")
    batch = _make_zip(
        {
            "CC-11-AA/Faturas/fatura_2026-05-15.pdf": pdf,
            "CC-11-AA/Faturas/copia_fatura.pdf": pdf,
            "Sem matricula/diagnostico.png": b"sample-image",
            "ignorar.txt": b"not a document",
        }
    )

    response = authenticated_client.post(
        "/v2-clean/documents/import/archive-batch",
        files={"file": ("documentos.zip", batch.getvalue(), "application/zip")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "batch_imported=2" in response.headers["location"]
    assert "batch_matched=1" in response.headers["location"]
    assert "batch_pending=1" in response.headers["location"]
    assert "batch_duplicates=1" in response.headers["location"]
    documents = db_session.scalars(
        select(Document).where(Document.entry_channel == "v2_clean_batch").order_by(Document.id)
    ).all()
    assert len(documents) == 2
    matched = next(item for item in documents if item.vehicle_id == vehicle.id)
    pending = next(item for item in documents if item.vehicle_id is None)
    assert matched.document_type == "workshop_supplier_invoice"
    assert matched.document_date == date(2026, 5, 15)
    assert matched.folder_path.endswith("01_Documentacao_Financeira/Faturas")
    assert Path(matched.storage_path).exists()
    ocr_event = db_session.scalar(
        select(DocumentEvent).where(
            DocumentEvent.document_id == matched.id,
            DocumentEvent.action == "invoice.ocr.extracted",
        )
    )
    assert ocr_event is not None
    payload = json.loads(ocr_event.new_value)
    assert payload["ocr_status"] == "extracted"
    assert any("Oleo motor" in row["description"] for row in payload["invoice_lines"])
    assert pending.folder_path == "Frota/_POR_ASSOCIAR/99_Pendentes_Classificar"
    assert Path(pending.storage_path).exists()


def test_clean_document_batch_vehicle_match_falls_back_to_vin(db_session):
    vehicle = _create_vehicle(db_session)
    vehicles_by_plate = {"OTHERPLATE": vehicle}
    vehicles_by_vin = {"VINCC11AA123456789": vehicle}

    matched = _batch_document_vehicle(
        "FACTURA\nChassis: VINCC11AA123456789\nData: 12/06/2026",
        vehicles_by_plate,
        vehicles_by_vin,
    )

    assert matched == vehicle


def test_clean_vehicle_documents_page_renders(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)

    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")

    assert response.status_code == 200
    assert "Documentação de arquivo" in response.text
    assert "Documentação estruturada" in response.text
    assert "Timeline documental" in response.text


def test_clean_vehicle_documents_page_renders_with_regressive_km_alert(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    db_session.add_all(
        [
            VehicleDocumentRecord(
                vehicle_id=vehicle.id,
                source_record_type="structured",
                main_group="work_orders",
                title="FO 1",
                plate=vehicle.plate,
                document_date=date(2026, 1, 1),
                km=1000,
            ),
            VehicleDocumentRecord(
                vehicle_id=vehicle.id,
                source_record_type="structured",
                main_group="work_orders",
                title="FO 2",
                plate=vehicle.plate,
                document_date=date(2026, 1, 2),
                km=900,
            ),
        ]
    )
    db_session.commit()

    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")

    assert response.status_code == 200
    assert "KM regressivo" in response.text


def test_clean_vehicle_summary_hides_legacy_documents(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    legacy_document = Document(
        title="Relatório antigo",
        document_type="workshop_report",
        classification="technical_report",
        source="workshop",
        entry_channel="legacy",
        original_name="legacy.pdf",
        file_name="legacy.pdf",
        storage_provider="local",
        storage_path="/tmp/legacy.pdf",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
    )
    clean_document = Document(
        title="Relatório v2",
        document_type="workshop_report",
        classification="technical_report",
        source="v2_clean_manual",
        entry_channel="v2_clean",
        original_name="clean.pdf",
        file_name="clean.pdf",
        storage_provider="local",
        storage_path="/tmp/clean.pdf",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
    )
    db_session.add_all([legacy_document, clean_document])
    db_session.commit()

    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}")

    assert response.status_code == 200
    assert "Relatório v2" in response.text
    assert "Relatório antigo" not in response.text


def test_clean_vehicle_documents_audit_field_syncs_real_start(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/audit-field",
        data={
            "field_code": "real_start_date",
            "value": "2024-05-20",
            "audited_on": "2026-07-13",
            "observation": "Validado por documento base",
            "document_basis": "DUA + compra",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    audit_field = db_session.scalar(
        select(VehicleDocumentAuditField).where(
            VehicleDocumentAuditField.vehicle_id == vehicle.id,
            VehicleDocumentAuditField.field_code == "real_start_date",
        )
    )
    manual_field = db_session.scalar(
        select(VehicleManualField).where(
            VehicleManualField.vehicle_id == vehicle.id,
            VehicleManualField.field_code == "real_start_date",
        )
    )
    assert audit_field is not None
    assert audit_field.value_json == "2024-05-20"
    assert manual_field is not None
    assert manual_field.value_json == "2024-05-20"


def test_clean_vehicle_documents_import_work_orders(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [["FO-1576", "2026-05-15", "CC-11-AA", "Oficina Porto", "Revisão e pneus dianteiros"]],
    )

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/work-orders",
        files={"file": ("fo.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "work_orders",
        )
    )
    assert record is not None
    assert record.title == "FO-1576"
    assert record.supplier_name == "Oficina Porto"
    import_source = db_session.scalar(
        select(Document).where(
            Document.vehicle_id == vehicle.id,
            Document.entry_channel == "structured_import",
            Document.source_subject == "work_orders:1",
        )
    )
    assert import_source is not None
    assert import_source.file_hash
    assert import_source.storage_path.endswith(".xlsx")
    db_session.refresh(record)
    assert record.document_id == import_source.id
    module_ctx = vehicle_document_module_context(db_session, vehicle)
    assert len(module_ctx["structured_rows"]) == 1
    assert len(module_ctx["import_rows"]) == 1
    assert module_ctx["import_rows"][0]["import_label"] == "Folhas de obra"
    assert module_ctx["archive_rows"] == []

    page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")
    assert page.status_code == 200
    assert "Folhas de obra" in page.text
    assert "FO-1576" in page.text
    assert "Documentação estruturada" in page.text
    assert "Fontes importadas" not in page.text
    assert "Manutenção" in page.text
    assert "Calços" in page.text
    assert "Discos" in page.text
    assert f"/v2-clean/fleet/{vehicle.id}/documents/classify-row" in page.text

    fleet_page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}")
    assert fleet_page.status_code == 200
    assert "Folhas de obra" in fleet_page.text
    assert f"/v2-clean/fleet/{vehicle.id}/documents?main_group=work_orders" in fleet_page.text
    assert "<strong>1</strong>" in fleet_page.text


def test_clean_vehicle_documents_save_row_classification(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    record = VehicleDocumentRecord(
        vehicle_id=vehicle.id,
        source_record_type="structured",
        main_group="work_orders",
        title="FO-1608",
        external_reference="1608",
        plate=vehicle.plate,
        supplier_name="Oficina Porto",
        raw_description="Calços atrás gastos",
        document_date=date(2026, 5, 25),
        status="structured",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/classify-row",
        data={
            "record_id": str(record.id),
            "return_group": "work_orders",
            "maintenance": "",
            "pads": "rear",
            "discs": "",
            "tyres": "",
            "ipo": "",
            "other": "",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith("?classified=1&main_group=work_orders")
    db_session.refresh(record)
    assert record.status == "classified"
    assert record.comparison_state == "validado"
    tag = db_session.scalar(
        select(VehicleDocumentRecordTag).where(
            VehicleDocumentRecordTag.vehicle_id == vehicle.id,
            VehicleDocumentRecordTag.record_id == record.id,
            VehicleDocumentRecordTag.category == "pads",
        )
    )
    assert tag is not None
    assert tag.value == "rear"

    page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")
    assert page.status_code == 200
    assert '<option value="rear" selected>TR</option>' in page.text
    assert "Validado" in page.text


def test_clean_vehicle_documents_saves_multiple_services_and_custom_values(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    record = VehicleDocumentRecord(
        vehicle_id=vehicle.id,
        source_record_type="structured",
        main_group="work_orders",
        title="FO-1700",
        external_reference="1700",
        plate=vehicle.plate,
        status="structured",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/classify-row",
        data={
            "record_id": str(record.id),
            "return_group": "work_orders",
            "maintenance": ["revision", "degradation"],
            "pads": ["front", "rear"],
            "discs": ["undefined"],
            "other_custom": "Bateria; Correia auxiliar",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(record)
    assert record.status == "classified"
    assert record.comparison_state == "validado"
    tags = db_session.scalars(
        select(VehicleDocumentRecordTag).where(VehicleDocumentRecordTag.record_id == record.id)
    ).all()
    assert {(tag.category, tag.value) for tag in tags if tag.value} >= {
        ("maintenance", "revision"),
        ("maintenance", "degradation"),
        ("pads", "front"),
        ("pads", "rear"),
        ("discs", "undefined"),
    }
    assert {tag.free_text for tag in tags if tag.free_text} == {"Bateria", "Correia auxiliar"}


def test_clean_vehicle_documents_shows_existing_invoice_ocr_lines(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    invoice = Document(
        title="Fatura 4458",
        document_type="workshop_supplier_invoice",
        source="v2_clean_manual",
        entry_channel="v2_clean_manual",
        original_name="fatura-4458.pdf",
        file_name="fatura-4458.pdf",
        storage_provider="local",
        storage_path="Frota/fatura-4458.pdf",
        folder_path="Frota/Faturas",
        status="received",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        supplier_name="Oficina Porto",
        contract_number="4458",
        document_date=date(2026, 6, 1),
    )
    db_session.add(invoice)
    db_session.flush()
    db_session.add(
        DocumentEvent(
            document_id=invoice.id,
            action="invoice.ocr.extracted",
            new_value=json.dumps(
                {
                    "invoice_lines": [
                        {"description": "Óleo motor 5W30", "quantity": 5, "amount": "45,00", "service": "Revisão"},
                        {"description": "Filtro de óleo", "quantity": 1, "amount": "12,00"},
                    ]
                },
                ensure_ascii=False,
            ),
        )
    )
    db_session.commit()

    response = authenticated_client.get(
        f"/v2-clean/fleet/{vehicle.id}/documents?main_group=invoices"
    )

    assert response.status_code == 200
    assert "Óleo motor 5W30" in response.text
    assert "Filtro de óleo" in response.text
    assert "Associar FO" in response.text


def test_clean_vehicle_documents_links_invoice_to_work_order_once(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    work_order = VehicleDocumentRecord(
        vehicle_id=vehicle.id,
        source_record_type="structured",
        main_group="work_orders",
        title="FO 1608",
        external_reference="1608",
        plate=vehicle.plate,
        document_date=date(2026, 5, 25),
        status="classified",
    )
    invoice = Document(
        title="Fatura 4458",
        document_type="workshop_supplier_invoice",
        source="v2_clean_manual",
        entry_channel="v2_clean_manual",
        original_name="fatura-4458.pdf",
        file_name="fatura-4458.pdf",
        storage_provider="local",
        storage_path="Frota/fatura-4458.pdf",
        folder_path="Frota/Faturas",
        status="received",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
    )
    db_session.add_all([work_order, invoice])
    db_session.commit()
    db_session.refresh(work_order)
    db_session.refresh(invoice)

    for _ in range(2):
        response = authenticated_client.post(
            f"/v2-clean/fleet/{vehicle.id}/documents/link-work-order",
            data={
                "document_id": str(invoice.id),
                "work_order_record_id": str(work_order.id),
                "return_group": "invoices",
            },
            follow_redirects=False,
        )
        assert response.status_code == 303

    links = db_session.scalars(
        select(DocumentLink).where(
            DocumentLink.document_id == invoice.id,
            DocumentLink.entity_type == "vehicle_document_record",
            DocumentLink.entity_id == str(work_order.id),
            DocumentLink.category == "invoice_work_order",
        )
    ).all()
    assert len(links) == 1
    events = db_session.scalars(
        select(DocumentEvent).where(
            DocumentEvent.document_id == invoice.id,
            DocumentEvent.action == "invoice.work_order_linked",
        )
    ).all()
    assert len(events) == 1
    page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents?main_group=invoices")
    assert page.status_code == 200
    assert "FO 1608" in page.text


def test_clean_vehicle_documents_imports_multiple_detail_lines_by_work_order_number(
    authenticated_client,
    db_session,
):
    vehicle = _create_vehicle(db_session)
    record = VehicleDocumentRecord(
        vehicle_id=vehicle.id,
        source_record_type="structured",
        main_group="work_orders",
        title="1608",
        external_reference="1608",
        plate=vehicle.plate,
        status="structured",
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)
    workbook = _make_workbook(
        ["Folha de obra nº", "Descrição", "Referência", "Quantidade", "Preço unitário", "Total", "Kms"],
        [
            ["1608", "Jogo de calços traseiros", "CAL-01", 1, 75, 75, 32100],
            ["1608", "Mão de obra", "MO-01", 1.5, 40, 60, 32100],
        ],
    )

    response = authenticated_client.post(
        "/v2-clean/documents/import/work-order-details",
        files={
            "file": (
                "detalhe fo.xlsx",
                workbook.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "imported_count=2" in response.headers["location"]
    db_session.refresh(record)
    assert record.km == 32100
    assert len(record.metadata_json["work_order_lines"]) == 2
    assert record.metadata_json["work_order_lines"][0]["description"] == "Jogo de calços traseiros"
    module_ctx = vehicle_document_module_context(db_session, vehicle)
    row = next(item for item in module_ctx["structured_rows"] if item["id"] == record.id)
    assert len(row["work_order_lines"]) == 2


def test_clean_vehicle_documents_import_work_orders_deduplicates_by_number(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [
            ["1608", "2026-05-25", "CC-11-AA", "Oficina Porto", "Calços atrás gastos"],
            ["1608", "2026-05-25", "CC-11-AA", "Oficina Porto", "Calços atrás gastos repetido"],
        ],
    )

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/work-orders",
        files={"file": ("fo.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "imported_count=1" in response.headers["location"]
    records = db_session.scalars(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.main_group == "work_orders",
            VehicleDocumentRecord.external_reference == "1608",
        )
    ).all()
    assert len(records) == 1
    assert records[0].vehicle_id == vehicle.id


def test_clean_document_detail_page_renders_in_v2(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    document = Document(
        title="Fatura oficina",
        document_type="workshop_supplier_invoice",
        classification="invoice",
        source="v2_clean_manual",
        entry_channel="v2_clean",
        original_name="fatura.pdf",
        file_name="fatura.pdf",
        file_type="pdf",
        file_size=2048,
        storage_provider="local",
        storage_path="/tmp/fatura.pdf",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        status="archived",
    )
    db_session.add(document)
    db_session.commit()

    response = authenticated_client.get(f"/v2-clean/documents/{document.id}")

    assert response.status_code == 200
    assert "Fatura oficina" in response.text
    assert vehicle.plate in response.text
    assert "Voltar à documentação" in response.text


def test_clean_vehicle_documents_import_work_orders_stays_on_current_vehicle(authenticated_client, db_session):
    current_vehicle = _create_vehicle(db_session)
    target_vehicle = Vehicle(
        plate="BB-69-TE",
        vin="VINBB69TE123456789",
        brand="CITROEN",
        model="BERLINGO",
        version="XL",
        rentway_unit_nr="244",
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(target_vehicle)
    db_session.commit()
    db_session.refresh(target_vehicle)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [["1682", "2026-06-22", "BB-69-TE", "CARFAST RENT-A-CAR LDA (OFICINA)", "IPO"]],
    )

    response = authenticated_client.post(
        f"/v2-clean/fleet/{current_vehicle.id}/documents/import/work-orders",
        files={"file": ("fo.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith(f"/v2-clean/fleet/{current_vehicle.id}/documents")
    assert "imported_count=1" in response.headers["location"]
    target_record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == target_vehicle.id,
            VehicleDocumentRecord.main_group == "work_orders",
        )
    )
    current_record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == current_vehicle.id,
            VehicleDocumentRecord.main_group == "work_orders",
        )
    )
    assert target_record is None
    assert current_record is not None
    assert current_record.title == "1682"
    assert current_record.plate == current_vehicle.plate


def test_clean_document_global_import_resolves_vehicle_identifier(authenticated_client, db_session):
    vehicle = Vehicle(
        plate=None,
        vin="VINBB69TE123456789",
        brand="CITROEN",
        model="BERLINGO",
        version="XL",
        rentway_unit_nr="244",
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(vehicle)
    db_session.commit()
    db_session.refresh(vehicle)
    db_session.add(
        VehicleIdentifier(
            vehicle_id=vehicle.id,
            identifier_type="plate",
            identifier_value="BB-69-TE",
            source_system="test",
            active=True,
        )
    )
    db_session.commit()
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [["1682", "2026-06-22", "BB-69-TE", "CARFAST RENT-A-CAR LDA (OFICINA)", "IPO"]],
    )

    response = authenticated_client.post(
        "/v2-clean/documents/import/work-orders",
        files={"file": ("fo.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "imported_count=1" in response.headers["location"]
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "work_orders",
        )
    )
    assert record is not None
    assert record.title == "1682"

    page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")
    assert page.status_code == 200
    assert "1682" in page.text
    assert "Folhas de obra" in page.text


def test_clean_document_center_shows_global_structured_import_rows(authenticated_client, db_session):
    vehicle = Vehicle(
        plate="BB-69-TE",
        vin="VR7EFYHT2PJ697244",
        brand="CITROEN",
        model="BERLINGO",
        version="XL 1.5 BH 100 S&S CVM6",
        rentway_unit_nr="244",
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(vehicle)
    db_session.commit()
    db_session.refresh(vehicle)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [["1682", "22/06/2026", "BB-69-TE", "CARFAST RENT-A-CAR LDA (OFICINA)", "IPO"]],
    )

    response = authenticated_client.post(
        "/v2-clean/documents/import/work-orders",
        files={
            "file": (
                "ordem_de_reparo (2).xlsx",
                workbook.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "imported_count=1" in response.headers["location"]

    page = authenticated_client.get("/v2-clean/documents")

    assert page.status_code == 200
    assert "ordem_de_reparo (2).xlsx" in page.text
    assert "linhas estruturadas" in page.text
    assert "BB-69-TE" in page.text
    assert "1682" in page.text
    assert "CARFAST RENT-A-CAR LDA (OFICINA)" in page.text


def test_clean_document_center_renders_real_invoice_for_vehicle(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    document = Document(
        title="Fatura oficina",
        document_type="invoice",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel=None,
        original_name="fatura_11168770.pdf",
        file_name="fatura_11168770.pdf",
        storage_path="Frota/CC-11-AA/fatura_11168770.pdf",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        supplier_name="Filinto Mota",
        contract_number="11168770",
        status="received",
    )
    db_session.add(document)
    db_session.commit()

    page = authenticated_client.get("/v2-clean/documents")

    assert page.status_code == 200
    assert "Faturas" in page.text
    assert "Filinto Mota" in page.text
    assert "PEUGEOT 2008" in page.text
    assert "11168770" in page.text


def test_clean_document_reprocess_structured_source_materializes_rows(authenticated_client, db_session, tmp_path):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [["1682", "2026-06-22", "CC-11-AA", "CARFAST RENT-A-CAR LDA (OFICINA)", "IPO"]],
    )
    source_path = tmp_path / "fo.xlsx"
    source_path.write_bytes(workbook.getvalue())
    source = Document(
        title="Importação Folhas de obra - CC-11-AA",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="structured_import",
        source_subject="work_orders:0",
        original_name="fo.xlsx",
        file_name="fo.xlsx",
        file_type="xlsx",
        file_size=source_path.stat().st_size,
        storage_provider="local",
        storage_path=str(source_path),
        status="archived",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        archived=True,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    response = authenticated_client.post(
        f"/v2-clean/documents/{source.id}/reprocess-structured-import",
        data={"return_url": f"/v2-clean/fleet/{vehicle.id}/documents"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "reprocessed=1" in response.headers["location"]
    assert "reprocessed_count=1" in response.headers["location"]
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "work_orders",
            VehicleDocumentRecord.external_reference == "1682",
        )
    )
    assert record is not None
    assert record.document_id == source.id
    db_session.refresh(source)
    assert source.source_subject == "work_orders:1"

    page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")
    assert page.status_code == 200
    assert "Documentação estruturada" in page.text
    assert "Reprocessar linhas" not in page.text
    assert "1682" in page.text


def test_clean_document_reprocess_legacy_source_kind_uses_filename(authenticated_client, db_session, tmp_path):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [["1682", "22/06/2026", "CC-11-AA", "CARFAST RENT-A-CAR LDA (OFICINA)", "IPO"]],
    )
    source_path = tmp_path / "ordem_de_reparo (2).xlsx"
    source_path.write_bytes(workbook.getvalue())
    source = Document(
        title="Importação Folhas de obra - CC-11-AA",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="structured_import",
        source_subject="Folhas de obra:0",
        original_name="ordem_de_reparo (2).xlsx",
        file_name="ordem_de_reparo (2).xlsx",
        file_type="xlsx",
        file_size=source_path.stat().st_size,
        storage_provider="local",
        storage_path=str(source_path),
        status="archived",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        archived=True,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    response = authenticated_client.post(
        f"/v2-clean/documents/{source.id}/reprocess-structured-import",
        data={"return_url": f"/v2-clean/fleet/{vehicle.id}/documents"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "reprocessed_count=1" in response.headers["location"]
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "work_orders",
            VehicleDocumentRecord.external_reference == "1682",
        )
    )
    assert record is not None
    assert record.document_id == source.id
    db_session.refresh(source)
    assert source.source_subject == "work_orders:1"

    module_ctx = vehicle_document_module_context(db_session, vehicle)
    assert module_ctx["group_counts"]["work_orders"] == 1
    assert any(row["title"] == "1682" for row in module_ctx["structured_rows"])
    assert any(
        any(card["group"] == "work_orders" and card["title"] == "1682" for card in event["right"])
        for event in module_ctx["timeline_events"]
    )


def test_clean_vehicle_documents_treats_legacy_import_source_as_structured(db_session):
    vehicle = _create_vehicle(db_session)
    source = Document(
        title="Importação Folhas de obra - CC-11-AA - 16/07/2026 00:03",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="v2_clean",
        source_subject="Folhas de obra:18",
        original_name="ordem_de_reparo (2).xlsx",
        file_name="ordem_de_reparo (2).xlsx",
        file_type="xlsx",
        file_size=2048,
        storage_provider="local",
        storage_path="/tmp/ordem_de_reparo.xlsx",
        status="archived",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        archived=True,
    )
    db_session.add(source)
    db_session.commit()

    module_ctx = vehicle_document_module_context(db_session, vehicle)

    assert module_ctx["archive_rows"] == []
    assert len(module_ctx["import_rows"]) == 1
    assert module_ctx["import_rows"][0]["import_kind"] == "work_orders"
    assert module_ctx["import_rows"][0]["imported_count"] == "18"


def test_clean_vehicle_documents_materializes_existing_import_source(db_session, tmp_path):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [
            ["1682", "22/06/2026", "CC-11-AA", "CARFAST RENT-A-CAR LDA (OFICINA)", "IPO"],
            ["1608", "25/05/2026", "CC-11-AA", "CARFAST RENT-A-CAR LDA (OFICINA)", "CALÇOS ATRAS GASTOS"],
        ],
    )
    source_path = tmp_path / "ordem_de_reparo (2).xlsx"
    source_path.write_bytes(workbook.getvalue())
    source = Document(
        title="Importação Folhas de obra - CC-11-AA - 16/07/2026 00:03",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="structured_import",
        source_subject="work_orders:2",
        original_name="ordem_de_reparo (2).xlsx",
        file_name="ordem_de_reparo (2).xlsx",
        file_type="xlsx",
        file_size=source_path.stat().st_size,
        storage_provider="local",
        storage_path=str(source_path),
        status="archived",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        archived=True,
    )
    db_session.add(source)
    db_session.commit()
    db_session.refresh(source)

    module_ctx = vehicle_document_module_context(db_session, vehicle)

    assert module_ctx["group_counts"]["work_orders"] == 2
    assert [row["title"] for row in module_ctx["structured_rows"] if row["main_group"] == "work_orders"][:2] == [
        "1682",
        "1608",
    ]
    records = db_session.scalars(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "work_orders",
        )
    ).all()
    assert len(records) == 2
    assert {record.document_id for record in records} == {source.id}


def test_clean_vehicle_documents_import_real_work_order_headers_updates_context(authenticated_client, db_session):
    vehicle = Vehicle(
        plate="BB-69-TE",
        vin="VR7EFYHT2PJ697244",
        brand="CITROEN",
        model="BERLINGO",
        version="XL 1.5 BH 100 S&S CVM6",
        rentway_unit_nr="244",
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(vehicle)
    db_session.commit()
    db_session.refresh(vehicle)
    workbook = _make_workbook(
        ["Número", "Data", "Matrícula", "Nome fornecedor", "Observações"],
        [
            ["1682", "22/06/2026", "BB-69-TE", "CARFAST RENT-A-CAR LDA (OFICINA)", "IPO"],
            ["1608", "25/05/2026", "BB-69-TE", "CARFAST RENT-A-CAR LDA (OFICINA)", "CALÇOS ATRAS GASTOS"],
            ["1606", "25/05/2026", "BB-69-TE", "CARFAST RENT-A-CAR LDA (OFICINA)", "REVISAO"],
        ],
    )

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/work-orders",
        files={
            "file": (
                "ordem_de_reparo (2).xlsx",
                workbook.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "imported_count=3" in response.headers["location"]
    module_ctx = vehicle_document_module_context(db_session, vehicle)
    assert module_ctx["group_counts"]["work_orders"] == 3
    assert [row["title"] for row in module_ctx["structured_rows"] if row["main_group"] == "work_orders"][:3] == [
        "1682",
        "1608",
        "1606",
    ]
    assert any(
        any(card["group"] == "work_orders" for card in event["right"])
        for event in module_ctx["timeline_events"]
    )


def test_clean_vehicle_documents_import_impros(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        [
            "Status",
            "Impro",
            "PlateNr",
            "Date_In",
            "Date_Out",
            "Garage",
            "Driven_Kms",
            "Impro_Type_Code",
            "Impro_Type_Description",
            "Driver_Name",
        ],
        [[
            "Open",
            "IMP-9281",
            "CC-11-AA",
            "2026-04-12",
            "2026-04-18",
            "Oficina Norte",
            42110,
            "MEC",
            "Avaria mecânica",
            "André",
        ]],
    )

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/impros",
        files={"file": ("impros.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "impros",
        )
    )
    assert record is not None
    assert record.title == "IMP-9281"
    assert record.km == 42110
    assert record.supplier_name == "Oficina Norte"
    import_source = db_session.scalar(
        select(Document).where(
            Document.vehicle_id == vehicle.id,
            Document.entry_channel == "structured_import",
            Document.source_subject == "impros:1",
        )
    )
    assert import_source is not None


def test_clean_vehicle_documents_import_contracts(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Contrato", "Matrícula", "Fornecedor", "Data início", "Data fim", "Estado", "Valor mensal", "Observações"],
        [["CTR-2026-001", "CC-11-AA", "Locadora X", "2026-01-01", "2029-01-01", "Ativo", "425.50", "Contrato de aluguer operacional"]],
    )

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/contracts",
        files={"file": ("contracts.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "contracts",
        )
    )
    assert record is not None
    assert record.title == "CTR-2026-001"
    assert record.supplier_name == "Locadora X"
    assert record.subtype == "Ativo"
    import_source = db_session.scalar(
        select(Document).where(
            Document.vehicle_id == vehicle.id,
            Document.entry_channel == "structured_import",
            Document.source_subject == "contracts:1",
        )
    )
    assert import_source is not None


def test_clean_document_center_reimport_refreshes_existing_structured_source(authenticated_client, db_session, tmp_path):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Contrato", "Matrícula", "Fornecedor", "Data início", "Data fim", "Estado", "Valor mensal", "Observações"],
        [["CTR-2026-001", "CC-11-AA", "Locadora X", "2026-01-01", "2029-01-01", "Ativo", "425.50", "Contrato de aluguer operacional"]],
    )
    workbook_bytes = workbook.getvalue()
    digest = hashlib.sha256(workbook_bytes).hexdigest()
    missing_source_path = tmp_path / "fonte-antiga-apagada.xlsx"
    source = Document(
        title="Importação Contratos - global",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="structured_import",
        source_subject="contracts:1",
        original_name="contracts.xlsx",
        file_name="contracts.xlsx",
        file_type="xlsx",
        file_hash=digest,
        file_size=len(workbook_bytes),
        storage_provider="local",
        storage_path=str(missing_source_path),
        status="archived",
        archived=True,
    )
    db_session.add(source)
    db_session.commit()
    source_id = source.id

    response = authenticated_client.post(
        "/v2-clean/documents/import/contracts",
        files={"file": ("contracts.xlsx", workbook_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    refreshed_source = db_session.get(Document, source_id)
    assert refreshed_source is not None
    assert refreshed_source.source_subject == "contracts:1"
    assert refreshed_source.storage_path
    assert Path(refreshed_source.storage_path).exists()
    assert refreshed_source.plate is None
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "contracts",
            VehicleDocumentRecord.document_id == source_id,
        )
    )
    assert record is not None
    assert record.title == "CTR-2026-001"


def test_clean_vehicle_documents_materializes_zero_count_contract_source(db_session, tmp_path):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        ["Contrato", "Matrícula", "Fornecedor", "Data início", "Data fim", "Estado", "Valor mensal", "Observações"],
        [["CTR-2026-001", "CC-11-AA", "Locadora X", "2026-01-01", "2029-01-01", "Ativo", "425.50", "Contrato de aluguer operacional"]],
    )
    source_path = tmp_path / "contratos.xlsx"
    source_path.write_bytes(workbook.getvalue())
    source = Document(
        title="Importação Contratos - CC-11-AA",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="structured_import",
        source_subject="contracts:0",
        original_name="contratos.xlsx",
        file_name="contratos.xlsx",
        file_type="xlsx",
        file_size=source_path.stat().st_size,
        storage_provider="local",
        storage_path=str(source_path),
        status="archived",
        vehicle_id=vehicle.id,
        plate=vehicle.plate,
        archived=True,
    )
    db_session.add(source)
    db_session.commit()

    module_ctx = vehicle_document_module_context(db_session, vehicle)

    assert module_ctx["group_counts"]["contracts"] == 1
    assert any(row["main_group"] == "contracts" and row["title"] == "CTR-2026-001" for row in module_ctx["structured_rows"])
    db_session.refresh(source)
    assert source.source_subject == "contracts:1"


def test_clean_document_center_materializes_zero_count_global_impro_source(db_session, tmp_path):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        [
            "Status",
            "Impro",
            "PlateNr",
            "Date_In",
            "Date_Out",
            "Garage",
            "Driven_Kms",
            "Impro_Type_Code",
            "Impro_Type_Description",
        ],
        [["Closed", "IMP-9281", "CC-11-AA", "2026-04-12", "2026-04-18", "Oficina Norte", 42110, "MEC", "Avaria mecânica"]],
    )
    source_path = tmp_path / "impros.xlsx"
    source_path.write_bytes(workbook.getvalue())
    source = Document(
        title="Importação Impros - global",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="structured_import",
        source_subject="impros:0",
        original_name="impros.xlsx",
        file_name="impros.xlsx",
        file_type="xlsx",
        file_size=source_path.stat().st_size,
        storage_provider="local",
        storage_path=str(source_path),
        status="archived",
        archived=True,
    )
    db_session.add(source)
    db_session.commit()

    center_ctx = document_center_module_context(db_session)
    vehicle_ctx = vehicle_document_module_context(db_session, vehicle)

    assert center_ctx["structured_counts"]["impros"] == 1
    assert vehicle_ctx["group_counts"]["impros"] == 1
    assert any(row["main_group"] == "impros" and row["title"] == "IMP-9281" for row in vehicle_ctx["structured_rows"])
    assert any(
        any(card["group"] == "impros" for card in event["center"])
        for event in vehicle_ctx["timeline_events"]
    )
    db_session.refresh(source)
    assert source.source_subject == "impros:1"


def test_clean_documents_counts_legacy_structured_records(db_session):
    vehicle = _create_vehicle(db_session)
    source = Document(
        title="Importação Contratos - global",
        document_type="general_fleet",
        classification="fleet",
        source="v2_clean_manual",
        entry_channel="structured_import",
        source_subject="contracts:1",
        original_name="contracts.xlsx",
        file_name="contracts.xlsx",
        file_type="xlsx",
        file_size=1024,
        storage_provider="local",
        storage_path="/tmp/contracts.xlsx",
        status="archived",
        archived=True,
    )
    db_session.add(source)
    db_session.flush()
    db_session.add(
        VehicleDocumentRecord(
            vehicle_id=vehicle.id,
            document_id=source.id,
            source_record_type="legacy_structured",
            main_group="contracts",
            status="structured",
            comparison_state="por_validar",
            external_reference="15394",
            title="RA 15394",
            plate=vehicle.plate,
            document_date=date(2026, 7, 1),
            source_system="contract_import",
        )
    )
    db_session.commit()

    center_ctx = document_center_module_context(db_session)
    vehicle_ctx = vehicle_document_module_context(db_session, vehicle)

    assert center_ctx["structured_counts"]["contracts"] == 1
    assert vehicle_ctx["group_counts"]["contracts"] == 1
    assert any(row["main_group"] == "contracts" and row["title"] == "RA 15394" for row in center_ctx["structured_rows"])
    assert any(row["main_group"] == "contracts" and row["title"] == "RA 15394" for row in vehicle_ctx["structured_rows"])


def test_clean_vehicle_documents_import_rental_agreements_format(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    workbook = _make_workbook(
        [
            "ra",
            "station",
            "creation_date",
            "ndays",
            "date_out",
            "date_in",
            "rate_code",
            "salesperson",
            "origin",
            "plate",
            "category",
            "category_requested",
            "invoiced_amount",
            "customer_name",
            "cashier_amount",
        ],
        [[
            15519,
            "VILA DAS AVES",
            "2026-07-10",
            28,
            "2026-07-10",
            "2026-08-07",
            "GR01",
            "DIRECTOS",
            "TO",
            "CC-11-AA",
            "PEUGEOT 208 OU SIMILAR (G)",
            "PEUGEOT 208 OU SIMILAR (G)",
            685.86,
            "NEGRELCAR",
            685.86,
        ]],
    )

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/contracts",
        files={"file": ("rental_agreements.xlsx", workbook.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    record = db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "contracts",
            VehicleDocumentRecord.external_reference == "15519",
        )
    )
    assert record is not None
    assert record.title == "RA 15519"
    assert record.supplier_name == "NEGRELCAR"
    assert record.document_date is not None


def test_clean_vehicle_documents_import_rentway_exports_with_preamble(authenticated_client, db_session):
    vehicle = _create_vehicle(db_session)
    impros = _make_rentway_export_workbook(
        "Impros - 13/07/2026 15:20",
        [
            "Status",
            "Impro",
            "Station_In",
            "Date_In",
            "PlateNr",
            "BrandID",
            "ModelID",
            "Driver_Name",
            "GroupID",
            "Station_Out",
            "Date_Out",
            "Garage",
            "Driven_Kms",
            "Impro_Type_Code",
            "Impro_Type_Description",
        ],
        [[
            "Closed",
            6400,
            "AEROPORTO PORTO",
            "2026-01-12",
            "CC-11-AA",
            "CITROEN",
            "BERLINGO",
            "Filinto Mota",
            "2",
            "OFICINA",
            "2026-01-06",
            "",
            51,
            "0010",
            "OFICINA",
        ]],
    )
    contracts = _make_rentway_export_workbook(
        "Informações de Contratos - 13/07/2026 15:21",
        [
            "ra",
            "station",
            "creation_date",
            "ndays",
            "date_out",
            "date_in",
            "rate_code",
            "salesperson",
            "origin",
            "plate",
            "category",
            "category_requested",
            "invoiced_amount",
            "customer_name",
            "cashier_amount",
        ],
        [[
            48,
            "AEROPORTO PORTO",
            "2024-01-11",
            31,
            "2024-01-01",
            "2024-01-31",
            "CORP MENSAL",
            "DIRECTOS",
            "DIRECTOS",
            "CC-11-AA",
            "CITROEN BERLINGO OU SIMILAR",
            "CITROEN BERLINGO OU SIMILAR",
            711.91,
            "ROTA LATINA, LDA.",
            0,
        ]],
    )

    impro_response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/impros",
        files={"file": ("impros.xlsx", impros.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )
    contract_response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/import/contracts",
        files={"file": ("contracts.xlsx", contracts.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        follow_redirects=False,
    )

    assert impro_response.status_code == 303
    assert "imported_count=1" in impro_response.headers["location"]
    assert contract_response.status_code == 303
    assert "imported_count=1" in contract_response.headers["location"]
    assert db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "impros",
            VehicleDocumentRecord.external_reference == "6400",
        )
    )
    assert db_session.scalar(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.vehicle_id == vehicle.id,
            VehicleDocumentRecord.main_group == "contracts",
            VehicleDocumentRecord.external_reference == "48",
        )
    )
    module_ctx = vehicle_document_module_context(db_session, vehicle)
    assert module_ctx["group_counts"]["impros"] == 1
    assert module_ctx["group_counts"]["contracts"] == 1
    assert len(module_ctx["import_rows"]) == 2
    contract_rows = [row for row in module_ctx["structured_rows"] if row["main_group"] == "contracts"]
    assert contract_rows
    assert contract_rows[0]["period_display"] == "01/01/2024 a 31/01/2024"
    assert any(
        any(card["group"] == "contracts" and card["period"] == "01/01/2024 a 31/01/2024" for card in event["center"])
        for event in module_ctx["timeline_events"]
    )
    assert any(
        any(card["group"] == "impros" for card in event["center"])
        for event in module_ctx["timeline_events"]
    )
