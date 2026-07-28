import hashlib
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.imports import ImportBatch, ImportFile, ImportRawRow
from app.models.vehicles import Vehicle, VehicleExternalSnapshot
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
    plate = normalize_identifier(clean_text(first_row_value(row, col, ["platenr", "matricula", "plate"])))
    vin = normalize_identifier(clean_text(first_row_value(row, col, ["chassinr", "vin", "chassis"])))
    rentway_unit_nr = normalize_identifier(
        clean_text(first_row_value(row, col, ["unitnr", "rentway_unitnr", "rentway_id"]))
    )
    if not (plate or vin or rentway_unit_nr):
        return None

    current_status = clean_text(first_row_value(row, col, ["CurrentStatus", "current_status_rentway"]))
    status = clean_text(first_row_value(row, col, ["status", "status_rentway"]))
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

    return {
        "plate": plate,
        "vin": vin,
        "rentway_unit_nr": rentway_unit_nr,
        "brand": clean_text(first_row_value(row, col, ["brandid", "marca", "brand"])),
        "model": clean_text(first_row_value(row, col, ["modelid", "modelo", "model"])),
        "version": clean_text(first_row_value(row, col, ["version", "versao"])),
        "year": clean_int(first_row_value(row, col, ["Year", "ano"])),
        "lifecycle_status": lifecycle_status,
        "operational_status": operational_status,
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
                        storage_path=str(file_path),
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
            if vehicle:
                # Rentway updates the live fleet record and its external snapshot only.
                # Historical workshop mileage belongs to the workshop process and is
                # deliberately never synchronized from this payload.
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
