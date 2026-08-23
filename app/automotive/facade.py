from __future__ import annotations

from sqlalchemy.orm import Session

from app.automotive.compat import VehicleRecord, WorkshopProcessRecord
from app.automotive.contracts import AutomotiveReference, VehicleSummary, WorkshopProcessSnapshot


class AutomotiveFacade:
    """Read boundary over vehicle identity and the current phased Workshop process."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def vehicle(self, reference: AutomotiveReference | int) -> VehicleRecord | None:
        vehicle_id = reference.id if isinstance(reference, AutomotiveReference) else reference
        return self.db.get(VehicleRecord, vehicle_id)

    def vehicle_summary(self, reference: AutomotiveReference | int) -> VehicleSummary | None:
        vehicle = self.vehicle(reference)
        if vehicle is None:
            return None
        display = " ".join(part for part in (vehicle.brand, vehicle.model) if part).strip()
        return VehicleSummary(
            reference=AutomotiveReference("vehicle", vehicle.id),
            plate=vehicle.plate,
            vin=vehicle.vin,
            display_name=display or vehicle.plate or vehicle.vin or f"Viatura {vehicle.id}",
            lifecycle_status=vehicle.lifecycle_status,
            operational_status=vehicle.operational_status,
        )

    def workshop_process(
        self, reference: AutomotiveReference | int
    ) -> WorkshopProcessRecord | None:
        process_id = reference.id if isinstance(reference, AutomotiveReference) else reference
        return self.db.get(WorkshopProcessRecord, process_id)

    def workshop_snapshot(
        self, reference: AutomotiveReference | int
    ) -> WorkshopProcessSnapshot | None:
        process = self.workshop_process(reference)
        if process is None:
            return None
        return WorkshopProcessSnapshot(
            reference=AutomotiveReference("workshop-process", process.id),
            vehicle_reference=AutomotiveReference("vehicle", process.vehicle_id)
            if process.vehicle_id
            else None,
            plate_snapshot=process.plate_snapshot,
            status=process.status,
            phase_code=process.current_phase_code,
            responsible_user_id=process.responsible_user_id,
            opened_at=process.opened_at,
            scheduled_at=process.scheduled_at,
            received_at=process.received_at,
            closed_at=process.closed_at,
        )
