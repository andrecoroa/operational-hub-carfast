from __future__ import annotations

import csv
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import unicodedata
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.documents import Document, VehicleDocumentRecord
from app.models.vehicles import Vehicle


VIN_RE = re.compile(r"(?<![A-Z0-9])([A-HJ-NPR-Z0-9]{17})(?![A-Z0-9])", re.IGNORECASE)


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in text if char.isalnum() and not unicodedata.combining(char))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _document_key(value: Any) -> str:
    return _key(value)


def _plate_key(value: Any) -> str:
    return _key(value).upper()


def _vin(value: Any) -> str:
    raw = _text(value).upper()
    match = VIN_RE.search(raw)
    if match:
        return match.group(1).upper()
    compact = re.sub(r"[^A-Z0-9]", "", raw)
    return compact if len(compact) == 17 else ""


def _date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = _text(value)
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _decimal(value: Any) -> str | None:
    text = _text(value).replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return format(Decimal(text), "f")
    except InvalidOperation:
        return None


def _rows(path: Path) -> Iterator[tuple[str, int, dict[str, Any]]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row_number, row in enumerate(reader, start=2):
                yield "CSV", row_number, {_key(key): value for key, value in row.items()}
        return
    if suffix == ".xls":
        try:
            import xlrd
        except ImportError as exc:
            raise ValueError("A leitura de .xls requer a dependência xlrd.") from exc
        workbook = xlrd.open_workbook(path)
        for sheet in workbook.sheets():
            if sheet.nrows < 2:
                continue
            headers = [_key(sheet.cell_value(0, col)) for col in range(sheet.ncols)]
            for row_index in range(1, sheet.nrows):
                yield sheet.name, row_index + 1, {
                    headers[col]: sheet.cell_value(row_index, col)
                    for col in range(sheet.ncols)
                    if headers[col]
                }
        return
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        for sheet in workbook.worksheets:
            iterator = sheet.iter_rows(values_only=True)
            headers = [_key(value) for value in next(iterator, ())]
            for row_number, values in enumerate(iterator, start=2):
                yield sheet.title, row_number, {
                    headers[index]: value
                    for index, value in enumerate(values)
                    if index < len(headers) and headers[index]
                }
    finally:
        workbook.close()


def _first(row: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = row.get(_key(alias))
        if value not in (None, ""):
            return value
    return None


def _vehicle_maps(db: Session) -> tuple[dict[str, Vehicle], dict[str, Vehicle], dict[str, Vehicle]]:
    by_vin: dict[str, Vehicle] = {}
    by_plate: dict[str, Vehicle] = {}
    by_unit: dict[str, Vehicle] = {}
    for vehicle in db.scalars(select(Vehicle)).all():
        if vehicle.vin:
            by_vin[_vin(vehicle.vin)] = vehicle
        if vehicle.plate:
            by_plate[_plate_key(vehicle.plate)] = vehicle
        if vehicle.rentway_unit_nr:
            by_unit[_key(vehicle.rentway_unit_nr)] = vehicle
    return by_vin, by_plate, by_unit


def import_pending_documents(
    db: Session,
    *,
    path: Path,
    original_name: str,
    user_id: int | None,
) -> dict[str, int]:
    by_vin, by_plate, by_unit = _vehicle_maps(db)
    existing_record_keys = {
        _document_key(value)
        for value in db.scalars(
            select(VehicleDocumentRecord.external_reference).where(
                VehicleDocumentRecord.main_group == "invoices",
                VehicleDocumentRecord.external_reference.is_not(None),
            )
        ).all()
        if value
    }
    existing_document_keys: set[str] = set()
    for document in db.scalars(
        select(Document).where(
            or_(
                Document.document_type.in_(
                    {"workshop_supplier_invoice", "finance_supplier_invoice"}
                ),
                Document.title.ilike("%fatura%"),
                Document.title.ilike("%factura%"),
            )
        )
    ).all():
        for value in (document.contract_number, document.reservation_number, document.title):
            if value:
                existing_document_keys.add(_document_key(value))

    result = {"created": 0, "associated": 0, "unmatched": 0, "duplicates": 0, "invalid": 0}
    seen: set[str] = set()
    for sheet, row_number, row in _rows(path):
        number = _text(
            _first(
                row,
                (
                    "Nº fatura",
                    "Numero fatura",
                    "Número fatura",
                    "Fatura",
                    "Factura",
                    "Nº documento",
                    "Numero documento",
                    "Documento",
                    "Invoice number",
                ),
            )
        )
        number_key = _document_key(number)
        if not number_key:
            result["invalid"] += 1
            continue
        if (
            number_key in seen
            or number_key in existing_record_keys
            or number_key in existing_document_keys
        ):
            result["duplicates"] += 1
            continue
        seen.add(number_key)

        raw_vin = _text(_first(row, ("Chassi", "Chassis", "VIN", "Referência", "Referencia")))
        vin = _vin(raw_vin)
        plate = _text(_first(row, ("Matrícula", "Matricula", "Plate", "PlateNr")))
        unit = _text(
            _first(row, ("Unit", "Unit nr", "Unit number", "Nº viatura", "Numero viatura"))
        )
        vehicle = (
            by_vin.get(vin)
            or by_plate.get(_plate_key(plate))
            or by_unit.get(_key(unit))
        )
        supplier_name = _text(_first(row, ("Fornecedor", "Nome fornecedor", "Supplier")))
        supplier_nif = _text(
            _first(row, ("NIF fornecedor", "NIF Fornecedor", "Supplier NIF", "VAT"))
        )
        document_date = _date(_first(row, ("Data", "Data fatura", "Data factura", "Invoice date")))
        total = _decimal(_first(row, ("Total", "Valor", "Total com IVA", "Total c/ IVA")))
        description = _text(_first(row, ("Observações", "Observacoes", "Descrição", "Descricao")))
        record = VehicleDocumentRecord(
            vehicle_id=vehicle.id if vehicle else None,
            source_record_type="pending_import",
            main_group="invoices",
            status="pending",
            external_reference=number,
            title=f"Fatura pendente {number}",
            plate=vehicle.plate if vehicle else plate or None,
            vin=vehicle.vin if vehicle else vin or None,
            supplier_name=supplier_name or None,
            raw_description=description or None,
            document_date=document_date,
            has_physical_file=False,
            source_system="pending_document_import",
            metadata_json={
                "supplier_nif": supplier_nif or None,
                "unit_number": unit or None,
                "expected_total": total,
                "source_file": original_name,
                "source_sheet": sheet,
                "source_row": row_number,
                "association_method": (
                    "vin" if vehicle and vin and by_vin.get(vin) is vehicle
                    else "plate" if vehicle and plate and by_plate.get(_plate_key(plate)) is vehicle
                    else "unit" if vehicle else None
                ),
            },
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        db.add(record)
        existing_record_keys.add(number_key)
        result["created"] += 1
        result["associated" if vehicle else "unmatched"] += 1
    db.flush()
    return result
