from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import User
from app.models.case_workflow import OperationalCase
from app.models.documents import Document
from app.models.integrations import EmailIntake
from app.models.organization import Team, UserOrganizationalUnit
from app.models.tasks import Task
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.services.authorization import get_user_permission_codes

ACTION_PERMISSIONS = {
    "read": "cases.read",
    "write": "cases.update",
    "execute": "process.instances.execute",
    "delegate": "process.instances.delegate",
    "validate": "process.instances.validate",
    "close_override": "cases.close_override",
    "reopen": "cases.reopen",
}

LINK_RULES = {
    "vehicle": (
        Vehicle,
        {"read": {"vehicles.read", "vehicles.write"}, "write": {"vehicles.write"}},
    ),
    "document": (
        Document,
        {"read": {"documents.read", "documents.write"}, "write": {"documents.write"}},
    ),
    "task": (
        Task,
        {
            "read": {"tasks.read", "tasks.operational.read", "tasks.operational.write"},
            "write": {"tasks.operational.write"},
        },
    ),
    "email": (
        EmailIntake,
        {
            "read": {"tasks.administration.read", "tasks.administration.write"},
            "write": {"tasks.administration.write"},
        },
    ),
    "workshop": (
        WorkshopProcess,
        {"read": {"workshop.read", "workshop.write"}, "write": {"workshop.write"}},
    ),
}


def can_access_case(db: Session, user: User, case: OperationalCase, action: str) -> bool:
    if not user.active or case.deleted_at:
        return False
    permissions = get_user_permission_codes(db, user)
    required = ACTION_PERMISSIONS.get(action)
    if not required or required not in permissions or case.organizational_unit_id is None:
        return False
    return bool(
        db.scalar(
            select(UserOrganizationalUnit.id).where(
                UserOrganizationalUnit.user_id == user.id,
                UserOrganizationalUnit.organizational_unit_id == case.organizational_unit_id,
            )
        )
    )


def _target_unit_id(db: Session, link_type: str, target: object) -> int | None:
    if link_type == "vehicle":
        return target.current_location_id
    if link_type == "document":
        vehicle = db.get(Vehicle, target.vehicle_id) if target.vehicle_id else None
        return vehicle.current_location_id if vehicle else None
    if link_type == "task":
        team = db.get(Team, target.team_id) if target.team_id else None
        return team.organizational_unit_id if team else None
    if link_type == "workshop":
        vehicle = db.get(Vehicle, target.vehicle_id)
        return vehicle.current_location_id if vehicle else None
    return None


def can_access_link(
    db: Session,
    user: User,
    case: OperationalCase,
    action: str,
    link_type: str,
    target: object | None,
) -> bool:
    if not can_access_case(db, user, case, action):
        return False
    rule = LINK_RULES.get(link_type)
    if not rule or target is None or not isinstance(target, rule[0]):
        return False
    permissions = get_user_permission_codes(db, user)
    allowed = rule[1].get(action, set())
    if not (permissions & allowed):
        return False
    target_unit_id = _target_unit_id(db, link_type, target)
    return target_unit_id is not None and target_unit_id == case.organizational_unit_id
