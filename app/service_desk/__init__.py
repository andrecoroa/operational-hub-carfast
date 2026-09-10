from app.service_desk.compat import EmailThreadRecord, ProcessRecord, TaskRecord
from app.service_desk.contracts import EmailOriginCommand, ServiceDeskReference, WorkSummary
from app.service_desk.facade import ServiceDeskFacade
from app.service_desk.manifest import SERVICE_DESK_MANIFEST
from app.service_desk.permissions import (
    SERVICE_DESK_PERMISSION_LEGACY_MAP,
    decide_service_desk_permission,
)

__all__ = [
    "EmailOriginCommand",
    "EmailThreadRecord",
    "ProcessRecord",
    "SERVICE_DESK_MANIFEST",
    "SERVICE_DESK_PERMISSION_LEGACY_MAP",
    "ServiceDeskFacade",
    "ServiceDeskReference",
    "TaskRecord",
    "WorkSummary",
    "decide_service_desk_permission",
]
