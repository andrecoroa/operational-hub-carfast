import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.admin import Role, User, UserRole
from app.models.organization import OrganizationalUnit, Team, TeamMember
from app.models.documents import Document
from app.models.email import EmailThread
from app.models.stock import StockSupplier
from app.models.task_templates import (
    ProcessInstance,
    ProcessInstanceEvent,
    ProcessModel,
    ProcessModelVersion,
    TaskTemplate,
    TaskTemplateUsage,
    TaskTemplateVersion,
)
from app.models.tasks import Task
from app.models.vehicles import Vehicle
from app.models.work_hierarchy import RoleWorkScope, WorkCategory, WorkDepartment, WorkQueue, WorkSubcategory
from app.services.audit import record_audit
from app.services.authorization import get_user_authorized_unit_codes, get_user_permission_codes
from app.services.service_desk import assignment_target_user_allowed, category_team_is_eligible, category_user_is_eligible


class CreationDenied(ValueError):
    pass


def validate_task_template_definition(definition: dict) -> None:
    required = {"task_type", "classification", "required_create_permissions", "defaults"}
    missing = sorted(required - set(definition))
    if missing:
        raise CreationDenied(f"task_template_missing:{','.join(missing)}")
    if not definition.get("required_create_permissions"):
        raise CreationDenied("task_template_create_permission_required")
    if not (definition.get("defaults") or {}).get("title"):
        raise CreationDenied("task_template_title_required")


def validate_process_model_definition(definition: dict) -> None:
    required = {"phases", "tasks", "dependencies", "required_gates", "documents", "sla", "responsibility_rules", "required_start_permissions", "allowed_sources"}
    missing = sorted(required - set(definition))
    if missing:
        raise CreationDenied(f"process_model_missing:{','.join(missing)}")
    codes = [item.get("code") for item in definition.get("phases", [])]
    if not codes or None in codes or len(codes) != len(set(codes)):
        raise CreationDenied("process_phase_codes_invalid")
    if not definition.get("required_start_permissions") or not definition.get("allowed_sources"):
        raise CreationDenied("process_authority_required")
    for phase in definition["phases"]:
        unknown = set(phase.get("depends_on") or []) - set(codes)
        if unknown:
            raise CreationDenied("process_phase_dependency_invalid")
        if set(phase.get("tasks") or []) - set(definition.get("tasks") or {}):
            raise CreationDenied("process_phase_task_invalid")
    for dependency in definition.get("dependencies") or []:
        if dependency.get("before") not in codes or dependency.get("after") not in codes:
            raise CreationDenied("process_dependency_invalid")
    effects = definition.get("external_effects")
    if not isinstance(effects, dict) or effects.get("webhooks") is not False:
        raise CreationDenied("process_external_effects_not_closed")
    if any((effects.get(name) or {}).get("enabled") is not False for name in ("email", "portal")):
        raise CreationDenied("process_external_effects_not_closed")
    responsibilities = definition.get("responsibility_rules") or {}
    if responsibilities.get("administrator_operational_access") is not False:
        raise CreationDenied("process_admin_access_not_closed")


def canonical_snapshot(value: dict) -> tuple[dict, str]:
    snapshot = json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True))
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return snapshot, hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class CreationCapability:
    template_version_id: int
    allowed: bool
    reason: str | None = None


class TaskCreationCapabilityResolver:
    """Single authority for task-template options and POST revalidation."""

    def __init__(self, db: Session):
        self.db = db

    def _role_codes(self, user_id: int) -> set[str]:
        return set(self.db.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id, Role.active.is_(True))))

    def _active_hierarchy(self, definition: dict) -> tuple[WorkQueue | None, WorkDepartment | None, WorkCategory | None, WorkSubcategory | None]:
        ids = definition.get("classification", {})
        queue = self.db.get(WorkQueue, ids.get("queue_id")) if ids.get("queue_id") else None
        department = self.db.get(WorkDepartment, ids.get("department_id")) if ids.get("department_id") else None
        category = self.db.get(WorkCategory, ids.get("category_id")) if ids.get("category_id") else None
        subcategory = self.db.get(WorkSubcategory, ids.get("subcategory_id")) if ids.get("subcategory_id") else None
        for item in (queue, department, category, subcategory):
            if item is not None and not item.active:
                raise CreationDenied("inactive_classification")
        if department and (not queue or department.queue_id != queue.id):
            raise CreationDenied("classification_drift")
        if category and (not department or category.department_id != department.id):
            raise CreationDenied("classification_drift")
        if subcategory and (not category or subcategory.category_id != category.id):
            raise CreationDenied("classification_drift")
        return queue, department, category, subcategory

    def require(self, user: User, version: TaskTemplateVersion) -> dict:
        template = self.db.get(TaskTemplate, version.template_id)
        if not template or not template.active or version.status != "published":
            raise CreationDenied("template_unavailable")
        definition = deepcopy(version.definition_json)
        validate_task_template_definition(definition)
        snapshot, digest = canonical_snapshot(definition)
        if digest != version.definition_digest:
            raise CreationDenied("template_digest_mismatch")
        permissions = get_user_permission_codes(self.db, user)
        required = set(definition.get("required_create_permissions") or [])
        if not required or not required.issubset(permissions):
            raise CreationDenied("create_permission_required")
        allowed_roles = set(definition.get("allowed_role_codes") or [])
        if allowed_roles and not allowed_roles.intersection(self._role_codes(user.id)):
            raise CreationDenied("role_not_allowed")
        allowed_units = set(definition.get("allowed_unit_codes") or [])
        user_units = get_user_authorized_unit_codes(self.db, user)
        if allowed_units and not allowed_units.intersection(user_units):
            raise CreationDenied("unit_not_allowed")
        queue, department, category, subcategory = self._active_hierarchy(definition)
        if queue:
            role_ids = select(UserRole.role_id).where(UserRole.user_id == user.id)
            scopes = list(self.db.scalars(select(RoleWorkScope).where(RoleWorkScope.role_id.in_(role_ids), RoleWorkScope.queue_id == queue.id, RoleWorkScope.can_create.is_(True))))
            def matches(scope: RoleWorkScope) -> bool:
                return (scope.department_id in (None, department.id if department else None) and scope.category_id in (None, category.id if category else None) and scope.subcategory_id in (None, subcategory.id if subcategory else None))
            if not any(matches(scope) for scope in scopes):
                raise CreationDenied("scope_create_denied")
        return snapshot

    def options(self, user: User) -> list[CreationCapability]:
        versions = self.db.scalars(select(TaskTemplateVersion).join(TaskTemplate, TaskTemplate.id == TaskTemplateVersion.template_id).where(TaskTemplate.active.is_(True), TaskTemplateVersion.status == "published")).all()
        result = []
        for version in versions:
            if version.definition_json.get("process_only"):
                continue
            try:
                self.require(user, version)
                result.append(CreationCapability(version.id, True))
            except CreationDenied as exc:
                result.append(CreationCapability(version.id, False, str(exc)))
        return result


ALLOWED_OVERRIDES = {"title", "description", "priority", "due_on", "assigned_to_id", "team_id", "context"}


def create_task_from_template(db: Session, *, user: User, version_id: int, overrides: dict | None = None, process_instance_id: int | None = None, process_step_code: str | None = None) -> Task:
    version = db.get(TaskTemplateVersion, version_id)
    if not version:
        raise CreationDenied("template_unavailable")
    definition = TaskCreationCapabilityResolver(db).require(user, version)
    overrides = overrides or {}
    unknown = set(overrides) - ALLOWED_OVERRIDES
    if unknown:
        raise CreationDenied(f"override_not_allowed:{','.join(sorted(unknown))}")
    assigned_to_id = overrides.get("assigned_to_id")
    if assigned_to_id is not None:
        assignee = db.get(User, assigned_to_id)
        permissions = get_user_permission_codes(db, user)
        category_id = (definition.get("classification") or {}).get("category_id")
        shares_unit = bool(assignee) and (assigned_to_id == user.id or bool(get_user_authorized_unit_codes(db, assignee).intersection(get_user_authorized_unit_codes(db, user))))
        if not assignee or not assignee.active or not shares_unit or not assignment_target_user_allowed(db, actor_user_id=user.id, target_user_id=assigned_to_id) or (assigned_to_id != user.id and "tasks.assign.peer" not in permissions) or (category_id and not category_user_is_eligible(db, category_id, assigned_to_id)):
            raise CreationDenied("assignee_not_allowed")
    team_id = overrides.get("team_id")
    if team_id is not None:
        team = db.get(Team, team_id)
        is_member = db.scalar(select(TeamMember.id).where(TeamMember.team_id == team_id, TeamMember.user_id == user.id))
        category_id = (definition.get("classification") or {}).get("category_id")
        team_unit = db.get(OrganizationalUnit, team.organizational_unit_id) if team and team.organizational_unit_id else None
        if not team or not team.active or not is_member or (team_unit and team_unit.code not in get_user_authorized_unit_codes(db, user)) or (category_id and not category_team_is_eligible(db, category_id, team_id)):
            raise CreationDenied("team_not_allowed")
    context = overrides.get("context") or {}
    if context:
        entity_type, entity_id = context.get("entity_type"), context.get("entity_id")
        allowed_types = set(definition.get("allowed_context_types") or [])
        entity_models = {"vehicle": Vehicle, "document": Document, "process": ProcessInstance, "email": EmailThread, "supplier": StockSupplier}
        model = entity_models.get(entity_type)
        try:
            parsed_entity_id = int(entity_id)
        except (TypeError, ValueError):
            parsed_entity_id = None
        entity = db.get(model, parsed_entity_id) if model and parsed_entity_id is not None else None
        entity_permission = {"vehicle": "vehicles.read", "document": "documents.read", "process": "process.models.read", "email": "email.read", "supplier": "suppliers.read"}.get(entity_type)
        if not entity_type or parsed_entity_id is None or entity_type not in allowed_types or model is None or entity is None or entity_permission not in get_user_permission_codes(db, user):
            raise CreationDenied("context_not_allowed")
        user_units = get_user_authorized_unit_codes(db, user)
        if entity_type == "vehicle":
            unit = db.get(OrganizationalUnit, entity.current_location_id) if entity.current_location_id else None
            if not unit or unit.code not in user_units:
                raise CreationDenied("context_scope_denied")
        if entity_type == "document" and entity.vehicle_id:
            vehicle = db.get(Vehicle, entity.vehicle_id)
            unit = db.get(OrganizationalUnit, vehicle.current_location_id) if vehicle and vehicle.current_location_id else None
            if not unit or unit.code not in user_units:
                raise CreationDenied("context_scope_denied")
        if entity_type == "process" and entity.organizational_unit_code not in user_units:
            raise CreationDenied("context_scope_denied")
    classification = definition.get("classification", {})
    defaults = definition.get("defaults", {})
    due_on = overrides.get("due_on")
    if due_on is None and defaults.get("due_offset_days") is not None:
        due_on = date.today() + timedelta(days=int(defaults["due_offset_days"]))
    task = Task(
        title=overrides.get("title", defaults.get("title", "Tarefa")),
        description=overrides.get("description", defaults.get("description")),
        task_type=definition.get("task_type", "operational_task"),
        status="new",
        priority=overrides.get("priority", defaults.get("priority", "normal")),
        due_on=due_on,
        work_queue_id=classification.get("queue_id"), work_department_id=classification.get("department_id"), work_category_id=classification.get("category_id"), work_subcategory_id=classification.get("subcategory_id"),
        assigned_to_id=assigned_to_id, team_id=team_id,
        entity_type=context.get("entity_type"), entity_id=context.get("entity_id"),
        created_by_id=user.id, task_template_version_id=version.id,
        task_template_snapshot_json=deepcopy(definition), task_template_snapshot_digest=version.definition_digest,
        process_instance_id=process_instance_id, process_step_code=process_step_code,
    )
    db.add(task)
    db.flush()
    usage = db.scalar(select(TaskTemplateUsage).where(TaskTemplateUsage.template_id == version.template_id, TaskTemplateUsage.user_id == user.id))
    if usage is None:
        usage = TaskTemplateUsage(template_id=version.template_id, user_id=user.id)
        db.add(usage)
    usage.last_used_at = datetime.now(timezone.utc)
    record_audit(db, "task.created_from_template", "task", task.id, user_id=user.id, after_json={"template_version_id": version.id, "process_instance_id": process_instance_id})
    return task


def start_process(db: Session, *, user: User, model_version_id: int, context: dict, source: str = "manual", justification: str | None = None, trusted_source: bool = False) -> ProcessInstance:
    version = db.get(ProcessModelVersion, model_version_id)
    model = db.get(ProcessModel, version.model_id) if version else None
    if not version or not model or not model.active or version.status != "published":
        raise CreationDenied("process_model_unavailable")
    snapshot, digest = canonical_snapshot(version.definition_json)
    validate_process_model_definition(snapshot)
    if digest != version.definition_digest:
        raise CreationDenied("process_model_digest_mismatch")
    if source not in set(snapshot.get("allowed_sources") or []):
        raise CreationDenied("process_source_not_allowed")
    if source != "manual" and not trusted_source:
        raise CreationDenied("process_source_requires_trusted_event")
    permissions = get_user_permission_codes(db, user)
    required = set(snapshot.get("required_start_permissions") or [])
    if not required or not required.issubset(permissions):
        raise CreationDenied("process_start_permission_required")
    role_codes = set(db.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id, Role.active.is_(True))))
    if "manager" in role_codes and snapshot.get("manager_execution_requires_justification", True) and not (justification or "").strip():
        raise CreationDenied("manager_justification_required")
    units = get_user_authorized_unit_codes(db, user)
    unit_code = context.get("organizational_unit_code")
    if not unit_code or unit_code not in units:
        raise CreationDenied("unit_not_allowed")
    selection_mode = context.get("selection_mode")
    vehicle_ids = context.get("vehicle_ids")
    document_ids = context.get("document_ids")
    if selection_mode not in set(snapshot.get("selection", {}).get("vehicles") or []) or not isinstance(vehicle_ids, list) or not vehicle_ids or not all(isinstance(item, int) and item > 0 for item in vehicle_ids):
        raise CreationDenied("vehicle_selection_invalid")
    if not isinstance(document_ids, list) or not all(isinstance(item, int) and item > 0 for item in document_ids):
        raise CreationDenied("document_selection_invalid")
    if not {"vehicles.read", "documents.read"}.issubset(permissions):
        raise CreationDenied("source_data_permission_required")
    selected_unit = db.scalar(select(OrganizationalUnit).where(OrganizationalUnit.code == unit_code, OrganizationalUnit.active.is_(True)))
    if not selected_unit:
        raise CreationDenied("vehicle_scope_denied")
    if selection_mode == "all_authorized":
        selected_vehicles = list(db.scalars(select(Vehicle).where(Vehicle.current_location_id == selected_unit.id, Vehicle.active.is_(True))).all())
        if not selected_vehicles:
            raise CreationDenied("vehicle_selection_invalid")
        vehicle_ids = [item.id for item in selected_vehicles]
        context = deepcopy(context)
        context["vehicle_ids"] = vehicle_ids
    else:
        selected_vehicles = list(db.scalars(select(Vehicle).where(Vehicle.id.in_(vehicle_ids), Vehicle.active.is_(True))).all())
    if {item.id for item in selected_vehicles} != set(vehicle_ids):
        raise CreationDenied("vehicle_selection_invalid")
    if not selected_unit or any(vehicle.current_location_id != selected_unit.id for vehicle in selected_vehicles):
        raise CreationDenied("vehicle_scope_denied")
    selected_documents = list(db.scalars(select(Document).where(Document.id.in_(document_ids), Document.archived.is_(False))).all()) if document_ids else []
    if {item.id for item in selected_documents} != set(document_ids):
        raise CreationDenied("document_selection_invalid")
    if any(item.vehicle_id not in set(vehicle_ids) or item.confidentiality_level in {"confidential", "restricted"} for item in selected_documents):
        raise CreationDenied("document_scope_denied")
    if source != "manual" and not context.get("source_entity_id"):
        raise CreationDenied("source_entity_required")
    context = deepcopy(context)
    context["current_phase_code"] = snapshot["phases"][0]["code"]
    instance = ProcessInstance(model_version_id=version.id, model_snapshot_json=snapshot, model_snapshot_digest=digest, title=context.get("title") or model.name, source=source, context_json=deepcopy(context), organizational_unit_code=unit_code, manager_exception_justification=justification, created_by_id=user.id)
    db.add(instance); db.flush()
    db.add(ProcessInstanceEvent(process_instance_id=instance.id, actor_user_id=user.id, action="process.started", details_json={"model_version_id": version.id, "source": source, "manager_exception": bool(justification)}))
    record_audit(db, "process.started", "process_instance", instance.id, user_id=user.id, after_json={"model_version_id": version.id, "source": source})
    return instance


def create_task_for_process(db: Session, *, user: User, instance: ProcessInstance, template_version_id: int, process_step_code: str, overrides: dict | None = None) -> Task:
    if instance.status not in {"active", "blocked"}:
        raise CreationDenied("process_instance_unavailable")
    if instance.organizational_unit_code not in get_user_authorized_unit_codes(db, user):
        raise CreationDenied("process_instance_scope_denied")
    current_phase = instance.context_json.get("current_phase_code")
    if process_step_code != current_phase:
        raise CreationDenied("process_phase_not_actionable")
    phase = next((item for item in instance.model_snapshot_json.get("phases", []) if item.get("code") == process_step_code), None)
    version = db.get(TaskTemplateVersion, template_version_id)
    template = db.get(TaskTemplate, version.template_id) if version else None
    if not phase or not template or template.code not in set(phase.get("tasks") or []):
        raise CreationDenied("task_template_not_allowed_for_phase")
    return create_task_from_template(
        db,
        user=user,
        version_id=template_version_id,
        overrides=overrides,
        process_instance_id=instance.id,
        process_step_code=process_step_code,
    )


class ProcessExecutionCapabilityResolver:
    def __init__(self, db: Session):
        self.db = db

    def require(self, user: User, instance: ProcessInstance) -> None:
        if instance.status != "active":
            raise CreationDenied("process_instance_not_actionable")
        permissions = get_user_permission_codes(self.db, user)
        if "process.instances.execute" not in permissions:
            raise CreationDenied("process_execute_permission_required")
        if instance.organizational_unit_code not in get_user_authorized_unit_codes(self.db, user):
            raise CreationDenied("process_instance_scope_denied")
        roles = set(self.db.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id, Role.active.is_(True))))
        if not roles.intersection({"operator", "manager"}):
            raise CreationDenied("process_execute_role_denied")


def _phase_tasks_complete(db: Session, instance: ProcessInstance, phase: dict) -> bool:
    required_codes = set(phase.get("tasks") or [])
    if not required_codes:
        return True
    rows = db.execute(
        select(Task, TaskTemplate)
        .join(TaskTemplateVersion, TaskTemplateVersion.id == Task.task_template_version_id)
        .join(TaskTemplate, TaskTemplate.id == TaskTemplateVersion.template_id)
        .where(Task.process_instance_id == instance.id, Task.process_step_code == phase.get("code"))
    ).all()
    completed_codes = {template.code for task, template in rows if task.status in {"resolved", "closed", "execution_done", "ready_validation"}}
    return required_codes.issubset(completed_codes)


def complete_process_checkpoint(db: Session, *, user: User, instance: ProcessInstance, checkpoint_code: str) -> ProcessInstance:
    ProcessExecutionCapabilityResolver(db).require(user, instance)
    current = instance.context_json.get("current_phase_code")
    phase = next((item for item in instance.model_snapshot_json.get("phases", []) if item.get("code") == current), None)
    allowed = set((phase or {}).get("gates") or [])
    if checkpoint_code not in allowed:
        raise CreationDenied("process_checkpoint_not_allowed")
    if not _phase_tasks_complete(db, instance, phase):
        raise CreationDenied("process_gate_evidence_incomplete")
    if checkpoint_code == "explicit_documents_selected" and not instance.context_json.get("document_ids"):
        raise CreationDenied("process_gate_evidence_incomplete")
    context = deepcopy(instance.context_json)
    completed = set(context.get("completed_checkpoints") or [])
    completed.add(checkpoint_code)
    context["completed_checkpoints"] = sorted(completed)
    instance.context_json = context
    db.add(ProcessInstanceEvent(process_instance_id=instance.id, actor_user_id=user.id, action="process.checkpoint_completed", details_json={"phase": current, "checkpoint": checkpoint_code}))
    record_audit(db, "process.checkpoint_completed", "process_instance", instance.id, user_id=user.id, after_json={"phase": current, "checkpoint": checkpoint_code})
    return instance


def advance_process_phase(db: Session, *, user: User, instance: ProcessInstance, justification: str | None = None) -> ProcessInstance:
    ProcessExecutionCapabilityResolver(db).require(user, instance)
    phases = instance.model_snapshot_json.get("phases") or []
    current = instance.context_json.get("current_phase_code")
    index = next((index for index, item in enumerate(phases) if item.get("code") == current), None)
    if index is None:
        raise CreationDenied("process_phase_invalid")
    phase = phases[index]
    required = set(phase.get("gates") or [])
    completed = set(instance.context_json.get("completed_checkpoints") or [])
    if not _phase_tasks_complete(db, instance, phase) or not required.issubset(completed):
        raise CreationDenied("process_phase_incomplete")
    role_codes = set(db.scalars(select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user.id, Role.active.is_(True))))
    if "manager" in role_codes and instance.model_snapshot_json.get("manager_execution_requires_justification", True) and not (justification or "").strip():
        raise CreationDenied("manager_justification_required")
    context = deepcopy(instance.context_json)
    history = list(context.get("phase_history") or [])
    history.append({"phase": current, "completed_at": datetime.now(timezone.utc).isoformat(), "actor_user_id": user.id})
    context["phase_history"] = history
    action = "process.completed"
    if index + 1 < len(phases):
        context["current_phase_code"] = phases[index + 1]["code"]
        action = "process.phase_advanced"
    else:
        instance.status = "completed"
    instance.context_json = context
    details = {"from": current, "to": context.get("current_phase_code"), "justification": bool(justification)}
    db.add(ProcessInstanceEvent(process_instance_id=instance.id, actor_user_id=user.id, action=action, details_json=details))
    record_audit(db, action, "process_instance", instance.id, user_id=user.id, after_json=details)
    return instance


USED_VEHICLE_SALE_DEFINITION = {
    "code": "used_vehicle_sale_to_merchant",
    "required_start_permissions": ["vehicle_sales.process.create"],
    "allowed_sources": ["sale_process_close", "manual"],
    "manager_execution_requires_justification": True,
    "selection": {
        "vehicles": ["selected", "all_authorized"],
        "documents": "explicit_only",
        "reject_unlisted_documents": True,
    },
    "external_effects": {
        "email": {"enabled": False, "template": "merchant_sale_review", "human_review_required": True},
        "portal": {"enabled": False, "preview_required": True, "explicit_authorization_required": True},
        "webhooks": False,
    },
    "phases": [
        {"code": "preparation", "name": "Preparação", "required": True, "tasks": ["select_vehicles", "select_documents", "prepare_merchant_ticket"], "gates": ["explicit_documents_selected"]},
        {"code": "operational_validation", "name": "Validação operacional", "required": True, "depends_on": ["preparation"], "tasks": ["validate_vehicle_state", "validate_document_set"], "gates": ["operational_validation_complete"]},
        {"code": "documentation_delivery", "name": "Documentação e entrega", "required": True, "depends_on": ["operational_validation"], "tasks": ["review_email", "preview_portal", "confirm_delivery"], "gates": ["human_communications_reviewed"]},
        {"code": "financial", "name": "Financeiro", "required": True, "depends_on": ["operational_validation", "documentation_delivery"], "tasks": ["validate_amounts", "confirm_settlement"], "gates": ["financial_reconciled"]},
        {"code": "close", "name": "Fecho", "required": True, "depends_on": ["financial"], "tasks": ["reconcile_evidence", "close_sale"], "gates": []},
    ],
    "tasks": {
        "select_vehicles": {"unique": True, "required": True},
        "select_documents": {"unique": True, "required": True, "explicit_selection": True},
        "prepare_merchant_ticket": {"unique": True, "prefilled": True, "external_effect": False},
        "validate_vehicle_state": {"unique": True, "required": True},
        "validate_document_set": {"unique": True, "required": True},
        "review_email": {"unique": True, "human_review_required": True, "external_effect": False},
        "preview_portal": {"unique": True, "preview_required": True, "external_effect": False},
        "confirm_delivery": {"unique": True, "required": True},
        "validate_amounts": {"unique": True, "required": True},
        "confirm_settlement": {"unique": True, "required": True},
        "reconcile_evidence": {"unique": True, "required": True},
        "close_sale": {"unique": True, "required": True},
    },
    "dependencies": [{"before": "operational_validation", "after": "financial"}],
    "required_gates": ["operational_validation_complete", "explicit_documents_selected", "human_communications_reviewed", "financial_reconciled"],
    "documents": {"source": "vehicle_record", "selection": "explicit_only", "paths_never_exposed": True},
    "sla": {"alerts": True, "external_jobs": False},
    "responsibility_rules": {
        "executor_can_start_with_permission": True,
        "team_coordinator_scope": "own_team",
        "operational_coordinator_scope": "authorized_units",
        "manager_requires_alert_and_justification": True,
        "administrator_operational_access": False,
    },
    "audit": {"snapshot_version": True, "phase_transitions": True, "manager_exceptions": True},
}


def workshop_parity_supported(definition: dict) -> bool:
    required = {"phases", "tasks", "dependencies", "required_gates", "documents", "sla", "responsibility_rules"}
    return required.issubset(definition)
