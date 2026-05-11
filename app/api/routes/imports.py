from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.auth import require_permission
from app.api.deps import DbSession
from app.models.imports import ImportBatch, ImportError, ImportRawRow
from app.schemas.imports import (
    ImportBatchCreate,
    ImportBatchRead,
    ImportBatchUpdate,
    ImportErrorCreate,
    ImportErrorRead,
    ImportRawRowCreate,
    ImportRawRowRead,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/imports")
ImportRunner = Annotated[object, Depends(require_permission("imports.run"))]
ImportApprover = Annotated[object, Depends(require_permission("imports.approve"))]


@router.get("/batches", response_model=list[ImportBatchRead])
def list_import_batches(
    db: DbSession,
    source_system: str | None = None,
    import_type: str | None = None,
    status_filter: str | None = None,
):
    stmt = select(ImportBatch).order_by(ImportBatch.id.desc())
    if source_system:
        stmt = stmt.where(ImportBatch.source_system == source_system)
    if import_type:
        stmt = stmt.where(ImportBatch.import_type == import_type)
    if status_filter:
        stmt = stmt.where(ImportBatch.status == status_filter)
    return db.scalars(stmt).all()


@router.post("/batches", response_model=ImportBatchRead, status_code=status.HTTP_201_CREATED)
def create_import_batch(payload: ImportBatchCreate, db: DbSession, _: ImportRunner = None):
    batch = ImportBatch(**payload.model_dump())
    db.add(batch)
    db.flush()
    record_audit(
        db,
        action="import.batch.created",
        entity_type="import_batch",
        entity_id=batch.id,
        after_json=payload.model_dump(),
    )
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/batches/{batch_id}", response_model=ImportBatchRead)
def get_import_batch(batch_id: int, db: DbSession):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found.")
    return batch


@router.patch("/batches/{batch_id}", response_model=ImportBatchRead)
def update_import_batch(
    batch_id: int,
    payload: ImportBatchUpdate,
    db: DbSession,
    _: ImportApprover = None,
):
    batch = db.get(ImportBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found.")

    changes = payload.model_dump(exclude_unset=True)
    before = {
        "status": batch.status,
        "total_rows": batch.total_rows,
        "error_rows": batch.error_rows,
    }
    for field, value in changes.items():
        setattr(batch, field, value)
    if changes.get("status") in {"completed", "failed", "cancelled"} and batch.finished_at is None:
        batch.finished_at = datetime.utcnow()
    record_audit(
        db,
        action="import.batch.updated",
        entity_type="import_batch",
        entity_id=batch.id,
        before_json=before,
        after_json=changes,
    )
    db.commit()
    db.refresh(batch)
    return batch


@router.get("/batches/{batch_id}/raw-rows", response_model=list[ImportRawRowRead])
def list_import_raw_rows(batch_id: int, db: DbSession):
    if not db.get(ImportBatch, batch_id):
        raise HTTPException(status_code=404, detail="Import batch not found.")
    return db.scalars(
        select(ImportRawRow)
        .where(ImportRawRow.batch_id == batch_id)
        .order_by(ImportRawRow.row_number)
    ).all()


@router.post(
    "/batches/{batch_id}/raw-rows",
    response_model=ImportRawRowRead,
    status_code=status.HTTP_201_CREATED,
)
def create_import_raw_row(
    batch_id: int,
    payload: ImportRawRowCreate,
    db: DbSession,
    _: ImportRunner = None,
):
    if not db.get(ImportBatch, batch_id):
        raise HTTPException(status_code=404, detail="Import batch not found.")

    row = ImportRawRow(batch_id=batch_id, **payload.model_dump())
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Raw row already exists for this batch.") from exc
    db.refresh(row)
    return row


@router.get("/batches/{batch_id}/errors", response_model=list[ImportErrorRead])
def list_import_errors(batch_id: int, db: DbSession):
    if not db.get(ImportBatch, batch_id):
        raise HTTPException(status_code=404, detail="Import batch not found.")
    return db.scalars(
        select(ImportError)
        .where(ImportError.batch_id == batch_id)
        .order_by(ImportError.row_number, ImportError.id)
    ).all()


@router.post(
    "/batches/{batch_id}/errors",
    response_model=ImportErrorRead,
    status_code=status.HTTP_201_CREATED,
)
def create_import_error(
    batch_id: int,
    payload: ImportErrorCreate,
    db: DbSession,
    _: ImportRunner = None,
):
    if not db.get(ImportBatch, batch_id):
        raise HTTPException(status_code=404, detail="Import batch not found.")

    error = ImportError(batch_id=batch_id, **payload.model_dump())
    db.add(error)
    db.commit()
    db.refresh(error)
    return error
