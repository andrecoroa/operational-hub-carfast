import hashlib
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imports import ImportBatch, ImportFile, ImportRawRow
from app.models.vehicles import Vehicle, VehicleExternalSnapshot
from app.models.workshop import WorkshopProcess
from app.models.workshop_phased import WorkshopPhasedProcess
from app.services.audit import record_audit
from app.services.spreadsheets import (
    build_column_lookup,
    clean_int,
    clean_text,
    excel_date_to_iso,
    first_row_value,
    iter_xlsx_rows,
)
from app.services.vehicles import (
    find_vehicle_by_any_identifier,
    normalize_identifier,
    sync_vehicle_identifiers,
)


RENTWAY_FIELD_LABELS = {
    "plate": "Matrícula",
    "vin": "Chassis/VIN",
    "rentway_unit_nr": "Unit",
    "brand": "Marca",
    "model": "Modelo",
    "version": "Versão",
    "year": "Ano",
    "rentway_category": "Categoria",
    "rentway_group": "Grupo Rentway",
    "rentway_fuel": "Combustível",
    "rentway_seats": "Lugares",
    "rentway_colour": "Cor",
    "rentway_status": "Estado Rentway",
    "rentway_client": "Cliente atual",
    "rentway_return_date": "Devolução prevista",
    "rentway_ipo_date": "IPO Rentway",
    "rentway_registration_date": "Data de matrícula",
    "rentway_km": "KM",
    "rentway_location": "Localização",
    "lifecycle_status": "Estado de ciclo de vida",
    "operational_status": "Estado operacional",
    "active": "Ativa",
    "notes": "Observações",
}

WORKSHOP_PROTECTED_VEHICLE_FIELDS = frozenset(
    {"active", "lifecycle_status", "operational_status"}
)


def has_open_workshop_process(db: Session, vehicle_id: int) -> bool:
    phased_open = db.scalar(
        select(WorkshopPhasedProcess.id).where(
            WorkshopPhasedProcess.vehicle_id == vehicle_id,
            WorkshopPhasedProcess.status.notin_(("closed", "cancelled")),
        ).limit(1)
    )
    if phased_open:
        return True
    return bool(
        db.scalar(
            select(WorkshopProcess.id).where(
                WorkshopProcess.vehicle_id == vehicle_id,
                WorkshopProcess.closed_at.is_(None),
                WorkshopProcess.status.notin_(("closed", "cancelled")),
            ).limit(1)
        )
    )


def preserve_open_workshop_vehicle_state(
    db: Session, vehicle: Vehicle, payload: dict[str, Any]
) -> None:
    if not has_open_workshop_process(db, vehicle.id):
        return
    for field in WORKSHOP_PROTECTED_VEHICLE_FIELDS:
        payload[field] = getattr(vehicle, field)


def _rentway_value(row: tuple[Any, ...], col: dict[str, int], *candidates: str) -> Any:
    """Read a Rentway value using normalized real-export header variants."""

    return first_row_value(row, col, list(candidates))


def _date_value(value: Any) -> date | None:
    normalized = excel_date_to_iso(value)
    if not normalized:
        return None
    try:
        return date.fromisoformat(str(normalized)[:10])
    except ValueError:
        return None


def normalize_rentway_category(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    normalized = text.casefold()
    if any(token in normalized for token in ("comerc", "commercial", "cargo", "van", "furg")):
        return "Comerciais"
    if any(token in normalized for token in ("ligeir", "passage", "passenger", "car")):
        return "Ligeiros"
    return None


def clean_seats(value: Any) -> int | None:
    seats = clean_int(value)
    # Some Rentway exports use zero as the default for an unknown seat count.
    return seats if seats is not None and seats > 0 else None


def _audit_value(value: Any) -> Any:
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def rentway_status_to_states(current_status: str | None, status: str | None) -> tuple[str, str | None, bool]:
    current = (current_status or "").strip().upper()
    raw_status = str(status or "").strip()
    if "SOLD" in current or "RETURNED" in current or raw_status == "4":
        return "sold", "sold", False
    if "IMPRO" in current or raw_status == "3":
        return "active", "in_impro", True
    if "FREE" in current:
        return "active", "free", True
    if "SHORT" in current or "MID" in current or "RENT" in current or raw_status in {"1", "2"}:
        return "active", "in_contract", True
    return "active", clean_text(current_status), True


def build_vehicle_payload(row: tuple[Any, ...], col: dict[str, int]) -> dict[str, Any] | None:
    plate = normalize_identifier(
        clean_text(_rentway_value(row, col, "PlateNr", "Plate Nr", "Matrícula", "Matricula", "Plate"))
    )
    vin = normalize_identifier(
        clean_text(_rentway_value(row, col, "ChassisNr", "Chassis Nr", "VIN", "Chassis"))
    )
    rentway_unit_nr = normalize_identifier(
        clean_text(
            _rentway_value(
                row,
                col,
                "UnitNr",
                "Unit Nr",
                "Unit",
                "Rentway UnitNr",
                "Rentway Unit",
                "RentwayId",
            )
        )
    )
    if not (plate or vin or rentway_unit_nr):
        return None

    current_status = clean_text(
        _rentway_value(
            row,
            col,
            "CurrentStatus",
            "Current Status",
            "Estado Rentway",
            "Estado atual",
            "current_status_rentway",
        )
    )
    status = clean_text(_rentway_value(row, col, "Status", "Status Rentway", "status_rentway"))
    imported_lifecycle = clean_text(first_row_value(row, col, ["estado_frota", "lifecycle_status"]))
    imported_operational = clean_text(first_row_value(row, col, ["estado_operacional", "operational_status"]))
    lifecycle_status, operational_status, active = rentway_status_to_states(current_status, status)
    if imported_lifecycle:
        lifecycle_status = map_lifecycle_status(imported_lifecycle)
    if imported_operational:
        operational_status = map_operational_status(imported_operational)
    imported_active = first_row_value(row, col, ["ativo", "ativa_operacional", "active"])
    if imported_active not in (None, ""):
        active = str(imported_active).strip().lower() not in {"0", "false", "nao", "não", "no"}

    raw_category = _rentway_value(
        row,
        col,
        "Category",
        "VehicleCategory",
        "Vehicle Category",
        "Categoria",
        "Tipo de viatura",
        "VehicleType",
    )

    return {
        "plate": plate,
        "vin": vin,
        "rentway_unit_nr": rentway_unit_nr,
        "brand": clean_text(_rentway_value(row, col, "BrandId", "Brand", "Marca")),
        "model": clean_text(_rentway_value(row, col, "ModelId", "Model", "Modelo")),
        "version": clean_text(_rentway_value(row, col, "Version", "Versão", "Versao")),
        "year": clean_int(_rentway_value(row, col, "Year", "Ano")),
        "lifecycle_status": lifecycle_status,
        "operational_status": operational_status,
        "rentway_category": normalize_rentway_category(raw_category),
        "rentway_group": clean_text(
            _rentway_value(
                row,
                col,
                "GroupId",
                "Group ID",
                "RentwayGroup",
                "Grupo Rentway",
                "Grupo",
            )
        ),
        "rentway_fuel": clean_text(
            _rentway_value(row, col, "Fuel", "FuelType", "Fuel Type", "Combustível", "Combustivel")
        ),
        "rentway_seats": clean_seats(
            _rentway_value(
                row,
                col,
                "Seats",
                "SeatCount",
                "Seat Count",
                "NumberOfSeats",
                "Lugares",
                "N.º lugares",
                "Nº Lugares",
            )
        ),
        "rentway_colour": clean_text(_rentway_value(row, col, "Colour", "Color", "Cor")),
        "rentway_status": current_status,
        "rentway_client": clean_text(
            _rentway_value(
                row,
                col,
                "Client",
                "ClientName",
                "Client Name",
                "Customer",
                "CustomerName",
                "Cliente",
                "Cliente atual",
            )
        ),
        "rentway_return_date": _date_value(
            _rentway_value(
                row,
                col,
                "ReturnDate",
                "Return Date",
                "ExpectedReturnDate",
                "Expected Return Date",
                "Data prevista de devolução",
                "Data devolução",
                "Data de devolução",
            )
        ),
        "rentway_ipo_date": _date_value(
            _rentway_value(
                row,
                col,
                "InspectionDate",
                "Inspection Date",
                "NextInspectionDate",
                "IPODate",
                "IPO Date",
                "Data IPO",
                "Próxima IPO",
                "Proxima IPO",
            )
        ),
        "rentway_registration_date": _date_value(
            _rentway_value(
                row,
                col,
                "PlateDate",
                "Plate Date",
                "RegistrationDate",
                "Registration Date",
                "Data matrícula",
                "Data de matrícula",
            )
        ),
        "rentway_km": clean_int(
            _rentway_value(row, col, "Kms", "KM", "Km", "Odometer", "CurrentKm", "Quilómetros")
        ),
        "rentway_location": clean_text(
            _rentway_value(
                row,
                col,
                "RentalStation",
                "Rental Station",
                "Station",
                "Location",
                "Estação",
                "Localização",
            )
        ),
        "active": active,
        "notes": clean_text(first_row_value(row, col, ["observations", "observacoes"])),
    }


def map_lifecycle_status(value: str) -> str:
    text = value.strip().lower()
    mapping = {
        "ativa": "active",
        "activo": "active",
        "active": "active",
        "em venda": "for_sale",
        "vendida": "sold",
        "sold": "sold",
        "baixada": "inactive",
        "abatida": "written_off",
    }
    return mapping.get(text, text.replace(" ", "_"))


def map_operational_status(value: str) -> str:
    text = value.strip().lower()
    mapping = {
        "em contrato": "in_contract",
        "livre": "free",
        "em impro": "in_impro",
        "em preparacao": "in_preparation",
        "em preparação": "in_preparation",
        "bloqueada": "blocked",
        "bloqueado": "blocked",
        "em manutencao": "in_maintenance",
        "em manutenção": "in_maintenance",
        "reservada": "reserved",
        "reservado": "reserved",
        "em transferencia": "in_transfer",
        "em transferência": "in_transfer",
        "vendida": "sold",
    }
    return mapping.get(text, text.replace(" ", "_"))


def import_rentway_fleet_xlsx(
    db: Session,
    path: str | Path,
    original_name: str | None = None,
    imported_by_id: int | None = None,
    storage_path: str | Path | None = None,
) -> dict[str, int]:
    file_path = Path(path)
    stats = {
        "total_rows": 0,
        "created_rows": 0,
        "updated_rows": 0,
        "skipped_rows": 0,
        "error_rows": 0,
    }
    batch = ImportBatch(
        source_system="rentway",
        import_type="rentway_fleet",
        status="running",
        imported_by_id=imported_by_id,
    )
    db.add(batch)
    db.flush()

    sheet_name = None
    headers: list[str] = []
    try:
        for sheet_name, headers, row_number, row, raw in iter_xlsx_rows(file_path, preferred_sheet="Vehicles"):
            if not db.scalar(select(ImportFile).where(ImportFile.batch_id == batch.id)):
                db.add(
                    ImportFile(
                        batch_id=batch.id,
                        original_name=original_name or file_path.name,
                        file_name=file_path.name,
                        storage_path=str(storage_path or file_path),
                        sheet_name=sheet_name,
                        columns_json=headers,
                    )
                )
            col = build_column_lookup(headers)
            stats["total_rows"] += 1
            raw_json = json.dumps(raw, ensure_ascii=False, default=str, sort_keys=True)
            raw_hash = hashlib.sha1(raw_json.encode("utf-8")).hexdigest()
            payload = build_vehicle_payload(row, col)
            external_reference = (
                payload.get("plate") or payload.get("vin") or payload.get("rentway_unit_nr")
                if payload
                else None
            )
            db.add(
                ImportRawRow(
                    batch_id=batch.id,
                    row_number=row_number,
                    external_reference=external_reference,
                    raw_json=raw,
                    row_hash=raw_hash,
                )
            )
            if not payload:
                stats["skipped_rows"] += 1
                continue

            vehicle = find_vehicle_by_any_identifier(
                db,
                plate=payload["plate"],
                vin=payload["vin"],
                rentway_unit_nr=payload["rentway_unit_nr"],
            )
            before_payload: dict[str, Any] = {}
            if vehicle:
                # Rentway updates the live fleet record and its external snapshot only.
                # Historical workshop mileage belongs to the workshop process and is
                # deliberately never synchronized from this payload.
                before_payload = {field: getattr(vehicle, field, None) for field in payload}
                preserve_open_workshop_vehicle_state(db, vehicle, payload)
                for field, value in payload.items():
                    setattr(vehicle, field, value)
                stats["updated_rows"] += 1
            else:
                vehicle = Vehicle(**payload)
                db.add(vehicle)
                db.flush()
                stats["created_rows"] += 1

            sync_vehicle_identifiers(db, vehicle)
            upsert_external_snapshot(db, vehicle.id, batch.id, raw, raw_hash)
            changed_fields = {
                field: {"before": before_payload.get(field), "after": value}
                for field, value in payload.items()
                if before_payload.get(field) != value
            }
            record_audit(
                db,
                action="vehicle.rentway_snapshot.applied",
                entity_type="vehicle",
                entity_id=vehicle.id,
                detail=f"Rentway aplicado a {vehicle.plate or vehicle.rentway_unit_nr or vehicle.id}",
                before_json={field: _audit_value(values["before"]) for field, values in changed_fields.items()},
                after_json={field: _audit_value(values["after"]) for field, values in changed_fields.items()},
                user_id=imported_by_id,
            )

        batch.status = "completed"
        batch.total_rows = stats["total_rows"]
        batch.created_rows = stats["created_rows"]
        batch.updated_rows = stats["updated_rows"]
        batch.skipped_rows = stats["skipped_rows"]
        batch.error_rows = stats["error_rows"]
        record_audit(
            db,
            action="import.rentway_fleet.completed",
            entity_type="import_batch",
            entity_id=batch.id,
            after_json=stats,
            user_id=imported_by_id,
        )
        db.commit()
    except Exception:
        batch.status = "failed"
        batch.total_rows = stats["total_rows"]
        batch.error_rows = stats["error_rows"] + 1
        db.commit()
        raise

    return {"batch_id": batch.id, **stats}


def preview_rentway_fleet_xlsx(
    db: Session,
    path: str | Path,
    *,
    sample_limit: int = 25,
) -> dict[str, Any]:
    """Inspect a Rentway fleet sheet without creating or updating any row."""

    file_path = Path(path)
    preview_rows: list[dict[str, Any]] = []
    counts = {"total_rows": 0, "created_rows": 0, "updated_rows": 0, "skipped_rows": 0}
    headers: list[str] = []
    sheet_name = ""
    for current_sheet, current_headers, row_number, row, _raw in iter_xlsx_rows(
        file_path,
        preferred_sheet="Vehicles",
    ):
        sheet_name = current_sheet
        headers = current_headers
        counts["total_rows"] += 1
        payload = build_vehicle_payload(row, build_column_lookup(headers))
        if not payload:
            counts["skipped_rows"] += 1
            if len(preview_rows) < sample_limit:
                preview_rows.append(
                    {
                        "row_number": row_number,
                        "identifier": "-",
                        "action": "ignored",
                        "changes": [],
                    }
                )
            continue
        vehicle = find_vehicle_by_any_identifier(
            db,
            plate=payload["plate"],
            vin=payload["vin"],
            rentway_unit_nr=payload["rentway_unit_nr"],
        )
        action = "updated" if vehicle else "created"
        counts[f"{action}_rows"] += 1
        if vehicle:
            preserve_open_workshop_vehicle_state(db, vehicle, payload)
        changes = []
        for field, value in payload.items():
            old_value = getattr(vehicle, field, None) if vehicle else None
            if old_value != value:
                changes.append(
                    {
                        "field": field,
                        "label": RENTWAY_FIELD_LABELS.get(field, field),
                        "before": old_value.isoformat() if isinstance(old_value, (date, datetime)) else old_value,
                        "after": value.isoformat() if isinstance(value, (date, datetime)) else value,
                    }
                )
        if len(preview_rows) < sample_limit:
            preview_rows.append(
                {
                    "row_number": row_number,
                    "identifier": payload["plate"] or payload["vin"] or payload["rentway_unit_nr"],
                    "action": action,
                    "changes": changes,
                    "brand": payload.get("brand"),
                    "model": payload.get("model"),
                }
            )
    return {
        **counts,
        "sheet_name": sheet_name,
        "headers": headers,
        "rows": preview_rows,
        "preview_truncated": counts["total_rows"] > len(preview_rows),
    }


def upsert_external_snapshot(
    db: Session,
    vehicle_id: int,
    batch_id: int,
    raw: dict[str, Any],
    raw_hash: str,
) -> None:
    snapshot = db.scalar(
        select(VehicleExternalSnapshot).where(
            VehicleExternalSnapshot.vehicle_id == vehicle_id,
            VehicleExternalSnapshot.source_system == "rentway",
        )
    )
    if snapshot:
        snapshot.import_batch_id = batch_id
        snapshot.data_json = raw
        snapshot.data_hash = raw_hash
        return
    db.add(
        VehicleExternalSnapshot(
            vehicle_id=vehicle_id,
            source_system="rentway",
            import_batch_id=batch_id,
            data_json=raw,
            data_hash=raw_hash,
        )
    )
