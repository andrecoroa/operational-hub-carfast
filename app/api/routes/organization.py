from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.auth import require_permission
from app.api.deps import DbSession
from app.models.organization import OrganizationalUnit, Team
from app.schemas.organization import (
    OrganizationalUnitCreate,
    OrganizationalUnitRead,
    OrganizationalUnitUpdate,
    TeamCreate,
    TeamRead,
    TeamUpdate,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/organization")
SettingsManager = Annotated[object, Depends(require_permission("settings.manage"))]
OrganizationReader = Annotated[
    object, Depends(require_permission("admin.organization.read"))
]


@router.get("/units", response_model=list[OrganizationalUnitRead])
def list_organizational_units(
    db: DbSession, _: OrganizationReader, include_inactive: bool = False
):
    stmt = select(OrganizationalUnit).order_by(
        OrganizationalUnit.sort_order,
        OrganizationalUnit.name,
    )
    if not include_inactive:
        stmt = stmt.where(OrganizationalUnit.active.is_(True))
    return db.scalars(stmt).all()


@router.post(
    "/units",
    response_model=OrganizationalUnitRead,
    status_code=status.HTTP_201_CREATED,
)
def create_organizational_unit(
    payload: OrganizationalUnitCreate,
    db: DbSession,
    _: SettingsManager,
):
    existing = db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code == payload.code))
    if existing:
        raise HTTPException(status_code=409, detail="Organizational unit code already exists.")

    if payload.parent_id and not db.get(OrganizationalUnit, payload.parent_id):
        raise HTTPException(status_code=400, detail="Parent unit does not exist.")

    unit = OrganizationalUnit(**payload.model_dump())
    db.add(unit)
    db.flush()
    record_audit(
        db,
        action="organization.unit.created",
        entity_type="organizational_unit",
        entity_id=unit.id,
        after_json=payload.model_dump(),
    )
    db.commit()
    db.refresh(unit)
    return unit


@router.patch("/units/{unit_id}", response_model=OrganizationalUnitRead)
def update_organizational_unit(
    unit_id: int,
    payload: OrganizationalUnitUpdate,
    db: DbSession,
    _: SettingsManager,
):
    unit = db.get(OrganizationalUnit, unit_id)
    if not unit:
        raise HTTPException(status_code=404, detail="Organizational unit not found.")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("parent_id") == unit_id:
        raise HTTPException(status_code=400, detail="A unit cannot be its own parent.")
    if changes.get("parent_id") and not db.get(OrganizationalUnit, changes["parent_id"]):
        raise HTTPException(status_code=400, detail="Parent unit does not exist.")

    before = {
        "name": unit.name,
        "unit_type": unit.unit_type,
        "parent_id": unit.parent_id,
        "active": unit.active,
    }
    for field, value in changes.items():
        setattr(unit, field, value)
    record_audit(
        db,
        action="organization.unit.updated",
        entity_type="organizational_unit",
        entity_id=unit.id,
        before_json=before,
        after_json=changes,
    )
    db.commit()
    db.refresh(unit)
    return unit


@router.get("/teams", response_model=list[TeamRead])
def list_teams(db: DbSession, _: OrganizationReader, include_inactive: bool = False):
    stmt = select(Team).order_by(Team.name)
    if not include_inactive:
        stmt = stmt.where(Team.active.is_(True))
    return db.scalars(stmt).all()


@router.post("/teams", response_model=TeamRead, status_code=status.HTTP_201_CREATED)
def create_team(payload: TeamCreate, db: DbSession, _: SettingsManager):
    existing = db.scalar(select(Team).where(Team.code == payload.code))
    if existing:
        raise HTTPException(status_code=409, detail="Team code already exists.")

    if payload.organizational_unit_id and not db.get(
        OrganizationalUnit,
        payload.organizational_unit_id,
    ):
        raise HTTPException(status_code=400, detail="Organizational unit does not exist.")

    team = Team(**payload.model_dump())
    db.add(team)
    db.flush()
    record_audit(
        db,
        action="organization.team.created",
        entity_type="team",
        entity_id=team.id,
        after_json=payload.model_dump(),
    )
    db.commit()
    db.refresh(team)
    return team


@router.patch("/teams/{team_id}", response_model=TeamRead)
def update_team(team_id: int, payload: TeamUpdate, db: DbSession, _: SettingsManager):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found.")

    changes = payload.model_dump(exclude_unset=True)
    if changes.get("organizational_unit_id") and not db.get(
        OrganizationalUnit,
        changes["organizational_unit_id"],
    ):
        raise HTTPException(status_code=400, detail="Organizational unit does not exist.")

    before = {
        "name": team.name,
        "organizational_unit_id": team.organizational_unit_id,
        "active": team.active,
    }
    for field, value in changes.items():
        setattr(team, field, value)
    record_audit(
        db,
        action="organization.team.updated",
        entity_type="team",
        entity_id=team.id,
        before_json=before,
        after_json=changes,
    )
    db.commit()
    db.refresh(team)
    return team
