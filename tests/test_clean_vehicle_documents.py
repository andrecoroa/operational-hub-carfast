from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select

from app.models.documents import VehicleDocumentAuditField, VehicleDocumentRecord
from app.models.vehicles import Vehicle, VehicleManualField


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
    assert "Enquadramento documental" in response.text
    assert "Documentação de arquivo" in response.text
    assert "Documentação de listagem" in response.text
    assert "Timeline horizontal documental" in response.text
    assert "Validação manual" in response.text


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
