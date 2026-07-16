from datetime import date
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select

from app.models.documents import Document, VehicleDocumentAuditField, VehicleDocumentRecord
from app.models.vehicles import Vehicle, VehicleManualField
from app.services.vehicle_document_history import vehicle_document_module_context


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
    module_ctx = vehicle_document_module_context(db_session, vehicle)
    assert len(module_ctx["structured_rows"]) == 1
    assert len(module_ctx["import_rows"]) == 1
    assert module_ctx["import_rows"][0]["import_label"] == "Folhas de obra"
    assert module_ctx["archive_rows"] == []

    page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/documents")
    assert page.status_code == 200
    assert "Folhas de obra" in page.text
    assert "FO-1576" in page.text
    assert "Fontes importadas" in page.text
    assert "fo.xlsx" in page.text
    assert "Classificar" in page.text
    assert f"/v2-clean/fleet/{vehicle.id}/documents/classify" in page.text

    fleet_page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}")
    assert fleet_page.status_code == 200
    assert "Folhas de obra" in fleet_page.text
    assert f"/v2-clean/fleet/{vehicle.id}/documents?main_group=work_orders" in fleet_page.text
    assert "<strong>1</strong>" in fleet_page.text


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
    contract_rows = [row for row in module_ctx["structured_rows"] if row["main_group"] == "contracts"]
    assert contract_rows
    assert contract_rows[0]["period_display"] == "01/01/2024 a 31/01/2024"
    assert any(
        any(card["group"] == "contracts" and card["period"] == "01/01/2024 a 31/01/2024" for card in event["center"])
        for event in module_ctx["timeline_events"]
    )
