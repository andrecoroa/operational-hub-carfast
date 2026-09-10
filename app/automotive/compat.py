"""Compatibility aliases; existing tables remain authoritative in this slice.

The legacy and phased Workshop models intentionally coexist until their process,
phase, responsibility, date and history records can be reconciled explicitly.
"""

from app.models.vehicle_sales import VehicleSaleProfile as SaleProfileRecord
from app.models.vehicles import Vehicle as VehicleRecord
from app.models.workshop import WorkshopProcess as LegacyWorkshopProcessRecord
from app.models.workshop_phased import WorkshopPhasedProcess as WorkshopProcessRecord

__all__ = [
    "LegacyWorkshopProcessRecord",
    "SaleProfileRecord",
    "VehicleRecord",
    "WorkshopProcessRecord",
]
