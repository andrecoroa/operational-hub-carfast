from app.automotive.contracts import AutomotiveReference, VehicleSummary, WorkshopProcessSnapshot
from app.automotive.facade import AutomotiveFacade
from app.automotive.manifest import AUTOMOTIVE_MANIFEST
from app.automotive.permissions import decide_automotive_permission

__all__ = [
    "AUTOMOTIVE_MANIFEST",
    "AutomotiveFacade",
    "AutomotiveReference",
    "VehicleSummary",
    "WorkshopProcessSnapshot",
    "decide_automotive_permission",
]
