from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import require_permission
from app.api.deps import DbSession
from app.models.organization import OrganizationalUnit
from app.models.vehicles import Vehicle
from app.schemas.vehicles import VehicleCreate, VehicleRead, VehicleUpdate
from app.services.audit import record_audit
from app.services.vehicles import (
    find_vehicle_by_any_identifier,
    normalize_identifier,
    sync_vehicle_identifiers,
)

router = APIRouter(prefix="/vehicles")
VehicleReader = Annotated[object, Depends(require_permission("vehicles.read"))]
VehicleWriter = Annotated[object, Depends(require_permission("vehicles.write"))]


@router.get("", response_model=list[VehicleRead])
def list_vehicles(
    db: DbSession,
    q: str | None = None,
    lifecycle_status: str | None = None,
    operational_status: str | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    _: VehicleReader = None,
):
    stmt = select(Vehicle).order_by(Vehicle.plate, Vehicle.id).limit(limit).offset(offset)
    if not include_inactive:
        stmt = stmt.where(Vehicle.active.is_(True))
    if lifecycle_status:
        stmt = stmt.where(Vehicle.lifecycle_status == lifecycle_status)
    if operational_status:
        stmt = stmt.where(Vehicle.operational_status == operational_status)
    if q:
        normalized = normalize_identifier(q)
        stmt = stmt.where(
            (Vehicle.plate == normalized)
            | (Vehicle.vin == normalized)
            | (Vehicle.rentway_unit_nr == normalized)
            | Vehicle.brand.ilike(f"%{q}%")
            | Vehicle.model.ilike(f"%{q}%")
        )
    return db.scalars(stmt).all()


@router.post("", response_model=VehicleRead, status_code=status.HTTP_201_CREATED)
def create_vehicle(payload: VehicleCreate, db: DbSession, _: VehicleWriter = None):
    plate = normalize_identifier(payload.plate)
    vin = normalize_identifier(payload.vin)
    rentway_unit_nr = normalize_identifier(payload.rentway_unit_nr)

    existing = find_vehicle_by_any_identifier(db, plate=plate, vin=vin, rentway_unit_nr=rentway_unit_nr)
    if existing:
        raise HTTPException(status_code=409, detail="Vehicle already exists with one identifier.")

    if payload.current_location_id and not db.get(OrganizationalUnit, payload.current_location_id):
        raise HTTPException(status_code=400, detail="Location does not exist.")

    vehicle = Vehicle(
        **{
            **payload.model_dump(),
            "plate": plate,
            "vin": vin,
            "rentway_unit_nr": rentway_unit_nr,
        }
    )
    db.add(vehicle)
    db.flush()
    sync_vehicle_identifiers(db, vehicle)
    record_audit(
        db,
        action="vehicle.created",
        entity_type="vehicle",
        entity_id=vehicle.id,
        after_json=payload.model_dump(),
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Vehicle identifier already exists.") from exc
    db.refresh(vehicle)
    return vehicle


@router.get("/lookup", response_model=VehicleRead)
def lookup_vehicle(
    db: DbSession,
    plate: str | None = None,
    vin: str | None = None,
    rentway_unit_nr: str | None = None,
    _: VehicleReader = None,
):
    vehicle = find_vehicle_by_any_identifier(
        db,
        plate=plate,
        vin=vin,
        rentway_unit_nr=rentway_unit_nr,
    )
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle


@router.get("/{vehicle_id}", response_model=VehicleRead)
def get_vehicle(vehicle_id: int, db: DbSession, _: VehicleReader = None):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")
    return vehicle


@router.patch("/{vehicle_id}", response_model=VehicleRead)
def update_vehicle(vehicle_id: int, payload: VehicleUpdate, db: DbSession, _: VehicleWriter = None):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found.")

    changes = payload.model_dump(exclude_unset=True)
    if "plate" in changes:
        changes["plate"] = normalize_identifier(changes["plate"])
    if "vin" in changes:
        changes["vin"] = normalize_identifier(changes["vin"])
    if "rentway_unit_nr" in changes:
        changes["rentway_unit_nr"] = normalize_identifier(changes["rentway_unit_nr"])

    if changes.get("current_location_id") and not db.get(
        OrganizationalUnit,
        changes["current_location_id"],
    ):
        raise HTTPException(status_code=400, detail="Location does not exist.")

    before = {
        "plate": vehicle.plate,
        "vin": vehicle.vin,
        "rentway_unit_nr": vehicle.rentway_unit_nr,
        "lifecycle_status": vehicle.lifecycle_status,
        "operational_status": vehicle.operational_status,
    }
    for field, value in changes.items():
        setattr(vehicle, field, value)
    db.flush()
    sync_vehicle_identifiers(db, vehicle)
    record_audit(
        db,
        action="vehicle.updated",
        entity_type="vehicle",
        entity_id=vehicle.id,
        before_json=before,
        after_json=changes,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Vehicle identifier already exists.") from exc
    db.refresh(vehicle)
    return vehicle
