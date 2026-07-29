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


def _supplier_nif(value: Any) -> str:
    digits = re.sub(r"\D", "", _text(value))
    return digits if len(digits) == 9 else ""


def _invoice_key(number: Any, supplier_nif: Any) -> str:
    number_key = _document_key(number)
    nif_key = _supplier_nif(supplier_nif)
    return f"{nif_key}:{number_key}" if nif_key else number_key


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


def _existing_invoice_keys(db: Session) -> tuple[set[str], set[str]]:
    exact_keys: set[str] = set()
    number_only_keys: set[str] = set()
    records = db.scalars(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.main_group == "invoices",
            VehicleDocumentRecord.external_reference.is_not(None),
        )
    ).all()
    for record in records:
        number_key = _document_key(record.external_reference)
        if not number_key:
            continue
        nif = _supplier_nif(
            (record.metadata_json or {}).get("supplier_nif")
            or record.supplier_name
        )
        if nif:
            exact_keys.add(_invoice_key(record.external_reference, nif))
        else:
            number_only_keys.add(number_key)

    documents = db.scalars(
        select(Document).where(
            or_(
                Document.document_type.in_(
                    {"workshop_supplier_invoice", "finance_supplier_invoice"}
                ),
                Document.title.ilike("%fatura%"),
                Document.title.ilike("%factura%"),
            )
        )
    ).all()
    for document in documents:
        supplier_nif = _supplier_nif(document.supplier_name)
        for value in (document.contract_number, document.reservation_number, document.title):
            number_key = _document_key(value)
            if not number_key:
                continue
            if supplier_nif:
                exact_keys.add(_invoice_key(value, supplier_nif))
            else:
                number_only_keys.add(number_key)
    return exact_keys, number_only_keys


def _parsed_pending_rows(
    db: Session,
    *,
    path: Path,
    original_name: str,
) -> list[dict[str, Any]]:
    by_vin, by_plate, by_unit = _vehicle_maps(db)
    exact_existing_keys, number_only_existing_keys = _existing_invoice_keys(db)
    parsed_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, (sheet, row_number, row) in enumerate(_rows(path), start=1):
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
        supplier_name = _text(_first(row, ("Fornecedor", "Nome fornecedor", "Supplier")))
        supplier_nif = _supplier_nif(
            _first(row, ("NIF fornecedor", "NIF Fornecedor", "Supplier NIF", "VAT"))
        )
        duplicate_key = _invoice_key(number, supplier_nif)
        if not number_key:
            status = "invalid"
            status_detail = "Sem número de fatura"
        elif duplicate_key in seen:
            status = "duplicate"
            status_detail = "Repetida no ficheiro"
        elif duplicate_key in exact_existing_keys:
            status = "duplicate"
            status_detail = "Já existe para este NIF e número"
        elif number_key in number_only_existing_keys:
            status = "duplicate"
            status_detail = "Possível duplicado antigo com este número"
        else:
            status = "ready"
            status_detail = "Pronta para criar"
            seen.add(duplicate_key)

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
        document_date = _date(_first(row, ("Data", "Data fatura", "Data factura", "Invoice date")))
        total = _decimal(_first(row, ("Total", "Valor", "Total com IVA", "Total c/ IVA")))
        description = _text(_first(row, ("Observações", "Observacoes", "Descrição", "Descricao")))
        association_method = (
            "vin"
            if vehicle and vin and by_vin.get(vin) is vehicle
            else "plate"
            if vehicle and plate and by_plate.get(_plate_key(plate)) is vehicle
            else "unit"
            if vehicle
            else None
        )
        parsed_rows.append(
            {
                "row_id": str(index),
                "source_sheet": sheet,
                "source_row": row_number,
                "number": number,
                "supplier_name": supplier_name,
                "supplier_nif": supplier_nif,
                "document_date": document_date.isoformat() if document_date else None,
                "total": total,
                "description": description,
                "raw_vin": raw_vin,
                "vin": vin,
                "plate": plate,
                "unit_number": unit,
                "vehicle_id": vehicle.id if vehicle else None,
                "vehicle_plate": vehicle.plate if vehicle else None,
                "vehicle_label": (
                    f"{vehicle.plate} · Unit {vehicle.rentway_unit_nr}"
                    if vehicle and vehicle.rentway_unit_nr
                    else vehicle.plate
                    if vehicle
                    else None
                ),
                "association_method": association_method,
                "status": status,
                "status_detail": status_detail,
                "selected": status == "ready",
                "original_name": original_name,
            }
        )
    return parsed_rows


def preview_pending_documents(
    db: Session,
    *,
    path: Path,
    original_name: str,
) -> dict[str, Any]:
    rows = _parsed_pending_rows(db, path=path, original_name=original_name)
    return {
        "schema": "carfast.pending-invoice-preview.v1",
        "original_name": original_name,
        "rows": rows,
        "summary": {
            "total": len(rows),
            "ready": sum(row["status"] == "ready" for row in rows),
            "associated": sum(
                row["status"] == "ready" and row["vehicle_id"] is not None for row in rows
            ),
            "unmatched": sum(
                row["status"] == "ready" and row["vehicle_id"] is None for row in rows
            ),
            "duplicates": sum(row["status"] == "duplicate" for row in rows),
            "invalid": sum(row["status"] == "invalid" for row in rows),
        },
    }


def create_pending_documents_from_preview(
    db: Session,
    *,
    preview: dict[str, Any],
    selected_row_ids: set[str],
    user_id: int | None,
) -> dict[str, int]:
    result = {"created": 0, "associated": 0, "unmatched": 0, "duplicates": 0, "invalid": 0}
    exact_existing_keys, number_only_existing_keys = _existing_invoice_keys(db)
    selected_rows = [
        row
        for row in preview.get("rows", [])
        if str(row.get("row_id")) in selected_row_ids
    ]
    seen: set[str] = set()
    for row in selected_rows:
        number = _text(row.get("number"))
        number_key = _document_key(number)
        supplier_nif = _supplier_nif(row.get("supplier_nif"))
        duplicate_key = _invoice_key(number, supplier_nif)
        if not number_key or row.get("status") == "invalid":
            result["invalid"] += 1
            continue
        if (
            duplicate_key in seen
            or duplicate_key in exact_existing_keys
            or number_key in number_only_existing_keys
        ):
            result["duplicates"] += 1
            continue
        seen.add(duplicate_key)

        vehicle_id = row.get("vehicle_id")
        vehicle = db.get(Vehicle, int(vehicle_id)) if vehicle_id else None
        record = VehicleDocumentRecord(
            vehicle_id=vehicle.id if vehicle else None,
            source_record_type="pending_import",
            main_group="invoices",
            status="pending",
            external_reference=number,
            title=f"Fatura pendente {number}",
            plate=vehicle.plate if vehicle else _text(row.get("plate")) or None,
            vin=vehicle.vin if vehicle else _text(row.get("vin")) or None,
            supplier_name=_text(row.get("supplier_name")) or None,
            raw_description=_text(row.get("description")) or None,
            document_date=_date(row.get("document_date")),
            has_physical_file=False,
            source_system="pending_document_import",
            metadata_json={
                "supplier_nif": supplier_nif or None,
                "unit_number": _text(row.get("unit_number")) or None,
                "expected_total": row.get("total"),
                "source_file": preview.get("original_name"),
                "source_sheet": row.get("source_sheet"),
                "source_row": row.get("source_row"),
                "association_method": row.get("association_method"),
            },
            created_by_id=user_id,
            updated_by_id=user_id,
        )
        db.add(record)
        exact_existing_keys.add(duplicate_key)
        result["created"] += 1
        result["associated" if vehicle else "unmatched"] += 1
    db.flush()
    return result


def import_pending_documents(
    db: Session,
    *,
    path: Path,
    original_name: str,
    user_id: int | None,
) -> dict[str, int]:
    """Compatibility wrapper for non-interactive callers and existing tests."""
    preview = preview_pending_documents(db, path=path, original_name=original_name)
    selected = {
        str(row["row_id"])
        for row in preview["rows"]
        if row["status"] == "ready"
    }
    result = create_pending_documents_from_preview(
        db,
        preview=preview,
        selected_row_ids=selected,
        user_id=user_id,
    )
    result["duplicates"] += preview["summary"]["duplicates"]
    result["invalid"] += preview["summary"]["invalid"]
    return result
