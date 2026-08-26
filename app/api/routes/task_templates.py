from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import Field
from sqlalchemy import func, select

from app.api.auth import CurrentUser
from app.api.deps import DbSession
from app.models.task_templates import ProcessInstance, ProcessModel, ProcessModelVersion, TaskTemplate, TaskTemplateUsage, TaskTemplateVersion
from app.schemas.common import ApiModel
from app.services.audit import record_audit
from app.services.authorization import get_user_permission_codes
from app.services.task_templates import CreationDenied, TaskCreationCapabilityResolver, advance_process_phase, canonical_snapshot, complete_process_checkpoint, create_task_for_process, create_task_from_template, start_process, validate_process_model_definition, validate_task_template_definition


router = APIRouter(prefix="/task-design")


class TemplateTaskRequest(ApiModel):
    overrides: dict[str, Any] = Field(default_factory=dict)


class ProcessStartRequest(ApiModel):
    context: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"
    justification: str | None = None


class ProcessTaskRequest(TemplateTaskRequest):
    template_version_id: int
    process_step_code: str = Field(min_length=1, max_length=120)


class ModelDraftRequest(ApiModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,119}$")
    name: str = Field(min_length=2, max_length=200)
    definition: dict[str, Any]


class ProcessAdvanceRequest(ApiModel):
    justification: str | None = None


class ModelVersionRequest(ApiModel):
    definition: dict[str, Any]


def _require_any(user: CurrentUser, db: DbSession, *codes: str) -> None:
    if not set(codes).intersection(get_user_permission_codes(db, user)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permission denied.")


def _deny(db: DbSession, user: CurrentUser, action: str, target_id: int, exc: CreationDenied) -> None:
    # Persist only the denial code and target identifier; never persist submitted
    # content or secrets. The failed unit of work has not added an operational row.
    user_id = user.id
    db.rollback()
    record_audit(db, action, "creation_contract", target_id, detail=str(exc), user_id=user_id)
    db.commit()
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.get("/task-templates/options")
def task_template_options(db: DbSession, current_user: CurrentUser):
    allowed_ids = {item.template_version_id for item in TaskCreationCapabilityResolver(db).options(current_user) if item.allowed}
    if not allowed_ids:
        return []
    rows = db.execute(
        select(TaskTemplateVersion, TaskTemplate, TaskTemplateUsage)
        .join(TaskTemplate, TaskTemplate.id == TaskTemplateVersion.template_id)
        .outerjoin(TaskTemplateUsage, (TaskTemplateUsage.template_id == TaskTemplate.id) & (TaskTemplateUsage.user_id == current_user.id))
        .where(TaskTemplateVersion.id.in_(allowed_ids))
    ).all()
    return [
        {
            "template_id": template.id,
            "version_id": version.id,
            "version": version.version,
            "code": template.code,
            "name": template.name,
            "favorite": bool(usage and usage.favorite),
            "last_used_at": usage.last_used_at if usage else None,
            "preview": version.definition_json.get("preview") or {},
        }
        for version, template, usage in rows
    ]


@router.post("/task-templates/{version_id}/tasks", status_code=status.HTTP_201_CREATED)
def create_template_task(version_id: int, payload: TemplateTaskRequest, db: DbSession, current_user: CurrentUser):
    try:
        task = create_task_from_template(db, user=current_user, version_id=version_id, overrides=payload.overrides)
    except CreationDenied as exc:
        _deny(db, current_user, "task.template_create_denied", version_id, exc)
    db.commit()
    db.refresh(task)
    return {"id": task.id, "template_version_id": task.task_template_version_id, "snapshot_digest": task.task_template_snapshot_digest}


@router.post("/process-models/{version_id}/instances", status_code=status.HTTP_201_CREATED)
def create_process_instance(version_id: int, payload: ProcessStartRequest, db: DbSession, current_user: CurrentUser):
    try:
        instance = start_process(db, user=current_user, model_version_id=version_id, context=payload.context, source=payload.source, justification=payload.justification)
    except CreationDenied as exc:
        _deny(db, current_user, "process.start_denied", version_id, exc)
    db.commit()
    db.refresh(instance)
    return {"id": instance.id, "model_version_id": instance.model_version_id, "snapshot_digest": instance.model_snapshot_digest}


@router.post("/process-instances/{instance_id}/tasks", status_code=status.HTTP_201_CREATED)
def create_process_task(instance_id: int, payload: ProcessTaskRequest, db: DbSession, current_user: CurrentUser):
    instance = db.get(ProcessInstance, instance_id)
    if not instance or instance.status not in {"active", "blocked"}:
        _deny(db, current_user, "process.task_create_denied", instance_id, CreationDenied("process_instance_unavailable"))
    try:
        task = create_task_for_process(
            db, user=current_user, instance=instance, template_version_id=payload.template_version_id,
            overrides=payload.overrides, process_step_code=payload.process_step_code,
        )
    except CreationDenied as exc:
        _deny(db, current_user, "process.task_create_denied", instance_id, exc)
    db.commit()
    db.refresh(task)
    return {"id": task.id, "process_instance_id": instance.id, "process_step_code": task.process_step_code}


@router.post("/process-instances/{instance_id}/checkpoints/{checkpoint_code}")
def complete_checkpoint(instance_id: int, checkpoint_code: str, db: DbSession, current_user: CurrentUser):
    instance = db.get(ProcessInstance, instance_id)
    if not instance:
        _deny(db, current_user, "process.checkpoint_denied", instance_id, CreationDenied("process_instance_unavailable"))
    try:
        complete_process_checkpoint(db, user=current_user, instance=instance, checkpoint_code=checkpoint_code)
    except CreationDenied as exc:
        _deny(db, current_user, "process.checkpoint_denied", instance_id, exc)
    db.commit()
    return {"id": instance.id, "current_phase_code": instance.context_json.get("current_phase_code"), "completed_checkpoints": instance.context_json.get("completed_checkpoints", [])}


@router.post("/process-instances/{instance_id}/advance")
def advance_instance(instance_id: int, payload: ProcessAdvanceRequest, db: DbSession, current_user: CurrentUser):
    instance = db.get(ProcessInstance, instance_id)
    if not instance:
        _deny(db, current_user, "process.advance_denied", instance_id, CreationDenied("process_instance_unavailable"))
    try:
        advance_process_phase(db, user=current_user, instance=instance, justification=payload.justification)
    except CreationDenied as exc:
        _deny(db, current_user, "process.advance_denied", instance_id, exc)
    db.commit()
    return {"id": instance.id, "status": instance.status, "current_phase_code": instance.context_json.get("current_phase_code")}


@router.post("/admin/task-templates", status_code=status.HTTP_201_CREATED)
def create_task_template_draft(payload: ModelDraftRequest, db: DbSession, current_user: CurrentUser):
    _require_any(current_user, db, "tasks.templates.manage")
    try:
        validate_task_template_definition(payload.definition)
    except CreationDenied as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.scalar(select(TaskTemplate).where(TaskTemplate.code == payload.code)):
        raise HTTPException(status_code=409, detail="template_code_exists")
    snapshot, digest = canonical_snapshot(payload.definition)
    model = TaskTemplate(code=payload.code, name=payload.name, created_by_id=current_user.id)
    db.add(model); db.flush()
    version = TaskTemplateVersion(template_id=model.id, version=1, status="draft", definition_json=snapshot, definition_digest=digest, created_by_id=current_user.id)
    db.add(version); db.flush()
    record_audit(db, "task_template.draft_created", "task_template", model.id, user_id=current_user.id, after_json={"version_id": version.id, "digest": digest})
    db.commit()
    return {"id": model.id, "version_id": version.id, "status": "draft", "digest": digest}


@router.post("/admin/task-templates/{template_id}/versions", status_code=status.HTTP_201_CREATED)
def create_task_template_version(template_id: int, payload: ModelVersionRequest, db: DbSession, current_user: CurrentUser):
    _require_any(current_user, db, "tasks.templates.manage")
    model = db.get(TaskTemplate, template_id)
    if not model:
        raise HTTPException(status_code=404, detail="template_unavailable")
    try:
        validate_task_template_definition(payload.definition)
    except CreationDenied as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    number = (db.scalar(select(func.max(TaskTemplateVersion.version)).where(TaskTemplateVersion.template_id == model.id)) or 0) + 1
    snapshot, digest = canonical_snapshot(payload.definition)
    version = TaskTemplateVersion(template_id=model.id, version=number, status="draft", definition_json=snapshot, definition_digest=digest, created_by_id=current_user.id)
    db.add(version); db.flush(); record_audit(db, "task_template.version_created", "task_template_version", version.id, user_id=current_user.id, after_json={"version": number, "digest": digest}); db.commit()
    return {"version_id": version.id, "version": number, "status": "draft", "digest": digest}


@router.post("/admin/task-template-versions/{version_id}/publish")
def publish_task_template_version(version_id: int, db: DbSession, current_user: CurrentUser):
    _require_any(current_user, db, "tasks.templates.publish")
    version = db.get(TaskTemplateVersion, version_id)
    if not version or version.status != "draft":
        raise HTTPException(status_code=404, detail="draft_unavailable")
    try:
        validate_task_template_definition(version.definition_json)
    except CreationDenied as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _, digest = canonical_snapshot(version.definition_json)
    if digest != version.definition_digest:
        raise HTTPException(status_code=422, detail="template_digest_mismatch")
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    record_audit(db, "task_template.published", "task_template_version", version.id, user_id=current_user.id, after_json={"digest": version.definition_digest})
    db.commit()
    return {"version_id": version.id, "status": version.status}


@router.post("/admin/process-models", status_code=status.HTTP_201_CREATED)
def create_process_model_draft(payload: ModelDraftRequest, db: DbSession, current_user: CurrentUser):
    _require_any(current_user, db, "process.models.manage")
    try:
        validate_process_model_definition(payload.definition)
    except CreationDenied as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.scalar(select(ProcessModel).where(ProcessModel.code == payload.code)):
        raise HTTPException(status_code=409, detail="model_code_exists")
    snapshot, digest = canonical_snapshot(payload.definition)
    model = ProcessModel(code=payload.code, name=payload.name, created_by_id=current_user.id)
    db.add(model); db.flush()
    version = ProcessModelVersion(model_id=model.id, version=1, status="draft", definition_json=snapshot, definition_digest=digest, created_by_id=current_user.id)
    db.add(version); db.flush()
    record_audit(db, "process_model.draft_created", "process_model", model.id, user_id=current_user.id, after_json={"version_id": version.id, "digest": digest})
    db.commit()
    return {"id": model.id, "version_id": version.id, "status": "draft", "digest": digest}


@router.post("/admin/process-models/{model_id}/versions", status_code=status.HTTP_201_CREATED)
def create_process_model_version(model_id: int, payload: ModelVersionRequest, db: DbSession, current_user: CurrentUser):
    _require_any(current_user, db, "process.models.manage")
    model = db.get(ProcessModel, model_id)
    if not model:
        raise HTTPException(status_code=404, detail="model_unavailable")
    try:
        validate_process_model_definition(payload.definition)
    except CreationDenied as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    number = (db.scalar(select(func.max(ProcessModelVersion.version)).where(ProcessModelVersion.model_id == model.id)) or 0) + 1
    snapshot, digest = canonical_snapshot(payload.definition)
    version = ProcessModelVersion(model_id=model.id, version=number, status="draft", definition_json=snapshot, definition_digest=digest, created_by_id=current_user.id)
    db.add(version); db.flush(); record_audit(db, "process_model.version_created", "process_model_version", version.id, user_id=current_user.id, after_json={"version": number, "digest": digest}); db.commit()
    return {"version_id": version.id, "version": number, "status": "draft", "digest": digest}


@router.post("/admin/process-model-versions/{version_id}/publish")
def publish_process_model_version(version_id: int, db: DbSession, current_user: CurrentUser):
    _require_any(current_user, db, "process.models.publish")
    version = db.get(ProcessModelVersion, version_id)
    if not version or version.status != "draft":
        raise HTTPException(status_code=404, detail="draft_unavailable")
    try:
        validate_process_model_definition(version.definition_json)
    except CreationDenied as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _, digest = canonical_snapshot(version.definition_json)
    if digest != version.definition_digest:
        raise HTTPException(status_code=422, detail="process_model_digest_mismatch")
    version.status = "published"
    version.published_at = datetime.now(timezone.utc)
    record_audit(db, "process_model.published", "process_model_version", version.id, user_id=current_user.id, after_json={"digest": version.definition_digest})
    db.commit()
    return {"version_id": version.id, "status": version.status}
