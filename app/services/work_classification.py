from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, false, or_, select

from app.models.admin import UserRole
from app.models.classification_proposals import ClassificationProposal
from app.models.organization import TeamMember
from app.models.tasks import TaskHelpRequest, TaskParticipant
from app.models.work_hierarchy import (
    RoleWorkScope,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
    WorkSourceDefault,
    WorkSubcategory,
)

CONTENT_TYPES = {
    "message": "Mensagem / informação",
    "document": "Documento para tratar",
    "request": "Pedido",
    "complaint": "Reclamação",
    "incident": "Anomalia / incidente",
    "other": "Outro",
}

WORK_NATURES = {
    "operational": "Operacional",
    "stock": "Stock",
    "financial": "Financeira",
    "workshop": "Oficina",
    "fleet": "Frota",
    "audit": "Auditoria",
    "administration": "Administração",
    "other": "Outra",
}

DOCUMENT_TYPES = {
    "invoice": "Fatura",
    "credit_note": "Nota de crédito",
    "quote": "Orçamento",
    "work_order": "Folha de obra",
    "contract": "Contrato",
    "receipt": "Recibo / comprovativo",
    "report": "Relatório",
    "vehicle_document": "Documento de viatura",
    "other": "Outro documento",
}

ATTACHMENT_STATUSES = {
    "pending": "Por tratar",
    "classified": "Classificado",
    "routed": "Encaminhado",
    "associated": "Associado",
    "ignored": "Sem tratamento",
}

TASK_DESTINATION = {
    "operational": ("operational_task", "operations"),
    "stock": ("operational_task", "stock"),
    "financial": ("administration_task", "finance"),
    "workshop": ("workshop_task", "workshop"),
    "fleet": ("operational_task", "fleet"),
    "audit": ("audit_task", "documents"),
    "administration": ("administration_task", "administration"),
    "other": ("operational_task", "other"),
}


def parse_classification_choice(value: str | int | None) -> tuple[int | None, int | None]:
    """Return (official_id, proposal_id) for a common selector value."""
    if isinstance(value, int):
        return value, None
    cleaned = str(value or "").strip()
    if cleaned.startswith("proposal:") and cleaned[9:].isdigit():
        return None, int(cleaned[9:])
    return (int(cleaned), None) if cleaned.isdigit() else (None, None)


def task_classification(nature: str | None) -> tuple[str, str]:
    return TASK_DESTINATION.get(nature or "", TASK_DESTINATION["operational"])


def thread_reference(thread) -> str:
    year = (
        (thread.created_at or thread.last_message_at).year
        if (thread.created_at or thread.last_message_at)
        else 0
    )
    return f"EM-{year:04d}-{thread.id:06d}"


def message_reference(thread, position: int) -> str:
    return f"{thread_reference(thread)}.{position:02d}"


def attachment_reference(thread, message_position: int, attachment_position: int) -> str:
    return f"{message_reference(thread, message_position)}-A{attachment_position:02d}"


@dataclass(frozen=True)
class WorkHierarchySelection:
    queue: WorkQueue
    department: WorkDepartment
    category: WorkCategory | None
    subcategory: WorkSubcategory | None
    status: str
    other_text: str | None


def work_hierarchy_context(db, *, active_only: bool = True) -> dict[str, object]:
    queues_query = select(WorkQueue)
    departments_query = select(WorkDepartment)
    categories_query = select(WorkCategory)
    subcategories_query = select(WorkSubcategory)
    if active_only:
        queues_query = queues_query.where(WorkQueue.active.is_(True))
        departments_query = departments_query.where(WorkDepartment.active.is_(True))
        categories_query = categories_query.where(WorkCategory.active.is_(True))
        subcategories_query = subcategories_query.where(WorkSubcategory.active.is_(True))
    queues = list(db.scalars(queues_query.order_by(WorkQueue.sort_order, WorkQueue.name)))
    departments = list(
        db.scalars(departments_query.order_by(WorkDepartment.sort_order, WorkDepartment.name))
    )
    categories = list(
        db.scalars(categories_query.order_by(WorkCategory.sort_order, WorkCategory.name))
    )
    subcategories = list(
        db.scalars(
            subcategories_query.order_by(WorkSubcategory.sort_order, WorkSubcategory.name)
        )
    )
    proposals = list(
        db.scalars(
            select(ClassificationProposal)
            .where(ClassificationProposal.active.is_(True))
            .order_by(ClassificationProposal.kind, ClassificationProposal.proposed_name)
        )
    )
    if active_only:
        all_queues = list(db.scalars(select(WorkQueue)))
        all_departments = list(db.scalars(select(WorkDepartment)))
        all_categories = list(db.scalars(select(WorkCategory)))
        all_subcategories = list(db.scalars(select(WorkSubcategory)))
    else:
        all_queues = queues
        all_departments = departments
        all_categories = categories
        all_subcategories = subcategories
    return {
        "work_queues": queues,
        "work_departments": departments,
        "work_categories": categories,
        "work_subcategories": subcategories,
        "work_queues_by_id": {item.id: item for item in queues},
        "work_departments_by_id": {item.id: item for item in departments},
        "work_categories_by_id": {item.id: item for item in categories},
        "work_subcategories_by_id": {item.id: item for item in subcategories},
        "classification_proposals": proposals,
        "classification_proposals_by_id": {item.id: item for item in proposals},
        # Active rows feed selectors; these complete maps preserve readable history
        # when an administrator later deactivates or renames a classification.
        "work_queue_labels": {item.id: item.name for item in all_queues},
        "work_department_labels": {item.id: item.name for item in all_departments},
        "work_category_labels": {item.id: item.name for item in all_categories},
        "work_subcategory_labels": {item.id: item.name for item in all_subcategories},
        "work_hierarchy_json": {
            "departments": [
                {
                    "id": item.id,
                    "parent_id": item.queue_id,
                    "name": item.name,
                    "requires_description": item.requires_description,
                }
                for item in departments
            ],
            "categories": [
                {
                    "id": item.id,
                    "parent_id": item.department_id,
                    "name": item.name,
                    "requires_description": item.requires_description,
                }
                for item in categories
            ],
            "subcategories": [
                {
                    "id": item.id,
                    "parent_id": item.category_id,
                    "name": item.name,
                    "requires_description": item.requires_description,
                }
                for item in subcategories
            ],
            "proposals": [
                {
                    "id": item.id,
                    "kind": item.kind,
                    "parent_id": item.department_id
                    if item.kind == "category"
                    else item.category_id,
                    "parent_proposal_id": item.parent_proposal_id,
                    "name": item.proposed_name,
                    "code": item.provisional_code,
                    "usage_count": item.usage_count,
                    "status": item.status,
                }
                for item in proposals
            ],
        },
    }


def validate_work_hierarchy(
    db,
    *,
    queue_id: int | None,
    department_id: int | None,
    category_id: int | None = None,
    subcategory_id: int | None = None,
    other_text: str = "",
    require_category: bool = False,
) -> WorkHierarchySelection | None:
    queue = db.get(WorkQueue, queue_id) if queue_id else None
    department = db.get(WorkDepartment, department_id) if department_id else None
    category = db.get(WorkCategory, category_id) if category_id else None
    subcategory = db.get(WorkSubcategory, subcategory_id) if subcategory_id else None
    if not queue or not queue.active or not department or not department.active:
        return None
    if department.queue_id != queue.id:
        return None
    if require_category and not category:
        return None
    if category and (not category.active or category.department_id != department.id):
        return None
    if subcategory and (
        not category or not subcategory.active or subcategory.category_id != category.id
    ):
        return None
    cleaned_other = other_text.strip() or None
    requires_description = any(
        item and item.requires_description for item in (department, category, subcategory)
    )
    if requires_description and not cleaned_other:
        return None
    status = "review" if requires_description else "classified"
    return WorkHierarchySelection(
        queue=queue,
        department=department,
        category=category,
        subcategory=subcategory,
        status=status,
        other_text=cleaned_other,
    )


def user_work_scope_allows(
    db,
    *,
    user_id: int,
    queue_id: int | None,
    department_id: int | None,
    category_id: int | None,
    subcategory_id: int | None,
    action: str,
    task=None,
) -> bool:
    scopes = list(
        db.scalars(
            select(RoleWorkScope)
            .join(UserRole, UserRole.role_id == RoleWorkScope.role_id)
            .where(UserRole.user_id == user_id)
        )
    )
    if not scopes:
        return True
    permission_field = {
        "read": "can_read",
        "create": "can_create",
        "update": "can_update",
        "assign": "can_assign",
        "assume": "can_assume",
        "respond": "can_respond",
        "close": "can_complete",
        "complete": "can_complete",
        "manage_sla": "can_manage_sla",
        "admin_classifications": "can_administer_classifications",
        "manage": "can_manage",
    }.get(action)
    if not permission_field:
        return False
    task_required_actions = {
        "read",
        "update",
        "assign",
        "assume",
        "respond",
        "close",
        "complete",
        "manage_sla",
        "manage",
    }
    for scope in scopes:
        matches = queue_id is None or (
            scope.queue_id == queue_id
            and (scope.department_id is None or scope.department_id == department_id)
            and (scope.category_id is None or scope.category_id == category_id)
            and (scope.subcategory_id is None or scope.subcategory_id == subcategory_id)
        )
        if scope.visibility_mode == "consult" and action != "read":
            continue
        requires_direct_relation = (
            scope.visibility_mode == "direct_only" and action in task_required_actions
        )
        direct_relation_allowed = not requires_direct_relation or (
            task is not None and _task_has_direct_relation(db, user_id=user_id, task=task)
        )
        if (
            matches
            and _scope_grants(scope, permission_field)
            and direct_relation_allowed
        ):
            return True
    return False


def _task_direct_relation_filter(*, user_id: int, task_model):
    member_team_ids = select(TeamMember.team_id).where(TeamMember.user_id == user_id)
    participant_task_ids = select(TaskParticipant.task_id).where(
        TaskParticipant.user_id == user_id,
        TaskParticipant.status == "active",
    )
    help_task_ids = select(TaskHelpRequest.task_id).where(
        TaskHelpRequest.requested_user_id == user_id,
        TaskHelpRequest.status == "pending",
    )
    return or_(
        task_model.assigned_to_id == user_id,
        task_model.team_id.in_(member_team_ids),
        task_model.created_by_id == user_id,
        task_model.id.in_(participant_task_ids),
        task_model.id.in_(help_task_ids),
    )


def _scope_grants(scope: RoleWorkScope, permission_field: str) -> bool:
    granted = bool(getattr(scope, permission_field) or scope.can_manage)
    if permission_field == "can_complete":
        granted = granted or scope.can_close
    return granted


def _task_has_direct_relation(db, *, user_id: int, task) -> bool:
    if task.assigned_to_id == user_id or task.created_by_id == user_id:
        return True
    if task.team_id and db.scalar(
        select(TeamMember.id).where(
            TeamMember.team_id == task.team_id,
            TeamMember.user_id == user_id,
        )
    ):
        return True
    if db.scalar(
        select(TaskParticipant.id).where(
            TaskParticipant.task_id == task.id,
            TaskParticipant.user_id == user_id,
            TaskParticipant.status == "active",
        )
    ):
        return True
    return bool(
        db.scalar(
            select(TaskHelpRequest.id).where(
                TaskHelpRequest.task_id == task.id,
                TaskHelpRequest.requested_user_id == user_id,
                TaskHelpRequest.status == "pending",
            )
        )
    )


def user_work_scope_filter(db, *, user_id: int, task_model, action: str = "read"):
    """Return a SQL scope filter while leaving legacy, unclassified tasks accessible."""
    scopes = list(
        db.scalars(
            select(RoleWorkScope)
            .join(UserRole, UserRole.role_id == RoleWorkScope.role_id)
            .where(UserRole.user_id == user_id)
        )
    )
    if not scopes:
        return None
    permission_field = {
        "read": "can_read",
        "create": "can_create",
        "update": "can_update",
        "assign": "can_assign",
        "assume": "can_assume",
        "respond": "can_respond",
        "close": "can_complete",
        "complete": "can_complete",
        "manage_sla": "can_manage_sla",
        "admin_classifications": "can_administer_classifications",
        "manage": "can_manage",
    }.get(action)
    if not permission_field:
        return False
    allowed = []
    permits_unclassified = False
    direct_relation = _task_direct_relation_filter(user_id=user_id, task_model=task_model)
    for scope in scopes:
        if scope.visibility_mode == "consult" and action != "read":
            continue
        if not _scope_grants(scope, permission_field):
            continue
        conditions = [task_model.work_queue_id == scope.queue_id]
        if scope.department_id is not None:
            conditions.append(task_model.work_department_id == scope.department_id)
        if scope.category_id is not None:
            conditions.append(task_model.work_category_id == scope.category_id)
        if scope.subcategory_id is not None:
            conditions.append(task_model.work_subcategory_id == scope.subcategory_id)
        if scope.visibility_mode == "direct_only":
            conditions.append(direct_relation)
        else:
            permits_unclassified = True
        allowed.append(and_(*conditions))
    if allowed:
        if permits_unclassified:
            return or_(task_model.work_queue_id.is_(None), *allowed)
        return or_(and_(task_model.work_queue_id.is_(None), direct_relation), *allowed)
    return false()


def source_work_default(db, *, source_type: str, source_key: str = "default"):
    """Resolve an active source default, preferring the exact key over the default key."""
    cleaned_type = source_type.strip().lower()
    cleaned_key = source_key.strip().lower() or "default"
    return db.scalar(
        select(WorkSourceDefault)
        .where(
            WorkSourceDefault.source_type == cleaned_type,
            WorkSourceDefault.source_key.in_((cleaned_key, "default")),
            WorkSourceDefault.active.is_(True),
        )
        .order_by((WorkSourceDefault.source_key == cleaned_key).desc(), WorkSourceDefault.id)
    )


def apply_source_work_default(
    db,
    task,
    *,
    source_type: str,
    source_key: str = "default",
):
    """Apply a configured hierarchy only when the task has not been classified explicitly."""
    if task.work_queue_id or task.work_department_id:
        return task
    default = source_work_default(db, source_type=source_type, source_key=source_key)
    if not default or not default.queue_id or not default.department_id:
        return task
    hierarchy = validate_work_hierarchy(
        db,
        queue_id=default.queue_id,
        department_id=default.department_id,
        category_id=default.category_id,
        subcategory_id=default.subcategory_id,
    )
    if not hierarchy:
        return task
    task.work_queue_id = hierarchy.queue.id
    task.work_department_id = hierarchy.department.id
    task.work_category_id = hierarchy.category.id if hierarchy.category else None
    task.work_subcategory_id = hierarchy.subcategory.id if hierarchy.subcategory else None
    task.classification_status = hierarchy.status
    return task
