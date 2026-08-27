from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.auth import require_permission
from app.api.deps import DbSession
from app.models.settings import SettingsCatalog, SettingsValue
from app.schemas.settings import (
    SettingsCatalogCreate,
    SettingsCatalogRead,
    SettingsCatalogUpdate,
    SettingsValueCreate,
    SettingsValueRead,
    SettingsValueUpdate,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/settings")
SettingsManager = Annotated[object, Depends(require_permission("settings.manage"))]
SettingsReader = Annotated[object, Depends(require_permission("admin.settings.read"))]


@router.get("/catalogs", response_model=list[SettingsCatalogRead])
def list_catalogs(db: DbSession, _: SettingsReader, include_inactive: bool = False):
    stmt = select(SettingsCatalog).order_by(SettingsCatalog.name)
    if not include_inactive:
        stmt = stmt.where(SettingsCatalog.active.is_(True))
    return db.scalars(stmt).all()


@router.post("/catalogs", response_model=SettingsCatalogRead, status_code=status.HTTP_201_CREATED)
def create_catalog(payload: SettingsCatalogCreate, db: DbSession, _: SettingsManager):
    existing = db.scalar(select(SettingsCatalog).where(SettingsCatalog.code == payload.code))
    if existing:
        raise HTTPException(status_code=409, detail="Catalog code already exists.")

    catalog = SettingsCatalog(**payload.model_dump())
    db.add(catalog)
    db.flush()
    record_audit(
        db,
        action="settings.catalog.created",
        entity_type="settings_catalog",
        entity_id=catalog.id,
        after_json=payload.model_dump(),
    )
    db.commit()
    db.refresh(catalog)
    return catalog


@router.patch("/catalogs/{catalog_id}", response_model=SettingsCatalogRead)
def update_catalog(
    catalog_id: int,
    payload: SettingsCatalogUpdate,
    db: DbSession,
    _: SettingsManager,
):
    catalog = db.get(SettingsCatalog, catalog_id)
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found.")

    changes = payload.model_dump(exclude_unset=True)
    before = {
        "name": catalog.name,
        "description": catalog.description,
        "active": catalog.active,
    }
    for field, value in changes.items():
        setattr(catalog, field, value)
    record_audit(
        db,
        action="settings.catalog.updated",
        entity_type="settings_catalog",
        entity_id=catalog.id,
        before_json=before,
        after_json=changes,
    )
    db.commit()
    db.refresh(catalog)
    return catalog


@router.get("/catalogs/{catalog_code}/values", response_model=list[SettingsValueRead])
def list_catalog_values(
    catalog_code: str,
    db: DbSession,
    _: SettingsReader,
    include_inactive: bool = False,
):
    catalog = db.scalar(select(SettingsCatalog).where(SettingsCatalog.code == catalog_code))
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found.")

    stmt = (
        select(SettingsValue)
        .where(SettingsValue.catalog_id == catalog.id)
        .order_by(SettingsValue.sort_order, SettingsValue.label)
    )
    if not include_inactive:
        stmt = stmt.where(SettingsValue.active.is_(True))
    return db.scalars(stmt).all()


@router.post(
    "/catalogs/{catalog_code}/values",
    response_model=SettingsValueRead,
    status_code=status.HTTP_201_CREATED,
)
def create_catalog_value(
    catalog_code: str,
    payload: SettingsValueCreate,
    db: DbSession,
    _: SettingsManager,
):
    catalog = db.scalar(select(SettingsCatalog).where(SettingsCatalog.code == catalog_code))
    if not catalog:
        raise HTTPException(status_code=404, detail="Catalog not found.")

    existing = db.scalar(
        select(SettingsValue).where(
            SettingsValue.catalog_id == catalog.id,
            SettingsValue.code == payload.code,
        )
    )
    if existing:
        raise HTTPException(status_code=409, detail="Catalog value code already exists.")

    value = SettingsValue(catalog_id=catalog.id, **payload.model_dump())
    db.add(value)
    db.flush()
    record_audit(
        db,
        action="settings.value.created",
        entity_type="settings_value",
        entity_id=value.id,
        after_json=payload.model_dump(),
    )
    db.commit()
    db.refresh(value)
    return value


@router.patch("/values/{value_id}", response_model=SettingsValueRead)
def update_catalog_value(
    value_id: int,
    payload: SettingsValueUpdate,
    db: DbSession,
    _: SettingsManager,
):
    value = db.get(SettingsValue, value_id)
    if not value:
        raise HTTPException(status_code=404, detail="Catalog value not found.")

    changes = payload.model_dump(exclude_unset=True)
    before = {
        "label": value.label,
        "active": value.active,
        "sort_order": value.sort_order,
        "color": value.color,
    }
    for field, field_value in changes.items():
        setattr(value, field, field_value)
    record_audit(
        db,
        action="settings.value.updated",
        entity_type="settings_value",
        entity_id=value.id,
        before_json=before,
        after_json=changes,
    )
    db.commit()
    db.refresh(value)
    return value
