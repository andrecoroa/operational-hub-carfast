from datetime import UTC, datetime

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.auth import CurrentUser
from app.api.deps import DbSession
from app.models.documents import Document
from app.models.photo_capture import PhotoCaptureItem, PhotoCaptureSession, PhotoMedia
from app.schemas.photo_capture import PhotoDefinitionCreate, PhotoReviewInput, PhotoSessionCreate
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.services.photo_capture import (
    PhotoCaptureError,
    active_session_items,
    create_photo_session,
    photo_session_ready,
    private_photo_path,
    publish_photo_definition,
    session_payload,
    store_photo,
    user_can_access_photo_session,
)

router = APIRouter(prefix="/api/photo-actions")


def _session_or_404(db: DbSession, session_id: int) -> PhotoCaptureSession:
    session = db.get(PhotoCaptureSession, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Captura não encontrada.")
    return session


def _require_session_access(
    db: DbSession, current_user: CurrentUser, session: PhotoCaptureSession, action: str
) -> None:
    if not user_can_access_photo_session(db, current_user, session, action=action):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado.")


def _bad_request(exc: PhotoCaptureError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.post("/definitions", status_code=status.HTTP_201_CREATED)
def create_definition(payload: PhotoDefinitionCreate, db: DbSession, current_user: CurrentUser):
    permissions = get_user_permission_codes(db, current_user)
    if not permissions.intersection({"photos.configure", "admin.manage"}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado.")
    try:
        definition = publish_photo_definition(
            db,
            code=payload.code,
            name=payload.name,
            config=payload.config,
            user_id=current_user.id,
            change_note=payload.change_note,
        )
    except PhotoCaptureError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    return {
        "id": definition.id,
        "code": definition.code,
        "version": definition.version_number,
        "schema_version": definition.schema_version,
        "config": definition.config_json,
    }


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(payload: PhotoSessionCreate, db: DbSession, current_user: CurrentUser):
    permissions = get_user_permission_codes(db, current_user)
    if not permissions.intersection({"photos.capture", "admin.manage"}):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Acesso negado.")
    try:
        session = create_photo_session(
            db,
            payload,
            user=current_user,
            allow_inline_config=bool(permissions.intersection({"photos.configure", "admin.manage"})),
        )
    except PhotoCaptureError as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    db.refresh(session)
    return session_payload(db, session)


@router.get("/sessions")
def list_sessions(
    db: DbSession,
    current_user: CurrentUser,
    task_id: int | None = Query(default=None),
    task_flow_step_id: int | None = Query(default=None),
    workshop_process_id: int | None = Query(default=None),
    phased_process_id: int | None = Query(default=None),
    phase_id: int | None = Query(default=None),
    vehicle_id: int | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    entity_id: str | None = Query(default=None),
):
    stmt = select(PhotoCaptureSession)
    supplied = False
    for column, value in [
        (PhotoCaptureSession.task_id, task_id),
        (PhotoCaptureSession.task_flow_step_id, task_flow_step_id),
        (PhotoCaptureSession.workshop_process_id, workshop_process_id),
        (PhotoCaptureSession.phased_process_id, phased_process_id),
        (PhotoCaptureSession.phase_id, phase_id),
        (PhotoCaptureSession.vehicle_id, vehicle_id),
        (PhotoCaptureSession.entity_type, entity_type),
        (PhotoCaptureSession.entity_id, entity_id),
    ]:
        if value is not None:
            stmt = stmt.where(column == value)
            supplied = True
    if not supplied:
        raise HTTPException(status_code=400, detail="Indique o contexto a consultar.")
    sessions = db.scalars(stmt.order_by(PhotoCaptureSession.created_at.desc())).all()
    return [
        session_payload(db, session)
        for session in sessions
        if user_can_access_photo_session(db, current_user, session, action="read")
    ]


@router.get("/sessions/{session_id}")
def get_session(session_id: int, db: DbSession, current_user: CurrentUser):
    session = _session_or_404(db, session_id)
    _require_session_access(db, current_user, session, "read")
    return session_payload(db, session)


@router.post("/sessions/{session_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(
    session_id: int,
    db: DbSession,
    current_user: CurrentUser,
    photo: UploadFile = File(...),
    category: str = Form("other"),
    observation: str = Form(""),
    capture_source: str = Form("camera"),
    is_new_capture: bool = Form(True),
    client_captured_at: str = Form(""),
    location_latitude: float | None = Form(None),
    location_longitude: float | None = Form(None),
    location_accuracy_m: float | None = Form(None),
    location_consent: bool = Form(False),
    replaces_item_id: int | None = Form(None),
):
    session = _session_or_404(db, session_id)
    _require_session_access(db, current_user, session, "capture")
    maximum = int((session.config_snapshot_json or {}).get("max_file_bytes", 15_000_000))
    content = await photo.read(maximum + 1)
    parsed_captured_at = None
    if client_captured_at.strip():
        try:
            parsed_captured_at = datetime.fromisoformat(client_captured_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Data de captura inválida.") from exc
    try:
        item = store_photo(
            db,
            session=session,
            user=current_user,
            content=content,
            original_name=photo.filename or "photo.jpg",
            category=category,
            observation=observation,
            capture_source=capture_source,
            is_new_capture=is_new_capture,
            client_captured_at=parsed_captured_at,
            location_latitude=location_latitude,
            location_longitude=location_longitude,
            location_accuracy_m=location_accuracy_m,
            location_consent=location_consent,
            replaces_item_id=replaces_item_id,
        )
    except PhotoCaptureError as exc:
        db.rollback()
        raise _bad_request(exc) from exc
    db.commit()
    return {"item_id": item.id, "session": session_payload(db, session)}


@router.delete("/sessions/{session_id}/photos/{item_id}")
def remove_photo(session_id: int, item_id: int, db: DbSession, current_user: CurrentUser):
    session = _session_or_404(db, session_id)
    item = db.get(PhotoCaptureItem, item_id)
    if not item or item.session_id != session.id or item.removed_at:
        raise HTTPException(status_code=404, detail="Fotografia não encontrada.")
    permissions = get_user_permission_codes(db, current_user)
    action = "capture" if session.status in {"pending", "captured", "rejected"} else "remove"
    _require_session_access(db, current_user, session, action)
    if session.status not in {"pending", "captured", "rejected"} and not permissions.intersection(
        {"photos.remove", "admin.manage"}
    ):
        raise HTTPException(status_code=403, detail="A fotografia já foi submetida.")
    item.removed_at = datetime.now(UTC)
    item.removed_by_id = current_user.id
    remaining = len(active_session_items(db, session.id)) - 1
    if remaining <= 0:
        session.status = "pending"
    record_audit(
        db,
        action="photo.removed",
        entity_type="photo_capture_item",
        entity_id=item.id,
        user_id=current_user.id,
        before_json={"status": item.status},
        after_json={"removed": True},
    )
    db.commit()
    return session_payload(db, session)


@router.post("/sessions/{session_id}/submit")
def submit_session(session_id: int, db: DbSession, current_user: CurrentUser):
    session = _session_or_404(db, session_id)
    _require_session_access(db, current_user, session, "capture")
    if session.status not in {"pending", "captured", "rejected"}:
        raise HTTPException(status_code=400, detail="A captura já foi submetida.")
    items = active_session_items(db, session.id)
    minimum = int((session.config_snapshot_json or {}).get("min_photos", 1))
    if len(items) < minimum:
        raise HTTPException(status_code=400, detail=f"São necessárias pelo menos {minimum} fotografias.")
    session.status = "submitted"
    session.submitted_by_id = current_user.id
    session.submitted_at = datetime.now(UTC)
    session.rejection_reason = None
    for item in items:
        item.status = "submitted"
        item.rejection_reason = None
    record_audit(
        db,
        action="photo.session.submitted",
        entity_type="photo_capture_session",
        entity_id=session.id,
        user_id=current_user.id,
        after_json={"photo_count": len(items)},
    )
    db.commit()
    return session_payload(db, session)


@router.post("/sessions/{session_id}/review")
def review_session(
    session_id: int, payload: PhotoReviewInput, db: DbSession, current_user: CurrentUser
):
    session = _session_or_404(db, session_id)
    _require_session_access(db, current_user, session, "review")
    if session.status != "submitted":
        raise HTTPException(status_code=400, detail="A captura não está submetida para validação.")
    decision = payload.decision.strip().lower()
    reason = (payload.reason or "").strip() or None
    if decision not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Decisão inválida.")
    if decision == "rejected" and not reason:
        raise HTTPException(status_code=400, detail="Indique o motivo da rejeição.")
    session.status = decision
    session.reviewed_by_id = current_user.id
    session.reviewed_at = datetime.now(UTC)
    session.rejection_reason = reason if decision == "rejected" else None
    for item in active_session_items(db, session.id):
        item.status = decision
        item.rejection_reason = reason if decision == "rejected" else None
    record_audit(
        db,
        action=f"photo.session.{decision}",
        entity_type="photo_capture_session",
        entity_id=session.id,
        user_id=current_user.id,
        after_json={"decision": decision, "reason": reason},
    )
    db.commit()
    return session_payload(db, session)


@router.post("/sessions/{session_id}/repeat", status_code=status.HTTP_201_CREATED)
def repeat_session(session_id: int, db: DbSession, current_user: CurrentUser):
    original = _session_or_404(db, session_id)
    _require_session_access(db, current_user, original, "capture")
    if original.status != "rejected":
        raise HTTPException(status_code=400, detail="Só é possível repetir uma captura rejeitada.")
    repeated = PhotoCaptureSession(
        definition_id=original.definition_id,
        definition_code=original.definition_code,
        definition_version=original.definition_version,
        schema_version=original.schema_version,
        title=original.title,
        instructions=original.instructions,
        config_snapshot_json=original.config_snapshot_json,
        status="pending",
        required=original.required,
        task_id=original.task_id,
        task_flow_step_id=original.task_flow_step_id,
        workshop_process_id=original.workshop_process_id,
        phased_process_id=original.phased_process_id,
        phase_id=original.phase_id,
        vehicle_id=original.vehicle_id,
        entity_type=original.entity_type,
        entity_id=original.entity_id,
        attempt_number=original.attempt_number + 1,
        repeats_session_id=original.id,
        created_by_id=current_user.id,
    )
    db.add(repeated)
    db.flush()
    record_audit(
        db,
        action="photo.session.repeated",
        entity_type="photo_capture_session",
        entity_id=repeated.id,
        user_id=current_user.id,
        before_json={"rejected_session_id": original.id},
        after_json={"attempt_number": repeated.attempt_number},
    )
    db.commit()
    return session_payload(db, repeated)


def _photo_file(
    item_id: int, *, thumbnail: bool, db: DbSession, current_user: CurrentUser
) -> FileResponse:
    item = db.get(PhotoCaptureItem, item_id)
    if not item or item.removed_at:
        raise HTTPException(status_code=404, detail="Fotografia não encontrada.")
    session = _session_or_404(db, item.session_id)
    _require_session_access(db, current_user, session, "read")
    media = db.get(PhotoMedia, item.photo_media_id)
    document = db.get(Document, media.document_id) if media else None
    if not media or not document or document.archived:
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado.")
    try:
        path = private_photo_path(media, document, thumbnail=thumbnail)
    except PhotoCaptureError as exc:
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado.") from exc
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Ficheiro não encontrado.")
    response = FileResponse(
        path,
        media_type=media.thumbnail_content_type if thumbnail else document.file_type,
        filename=None,
    )
    response.headers["Cache-Control"] = "private, max-age=300"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response


@router.get("/photos/{item_id}/content")
def photo_content(item_id: int, db: DbSession, current_user: CurrentUser):
    return _photo_file(item_id, thumbnail=False, db=db, current_user=current_user)


@router.get("/photos/{item_id}/thumbnail")
def photo_thumbnail(item_id: int, db: DbSession, current_user: CurrentUser):
    return _photo_file(item_id, thumbnail=True, db=db, current_user=current_user)
