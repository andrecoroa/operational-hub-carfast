from sqlalchemy import or_, select, tuple_
from sqlalchemy.orm import Session

from app.models.vehicles import Vehicle, VehicleIdentifier


def normalize_identifier(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper().replace(" ", "")
    return normalized or None


def find_vehicle_by_any_identifier(
    db: Session,
    plate: str | None = None,
    vin: str | None = None,
    rentway_unit_nr: str | None = None,
) -> Vehicle | None:
    identifiers = []
    if plate := normalize_identifier(plate):
        identifiers.append(("plate", plate))
    if vin := normalize_identifier(vin):
        identifiers.append(("vin", vin))
    if rentway_unit_nr := normalize_identifier(rentway_unit_nr):
        identifiers.append(("rentway_unit_nr", rentway_unit_nr))

    if not identifiers:
        return None

    direct_conditions = []
    for identifier_type, identifier_value in identifiers:
        if identifier_type == "plate":
            direct_conditions.append(Vehicle.plate == identifier_value)
        elif identifier_type == "vin":
            direct_conditions.append(Vehicle.vin == identifier_value)
        elif identifier_type == "rentway_unit_nr":
            direct_conditions.append(Vehicle.rentway_unit_nr == identifier_value)

    found = db.scalar(select(Vehicle).where(or_(*direct_conditions)))
    if found:
        return found

    linked_identifier = db.scalar(
        select(VehicleIdentifier).where(
            tuple_(VehicleIdentifier.identifier_type, VehicleIdentifier.identifier_value).in_(identifiers)
        )
    )
    if not linked_identifier:
        return None
    return db.get(Vehicle, linked_identifier.vehicle_id)


def sync_vehicle_identifiers(db: Session, vehicle: Vehicle) -> None:
    desired = {
        "plate": normalize_identifier(vehicle.plate),
        "vin": normalize_identifier(vehicle.vin),
        "rentway_unit_nr": normalize_identifier(vehicle.rentway_unit_nr),
    }
    for identifier_type, identifier_value in desired.items():
        if not identifier_value:
            continue
        exists = db.scalar(
            select(VehicleIdentifier).where(
                VehicleIdentifier.vehicle_id == vehicle.id,
                VehicleIdentifier.identifier_type == identifier_type,
                VehicleIdentifier.identifier_value == identifier_value,
            )
        )
        if not exists:
            db.add(
                VehicleIdentifier(
                    vehicle_id=vehicle.id,
                    identifier_type=identifier_type,
                    identifier_value=identifier_value,
                    source_system="internal",
                )
            )
