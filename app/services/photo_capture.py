from __future__ import annotations

import hashlib
import io
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.admin import User
from app.models.documents import Document, DocumentEvent, DocumentLink
from app.models.photo_capture import (
    PhotoActionDefinition,
    PhotoCaptureItem,
    PhotoCaptureSession,
    PhotoMedia,
)
from app.models.tasks import Task, TaskDocument, TaskGuidedFlowStepRun
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.models.workshop_phased import WorkshopPhasedProcess, WorkshopPhasedProcessPhase
from app.schemas.photo_capture import PhotoActionConfigInput, PhotoSessionCreate
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.services.storage import persistent_storage_root

PHOTO_CATEGORIES = {
    "front",
    "rear",
    "side",
    "damage",
    "document",
    "part",
    "odometer",
    "other",
}
PHOTO_CATEGORY_LABELS = {
    "front": "Frente",
    "rear": "Traseira",
    "side": "Lateral",
    "damage": "Dano",
    "document": "Documento",
    "part": "Peça",
    "odometer": "Quilometragem",
    "other": "Outro",
}
PHOTO_STATUS_VALUES = {"pending", "captured", "submitted", "approved", "rejected"}
PHOTO_CONTENT_TYPES = {
    "image/jpeg": (".jpg", {".jpg", ".jpeg"}),
    "image/png": (".png", {".png"}),
    "image/webp": (".webp", {".webp"}),
}
DEFAULT_ACTION_CODE = "take_photo.default"
MAX_PIXELS = 60_000_000
MAX_LONG_EDGE = 6000
THUMBNAIL_EDGE = 720


class PhotoCaptureError(ValueError):
    pass


def normalize_photo_config(config: PhotoActionConfigInput | dict[str, Any]) -> dict[str, Any]:
    raw = config.model_dump() if isinstance(config, PhotoActionConfigInput) else dict(config or {})
    if raw.get("schema_version", 1) != 1 or raw.get("action_type", "take_photo") != "take_photo":
        raise PhotoCaptureError("A configuração da ação Tirar fotografia não é suportada.")
    minimum = int(raw.get("min_photos", 1))
    maximum = int(raw.get("max_photos", 1))
    if minimum < 0 or maximum < 1 or minimum > maximum or maximum > 50:
        raise PhotoCaptureError("A quantidade mínima deve ser menor ou igual à máxima.")
    categories = []
    for value in raw.get("categories") or ["other"]:
        clean = str(value).strip().lower()
        if clean not in PHOTO_CATEGORIES:
            raise PhotoCaptureError(f"Categoria de fotografia inválida: {clean or value}.")
        if clean not in categories:
            categories.append(clean)
    observation = str(raw.get("observation") or "optional").lower()
    if observation not in {"disabled", "optional", "required"}:
        raise PhotoCaptureError("A regra de observação é inválida.")
    allow_camera = bool(raw.get("allow_camera", True))
    allow_gallery = bool(raw.get("allow_gallery", True))
    if not allow_camera and not allow_gallery:
        raise PhotoCaptureError("É necessário permitir câmara ou galeria/ficheiro.")
    return {
        "schema_version": 1,
        "action_type": "take_photo",
        "title": str(raw.get("title") or "Tirar fotografia").strip()[:200],
        "instructions": (str(raw.get("instructions") or "").strip() or None),
        "min_photos": minimum,
        "max_photos": maximum,
        "required": bool(raw.get("required", False)),
        "capture": {
            "allow_camera": allow_camera,
            "allow_gallery": allow_gallery,
            "require_new": bool(raw.get("require_new_capture", False)),
        },
        "categories": categories,
        "observation": observation,
        "location": {"enabled": bool(raw.get("location_enabled", False)), "consent_required": True},
        "review": {"required": bool(raw.get("review_required", False))},
        "retention_policy": str(raw.get("retention_policy") or "operational_evidence")[:80],
        "metadata_policy": "strip_exif",
        "max_file_bytes": min(max(int(raw.get("max_file_bytes", 15_000_000)), 100_000), 50_000_000),
    }


def ensure_photo_action_defaults(db: Session) -> PhotoActionDefinition:
    existing = db.scalar(
        select(PhotoActionDefinition).where(
            PhotoActionDefinition.code == DEFAULT_ACTION_CODE,
            PhotoActionDefinition.version_number == 1,
        )
    )
    if existing:
        return existing
    config = normalize_photo_config(PhotoActionConfigInput())
    definition = PhotoActionDefinition(
        code=DEFAULT_ACTION_CODE,
        version_number=1,
        schema_version=1,
        name="Tirar fotografia",
        status="published",
        config_json=config,
        change_note="Primitivo base reutilizável",
        published_at=datetime.now(UTC),
    )
    db.add(definition)
    db.flush()
    return definition


def publish_photo_definition(
    db: Session,
    *,
    code: str,
    name: str,
    config: PhotoActionConfigInput | dict[str, Any],
    user_id: int,
    change_note: str | None,
) -> PhotoActionDefinition:
    version = (
        db.scalar(
            select(func.max(PhotoActionDefinition.version_number)).where(
                PhotoActionDefinition.code == code
            )
        )
        or 0
    ) + 1
    normalized = normalize_photo_config(config)
    definition = PhotoActionDefinition(
        code=code,
        version_number=version,
        schema_version=1,
        name=name.strip(),
        status="published",
        config_json=normalized,
        change_note=(change_note or "").strip() or None,
        published_at=datetime.now(UTC),
        published_by_id=user_id,
    )
    db.add(definition)
    db.flush()
    record_audit(
        db,
        action="photo.definition.published",
        entity_type="photo_action_definition",
        entity_id=definition.id,
        user_id=user_id,
        after_json={"code": code, "version": version, "config": normalized},
    )
    return definition


def _task_permission_codes(task: Task, *, write: bool) -> set[str]:
    suffix = "write" if write else "read"
    task_type = (task.task_type or "").lower()
    if "workshop" in task_type or "technical" in task_type:
        return {f"tasks.workshop.{suffix}", f"tasks.{suffix}"}
    if "audit" in task_type:
        return {f"tasks.audit.{suffix}", f"tasks.{suffix}"}
    if "administration" in task_type or "management" in task_type:
        return {f"tasks.administration.{suffix}", f"tasks.management.{suffix}", f"tasks.{suffix}"}
    return {f"tasks.operational.{suffix}", f"tasks.{suffix}"}


def user_can_access_photo_session(
    db: Session, user: User, session: PhotoCaptureSession, *, action: str
) -> bool:
    permissions = get_user_permission_codes(db, user)
    if "admin.manage" in permissions:
        return True
    required_photo_permission = {
        "read": "photos.read",
        "capture": "photos.capture",
        "review": "photos.review",
        "remove": "photos.remove",
    }.get(action, "photos.read")
    if required_photo_permission not in permissions:
        return False
    write = action in {"capture", "remove"}
    if session.task_id:
        task = db.get(Task, session.task_id)
        if not task or not permissions.intersection(_task_permission_codes(task, write=write)):
            return False
    if session.workshop_process_id or session.phased_process_id or session.phase_id:
        required = "workshop.write" if write else "workshop.read"
        if required not in permissions:
            return False
    if session.vehicle_id:
        required = "vehicles.write" if write else "vehicles.read"
        if required not in permissions:
            return False
    if session.entity_type and session.entity_type not in {
        "task",
        "vehicle",
        "workshop_process",
        "workshop_phase",
    }:
        return False
    return True


def _resolve_definition(
    db: Session, code: str | None, version: int | None
) -> PhotoActionDefinition | None:
    clean_code = code or DEFAULT_ACTION_CODE
    stmt = select(PhotoActionDefinition).where(
        PhotoActionDefinition.code == clean_code,
        PhotoActionDefinition.status == "published",
    )
    if version:
        stmt = stmt.where(PhotoActionDefinition.version_number == version)
    else:
        stmt = stmt.order_by(PhotoActionDefinition.version_number.desc())
    return db.scalar(stmt)


def create_photo_session(
    db: Session,
    payload: PhotoSessionCreate,
    *,
    user: User,
    allow_inline_config: bool,
) -> PhotoCaptureSession:
    definition = _resolve_definition(db, payload.definition_code, payload.definition_version)
    if payload.config:
        if not allow_inline_config:
            raise PhotoCaptureError("Não tem permissão para gerir a configuração da ação.")
        config = normalize_photo_config(payload.config)
        definition = None
    elif definition:
        config = normalize_photo_config(definition.config_json)
    else:
        raise PhotoCaptureError("A definição publicada da ação não foi encontrada.")

    task = db.get(Task, payload.task_id) if payload.task_id else None
    flow_step = db.get(TaskGuidedFlowStepRun, payload.task_flow_step_id) if payload.task_flow_step_id else None
    legacy_process = db.get(WorkshopProcess, payload.workshop_process_id) if payload.workshop_process_id else None
    phased_process = db.get(WorkshopPhasedProcess, payload.phased_process_id) if payload.phased_process_id else None
    phase = db.get(WorkshopPhasedProcessPhase, payload.phase_id) if payload.phase_id else None
    vehicle = db.get(Vehicle, payload.vehicle_id) if payload.vehicle_id else None
    requested = [
        (payload.task_id, task, "tarefa"),
        (payload.task_flow_step_id, flow_step, "passo"),
        (payload.workshop_process_id, legacy_process, "processo Oficina"),
        (payload.phased_process_id, phased_process, "processo faseado"),
        (payload.phase_id, phase, "fase"),
        (payload.vehicle_id, vehicle, "viatura"),
    ]
    for requested_id, resolved, label in requested:
        if requested_id and not resolved:
            raise PhotoCaptureError(f"A associação à {label} não existe.")
    if flow_step and (not task or flow_step.task_id != task.id):
        raise PhotoCaptureError("O passo guiado não pertence à tarefa indicada.")
    if phase:
        if phased_process and phase.process_id != phased_process.id:
            raise PhotoCaptureError("A fase não pertence ao processo indicado.")
        phased_process = phased_process or db.get(WorkshopPhasedProcess, phase.process_id)
    inherited_vehicle_id = payload.vehicle_id
    context_vehicle_ids = {
        value
        for value in [
            legacy_process.vehicle_id if legacy_process else None,
            phased_process.vehicle_id if phased_process else None,
        ]
        if value
    }
    if inherited_vehicle_id and context_vehicle_ids and inherited_vehicle_id not in context_vehicle_ids:
        raise PhotoCaptureError("A viatura não corresponde ao processo indicado.")
    if not inherited_vehicle_id and context_vehicle_ids:
        inherited_vehicle_id = next(iter(context_vehicle_ids))
    if not any(
        [payload.task_id, payload.workshop_process_id, phased_process, inherited_vehicle_id, payload.entity_type]
    ):
        raise PhotoCaptureError("Associe a captura a uma tarefa, processo, fase, viatura ou entidade.")

    session = PhotoCaptureSession(
        definition_id=definition.id if definition else None,
        definition_code=definition.code if definition else None,
        definition_version=definition.version_number if definition else None,
        schema_version=1,
        title=config["title"],
        instructions=config.get("instructions"),
        config_snapshot_json=deepcopy(config),
        status="pending",
        required=bool(config["required"]),
        task_id=payload.task_id,
        task_flow_step_id=payload.task_flow_step_id,
        workshop_process_id=payload.workshop_process_id,
        phased_process_id=phased_process.id if phased_process else None,
        phase_id=payload.phase_id,
        vehicle_id=inherited_vehicle_id,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        created_by_id=user.id,
    )
    db.add(session)
    db.flush()
    if not user_can_access_photo_session(db, user, session, action="capture"):
        raise PhotoCaptureError("Não tem acesso operacional ao contexto da captura.")
    record_audit(
        db,
        action="photo.session.created",
        entity_type="photo_capture_session",
        entity_id=session.id,
        user_id=user.id,
        after_json=photo_session_context(session),
    )
    return session


def photo_session_context(session: PhotoCaptureSession) -> dict[str, Any]:
    return {
        "task_id": session.task_id,
        "task_flow_step_id": session.task_flow_step_id,
        "workshop_process_id": session.workshop_process_id,
        "phased_process_id": session.phased_process_id,
        "phase_id": session.phase_id,
        "vehicle_id": session.vehicle_id,
        "entity_type": session.entity_type,
        "entity_id": session.entity_id,
    }


def _detect_content_type(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _safe_original_name(name: str | None) -> str:
    clean = Path(name or "photo").name[:255]
    return re.sub(r"[^A-Za-z0-9._ -]", "_", clean) or "photo"


def _normalize_image(content: bytes, original_name: str) -> tuple[bytes, str, str, int, int, bytes]:
    detected = _detect_content_type(content)
    if not detected:
        raise PhotoCaptureError("Formato inválido. Use JPEG, PNG ou WebP; SVG e HTML não são aceites.")
    suffix = Path(original_name).suffix.lower()
    canonical_suffix, compatible_suffixes = PHOTO_CONTENT_TYPES[detected]
    if suffix not in compatible_suffixes:
        raise PhotoCaptureError("A extensão do ficheiro não corresponde ao conteúdo da fotografia.")
    try:
        with Image.open(io.BytesIO(content)) as source:
            source.verify()
        with Image.open(io.BytesIO(content)) as source:
            image = ImageOps.exif_transpose(source)
            image.load()
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_PIXELS:
                raise PhotoCaptureError("A resolução da fotografia é inválida ou demasiado elevada.")
            if max(width, height) > MAX_LONG_EDGE:
                image.thumbnail((MAX_LONG_EDGE, MAX_LONG_EDGE), Image.Resampling.LANCZOS)
            width, height = image.size
            normalized = io.BytesIO()
            if detected == "image/png":
                image.save(normalized, format="PNG", optimize=True)
            elif detected == "image/webp":
                image.convert("RGB").save(normalized, format="WEBP", quality=90, method=6)
            else:
                image.convert("RGB").save(
                    normalized,
                    format="JPEG",
                    quality=92,
                    optimize=True,
                    progressive=True,
                )
            thumb = image.copy()
            thumb.thumbnail((THUMBNAIL_EDGE, THUMBNAIL_EDGE), Image.Resampling.LANCZOS)
            thumbnail = io.BytesIO()
            thumb.convert("RGB").save(thumbnail, format="JPEG", quality=82, optimize=True)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise PhotoCaptureError("O conteúdo da fotografia está corrompido ou não é seguro.") from exc
    return normalized.getvalue(), detected, canonical_suffix, width, height, thumbnail.getvalue()


def _resolve_private_file(path_value: str) -> Path:
    root = persistent_storage_root().resolve()
    candidate = Path(path_value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if candidate != root and root not in candidate.parents:
        raise PhotoCaptureError("Caminho de armazenamento inválido.")
    return candidate


def private_photo_path(media: PhotoMedia, document: Document, *, thumbnail: bool) -> Path:
    return _resolve_private_file(media.thumbnail_storage_path if thumbnail else document.storage_path)


def _ensure_document_link(
    db: Session, document_id: int, entity_type: str, entity_id: int | str, category: str
) -> None:
    exists = db.scalar(
        select(DocumentLink).where(
            DocumentLink.document_id == document_id,
            DocumentLink.entity_type == entity_type,
            DocumentLink.entity_id == str(entity_id),
            DocumentLink.category == category,
        )
    )
    if not exists:
        db.add(
            DocumentLink(
                document_id=document_id,
                entity_type=entity_type,
                entity_id=str(entity_id),
                category=category,
            )
        )


def store_photo(
    db: Session,
    *,
    session: PhotoCaptureSession,
    user: User,
    content: bytes,
    original_name: str,
    category: str,
    observation: str | None,
    capture_source: str,
    is_new_capture: bool,
    client_captured_at: datetime | None,
    location_latitude: float | None,
    location_longitude: float | None,
    location_accuracy_m: float | None,
    location_consent: bool,
    replaces_item_id: int | None = None,
) -> PhotoCaptureItem:
    config = session.config_snapshot_json or {}
    if session.status not in {"pending", "captured", "rejected"}:
        raise PhotoCaptureError("A captura já foi submetida e não pode ser alterada.")
    active_items = db.scalars(
        select(PhotoCaptureItem).where(
            PhotoCaptureItem.session_id == session.id,
            PhotoCaptureItem.removed_at.is_(None),
        )
    ).all()
    if len(active_items) >= int(config.get("max_photos", 1)):
        raise PhotoCaptureError("Foi atingida a quantidade máxima de fotografias.")
    clean_category = category.strip().lower()
    if clean_category not in set(config.get("categories") or ["other"]):
        raise PhotoCaptureError("A categoria não está permitida nesta ação.")
    observation_rule = config.get("observation", "optional")
    clean_observation = (observation or "").strip() or None
    if observation_rule == "required" and not clean_observation:
        raise PhotoCaptureError("A observação é obrigatória.")
    if observation_rule == "disabled":
        clean_observation = None
    capture_config = config.get("capture") or {}
    clean_source = capture_source.strip().lower()
    if clean_source not in {"camera", "gallery", "file"}:
        raise PhotoCaptureError("A origem da fotografia é inválida.")
    if clean_source == "camera" and not capture_config.get("allow_camera", True):
        raise PhotoCaptureError("A câmara não é permitida nesta ação.")
    if clean_source in {"gallery", "file"} and not capture_config.get("allow_gallery", True):
        raise PhotoCaptureError("O carregamento da galeria/ficheiro não é permitido.")
    if capture_config.get("require_new") and (clean_source != "camera" or not is_new_capture):
        raise PhotoCaptureError("Esta ação exige uma captura nova feita diretamente pela câmara.")
    location_config = config.get("location") or {}
    has_location = location_latitude is not None or location_longitude is not None
    if has_location:
        if not location_config.get("enabled") or not location_consent:
            raise PhotoCaptureError("A localização só pode ser guardada com consentimento explícito.")
        if location_latitude is None or location_longitude is None:
            raise PhotoCaptureError("A localização está incompleta.")
        if not (-90 <= location_latitude <= 90 and -180 <= location_longitude <= 180):
            raise PhotoCaptureError("A localização é inválida.")
    if len(content) > int(config.get("max_file_bytes", 15_000_000)):
        raise PhotoCaptureError("A fotografia excede o tamanho máximo permitido.")
    safe_name = _safe_original_name(original_name)
    normalized, content_type, suffix, width, height, thumbnail = _normalize_image(content, safe_name)
    digest = hashlib.sha256(normalized).hexdigest()
    media = db.scalar(select(PhotoMedia).where(PhotoMedia.sha256 == digest))
    document = db.get(Document, media.document_id) if media else None
    if not media or not document or document.archived:
        root = persistent_storage_root() / "photos" / "sha256" / digest[:2]
        root.mkdir(parents=True, exist_ok=True)
        stored = root / f"{digest}{suffix}"
        thumbnail_path = root / f"{digest}.thumb.jpg"
        if not stored.exists():
            stored.write_bytes(normalized)
        if not thumbnail_path.exists():
            thumbnail_path.write_bytes(thumbnail)
        document = Document(
            title=safe_name,
            document_type="photo",
            classification="operational_photo",
            source="photo_capture",
            entry_channel=clean_source,
            original_name=safe_name,
            file_name=stored.name,
            file_type=content_type,
            file_size=len(normalized),
            storage_provider="local",
            storage_path=str(stored),
            storage_key=f"photos/sha256/{digest[:2]}/{stored.name}",
            status="received",
            confidentiality_level="internal",
            retention_policy=config.get("retention_policy"),
            file_hash=digest,
            task_id=session.task_id,
            vehicle_id=session.vehicle_id,
            workshop_process_id=session.workshop_process_id,
            uploaded_by_id=user.id,
        )
        db.add(document)
        db.flush()
        media = PhotoMedia(
            document_id=document.id,
            sha256=digest,
            width=width,
            height=height,
            thumbnail_storage_path=str(thumbnail_path),
            thumbnail_content_type="image/jpeg",
            thumbnail_size=len(thumbnail),
            metadata_policy="strip_exif",
        )
        db.add(media)
        db.flush()
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="photo.stored",
                new_value="Imagem validada pelo conteúdo; EXIF removido; SHA-256 calculado.",
                user_id=user.id,
            )
        )
    item = PhotoCaptureItem(
        session_id=session.id,
        photo_media_id=media.id,
        category=clean_category,
        observation=clean_observation,
        status="captured",
        capture_source=clean_source,
        is_new_capture=is_new_capture,
        captured_by_id=user.id,
        client_captured_at=client_captured_at,
        location_latitude=location_latitude if has_location else None,
        location_longitude=location_longitude if has_location else None,
        location_accuracy_m=location_accuracy_m if has_location else None,
        location_consented_at=datetime.now(UTC) if has_location else None,
        replaces_item_id=replaces_item_id,
    )
    db.add(item)
    db.flush()
    session.status = "captured"
    for entity_type, entity_id in [
        ("photo_capture_session", session.id),
        ("task", session.task_id),
        ("task_guided_flow_step", session.task_flow_step_id),
        ("workshop_process", session.workshop_process_id),
        ("workshop_phased_process", session.phased_process_id),
        ("workshop_phase", session.phase_id),
        ("vehicle", session.vehicle_id),
        (session.entity_type, session.entity_id),
    ]:
        if entity_type and entity_id is not None:
            _ensure_document_link(db, document.id, entity_type, entity_id, clean_category)
    if session.task_id:
        task_document = db.scalar(
            select(TaskDocument).where(
                TaskDocument.task_id == session.task_id,
                TaskDocument.document_id == document.id,
            )
        )
        if not task_document:
            db.add(
                TaskDocument(
                    task_id=session.task_id,
                    document_id=document.id,
                    category=f"Fotografia · {PHOTO_CATEGORY_LABELS[clean_category]}",
                )
            )
    record_audit(
        db,
        action="photo.captured",
        entity_type="photo_capture_item",
        entity_id=item.id,
        user_id=user.id,
        after_json={
            "session_id": session.id,
            "document_id": document.id,
            "sha256": digest,
            "category": clean_category,
            "source": clean_source,
            "deduplicated": document.created_at != document.updated_at if document.created_at else False,
            "location_recorded": has_location,
        },
    )
    return item


def active_session_items(db: Session, session_id: int) -> list[PhotoCaptureItem]:
    return list(
        db.scalars(
            select(PhotoCaptureItem)
            .where(
                PhotoCaptureItem.session_id == session_id,
                PhotoCaptureItem.removed_at.is_(None),
            )
            .order_by(PhotoCaptureItem.id)
        ).all()
    )


def photo_session_ready(db: Session, session: PhotoCaptureSession) -> tuple[bool, str | None]:
    config = session.config_snapshot_json or {}
    count = len(active_session_items(db, session.id))
    minimum = int(config.get("min_photos", 1))
    if count < minimum:
        return False, f"Faltam {minimum - count} fotografia(s)."
    if config.get("review", {}).get("required") and session.status != "approved":
        return False, "A captura aguarda aprovação."
    if session.status not in {"submitted", "approved"}:
        return False, "A captura ainda não foi submetida."
    return True, None


def required_photo_blockers(
    db: Session,
    *,
    task_id: int | None = None,
    task_flow_step_id: int | None = None,
    phased_process_id: int | None = None,
    phase_id: int | None = None,
) -> list[str]:
    stmt = select(PhotoCaptureSession).where(PhotoCaptureSession.required.is_(True))
    filters = []
    if task_id is not None:
        filters.append(PhotoCaptureSession.task_id == task_id)
    if task_flow_step_id is not None:
        filters.append(PhotoCaptureSession.task_flow_step_id == task_flow_step_id)
    if phased_process_id is not None:
        filters.append(PhotoCaptureSession.phased_process_id == phased_process_id)
    if phase_id is not None:
        filters.append(PhotoCaptureSession.phase_id == phase_id)
    if not filters:
        return []
    stmt = stmt.where(*filters)
    blockers = []
    for session in db.scalars(stmt).all():
        ready, reason = photo_session_ready(db, session)
        if not ready:
            blockers.append(f"{session.title}: {reason}")
    return blockers


def session_payload(db: Session, session: PhotoCaptureSession) -> dict[str, Any]:
    items = active_session_items(db, session.id)
    config = session.config_snapshot_json or {}
    ready, blocker = photo_session_ready(db, session)
    item_payloads = []
    for item in items:
        media = db.get(PhotoMedia, item.photo_media_id)
        document = db.get(Document, media.document_id) if media else None
        item_payloads.append(
            {
                "id": item.id,
                "document_id": document.id if document else None,
                "category": item.category,
                "category_label": PHOTO_CATEGORY_LABELS.get(item.category, item.category),
                "observation": item.observation,
                "status": item.status,
                "capture_source": item.capture_source,
                "captured_at": item.captured_at,
                "captured_by_id": item.captured_by_id,
                "width": media.width if media else None,
                "height": media.height if media else None,
                "file_size": document.file_size if document else None,
                "content_url": f"/api/photo-actions/photos/{item.id}/content",
                "thumbnail_url": f"/api/photo-actions/photos/{item.id}/thumbnail",
            }
        )
    return {
        "id": session.id,
        "title": session.title,
        "instructions": session.instructions,
        "status": session.status,
        "required": session.required,
        "attempt_number": session.attempt_number,
        "rejection_reason": session.rejection_reason,
        "config": config,
        "context": photo_session_context(session),
        "progress": {
            "count": len(items),
            "minimum": int(config.get("min_photos", 1)),
            "maximum": int(config.get("max_photos", 1)),
            "label": f"{len(items)} de {int(config.get('max_photos', 1))} fotografias",
        },
        "ready": ready,
        "blocker": blocker,
        "items": item_payloads,
    }
