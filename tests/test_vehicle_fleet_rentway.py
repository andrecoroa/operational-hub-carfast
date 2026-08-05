from datetime import date
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import select

from app.models import Document, Vehicle, VehicleExternalSnapshot, VehicleSaleProfile
from app.models.imports import ImportRawRow
from app.services.rentway_fleet_importer import (
    build_vehicle_payload,
    import_rentway_fleet_xlsx,
    normalize_rentway_gearbox,
    preview_rentway_fleet_xlsx,
)
from app.services.spreadsheets import build_column_lookup


REAL_RENTWAY_HEADERS = [
    "Plate Nr",
    "Chassis Nr",
    "Unit Nr",
    "Brand",
    "Model",
    "Vehicle Category",
    "Group ID",
    "Fuel Type",
    "Transmission Type",
    "Number Of Seats",
    "Color",
    "Current Status",
    "Client Name",
    "Expected Return Date",
    "Next Inspection Date",
    "Registration Date",
    "Current Km",
    "Rental Station",
]


def _real_rentway_row(plate: str = "AA-10-BB", seats: int = 5):
    return (
        plate,
        f"VF3{plate.replace('-', '')}000000000",
        "9901",
        "PEUGEOT",
        "PARTNER",
        "Light Commercial Vehicle",
        "C1",
        "Diesel",
        "CVM6",
        seats,
        "Branco",
        "RENT",
        "Cliente Atual, Lda.",
        "2026-10-18",
        "2026-09-30",
        "2022-01-15",
        98450,
        "Porto",
    )


def _rentway_workbook(path: Path, *, seats: int = 5) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Vehicles"
    sheet.append(REAL_RENTWAY_HEADERS)
    sheet.append(_real_rentway_row(seats=seats))
    workbook.save(path)


def test_rentway_mapping_real_headers_normalizes_filter_fields_and_zero_seats():
    payload = build_vehicle_payload(
        _real_rentway_row(seats=0),
        build_column_lookup(REAL_RENTWAY_HEADERS),
    )

    assert payload is not None
    assert payload["rentway_category"] == "Comerciais"
    assert payload["rentway_group"] == "C1"
    assert payload["rentway_fuel"] == "Diesel"
    assert payload["rentway_gearbox"] == "Manual"
    assert payload["rentway_seats"] is None
    assert payload["rentway_colour"] == "Branco"
    assert payload["rentway_status"] == "RENT"
    assert payload["rentway_client"] == "Cliente Atual, Lda."
    assert payload["rentway_return_date"] == date(2026, 10, 18)
    assert payload["rentway_ipo_date"] == date(2026, 9, 30)
    assert payload["rentway_registration_date"] == date(2022, 1, 15)
    assert payload["rentway_km"] == 98450
    assert payload["rentway_location"] == "Porto"


def test_rentway_automatic_groups_supply_gearbox_when_source_is_empty():
    for group in ("B3", "C2", "c4", "c5", "d2", "d4", "e2", "G2", "G3", "I2", "J1", "J2", "J3", "L2"):
        assert normalize_rentway_gearbox(None, None, group) == "Automática"

    assert normalize_rentway_gearbox("EAT8", None, "C2") == "Automática"
    assert normalize_rentway_gearbox(None, "1.5 BlueHDi CVM6", "C1") == "Manual"


def test_rentway_preview_lists_created_fields_and_import_keeps_raw_snapshot(
    db_session,
    tmp_path,
):
    source = tmp_path / "rentway-real.xlsx"
    _rentway_workbook(source)

    preview = preview_rentway_fleet_xlsx(db_session, source)

    assert preview["created_rows"] == 1
    changes = {change["field"]: change for change in preview["rows"][0]["changes"]}
    assert changes["rentway_group"]["label"] == "Grupo Rentway"
    assert changes["rentway_client"]["after"] == "Cliente Atual, Lda."
    assert db_session.scalar(select(Vehicle)) is None

    result = import_rentway_fleet_xlsx(db_session, source)
    vehicle = db_session.scalar(select(Vehicle).where(Vehicle.plate == "AA-10-BB"))
    raw = db_session.scalar(select(ImportRawRow).where(ImportRawRow.batch_id == result["batch_id"]))
    snapshot = db_session.scalar(
        select(VehicleExternalSnapshot).where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
    )

    assert vehicle.rentway_group == "C1"
    assert vehicle.rentway_gearbox == "Manual"
    assert vehicle.rentway_client == "Cliente Atual, Lda."
    assert raw.raw_json["Client Name"] == "Cliente Atual, Lda."
    assert snapshot.data_json["Number Of Seats"] == 5


def test_fleet_filters_and_pagination_preserve_query_page_and_return_anchor(
    authenticated_client,
    db_session,
):
    for index in range(55):
        db_session.add(
            Vehicle(
                plate=f"{index:02d}-AA-{index:02d}",
                rentway_unit_nr=f"U{index:03d}",
                brand="Peugeot" if index % 2 else "Citroen",
                model="208",
                active=True,
                lifecycle_status="active",
                operational_status="free",
                rentway_category="Ligeiros",
                rentway_group="C1",
                rentway_fuel="Diesel",
                rentway_status="FREE",
                rentway_client="Cliente Norte",
                rentway_registration_date=date(2022, 1, 15),
                rentway_return_date=date(2026, 10, 18),
                rentway_ipo_date=date(2026, 9, 30),
            )
        )
    db_session.commit()

    page = authenticated_client.get(
        "/v2-clean/fleet",
        params=[
            ("scope", "active"),
            ("brand", "Peugeot"),
            ("brand", "Citroen"),
            ("fuel", "Diesel"),
            ("category", "Ligeiros"),
            ("rentway_group", "C1"),
            ("rentway_status", "FREE"),
            ("client", "Norte"),
            ("page", "2"),
        ],
    )

    assert page.status_code == 200
    assert "Página 2 de 2 · 55 viaturas" in page.text
    assert page.text.count('class="fleet-vehicle-link"') == 5
    assert 'type="checkbox" name="brand" value="Peugeot" checked' in page.text
    assert "Encontrar as viaturas certas" in page.text
    assert "return_to=" in page.text
    assert "page%3D2" in page.text
    assert "%23vehicle-" in page.text


def test_vehicle_detail_exposes_versioned_lazy_maintenance_plan(
    authenticated_client,
    db_session,
    tmp_path,
):
    vehicle = Vehicle(
        plate="MP-10-AA",
        rentway_unit_nr="MP10",
        brand="Peugeot",
        model="208",
        active=True,
        rentway_category="Ligeiros",
        rentway_fuel="Gasolina",
    )
    db_session.add(vehicle)
    db_session.flush()
    for version in (1, 2):
        path = tmp_path / f"plano-v{version}.pdf"
        path.write_bytes(b"%PDF-1.4\n%%EOF")
        db_session.add(
            Document(
                title=f"Plano de manutenção v{version}",
                document_type="maintenance_plan",
                classification="fleet",
                source="v2_clean_manual",
                original_name=path.name,
                file_name=path.name,
                storage_provider="local",
                storage_path=str(path),
                status="received",
                vehicle_id=vehicle.id,
                plate=vehicle.plate,
            )
        )
    db_session.commit()

    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}")

    assert response.status_code == 200
    assert "Anexar plano de manutenção" in response.text
    assert "Ver plano de manutenção · versão 2" in response.text
    assert "Histórico de versões (2)" in response.text
    assert 'data-src="/v2-clean/documents/' in response.text
    iframe = response.text.split('title="Plano de manutenção"', 1)[1].split(">", 1)[0]
    assert " src=" not in iframe


def test_sales_multiselect_filters_and_return_state(
    authenticated_client,
    db_session,
):
    rows = [
        ("MS-10-AA", "Peugeot", "C1", "free", "candidate"),
        ("MS-20-BB", "Citroen", "C2", "in_contract", "for_sale"),
        ("MS-30-CC", "Ford", "C3", "free", "sold"),
    ]
    for plate, brand, group, operational, sale_status in rows:
        vehicle = Vehicle(
            plate=plate,
            rentway_unit_nr=plate,
            brand=brand,
            model="Modelo",
            active=True,
            lifecycle_status="active",
            operational_status=operational,
            rentway_group=group,
            rentway_status="FREE" if operational == "free" else "RENT",
        )
        db_session.add(vehicle)
        db_session.flush()
        db_session.add(VehicleSaleProfile(vehicle_id=vehicle.id, status=sale_status))
    db_session.commit()

    response = authenticated_client.get(
        "/v2-clean/fleet/sales",
        params=[
            ("brand", "Peugeot"),
            ("brand", "Citroen"),
            ("rentway_group", "C1"),
            ("rentway_group", "C2"),
            ("vehicle_state", "free"),
            ("vehicle_state", "contract"),
            ("sale_status", "candidate"),
            ("sale_status", "for_sale"),
            ("page", "1"),
        ],
    )

    assert response.status_code == 200
    assert "MS-10-AA" in response.text
    assert "MS-20-BB" in response.text
    assert "MS-30-CC" not in response.text
    assert response.text.count(
        'type="checkbox" name="brand" value="Peugeot" checked'
    ) == 1
    assert "return_to=" in response.text
    assert "brand%3DPeugeot" in response.text
