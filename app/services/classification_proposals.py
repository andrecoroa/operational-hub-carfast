from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from difflib import SequenceMatcher

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError

from app.models.classification_proposals import (
    ClassificationProposal,
    ClassificationProposalAudit,
    ClassificationProposalUsage,
    ClassificationSequence,
)
from app.models.email import EmailAuditEvent, EmailThread
from app.models.evolution import EvolutionRecord, EvolutionRecordHistory
from app.models.tasks import Task, TaskHistory
from app.models.work_hierarchy import WorkCategory, WorkDepartment, WorkSubcategory
from app.services.audit import record_audit

OPEN_PROPOSAL_STATUSES = {"pending", "observation"}
FINAL_PROPOSAL_STATUSES = {"approved", "linked", "merged", "rejected", "archived"}


class DuplicateProposalError(ValueError):
    def __init__(self, proposal: ClassificationProposal):
        self.proposal = proposal
        super().__init__(f"Já existe a proposta {proposal.provisional_code} nesta hierarquia.")


@dataclass(frozen=True)
class ProposalSelection:
    category: ClassificationProposal | None
    subcategory: ClassificationProposal | None


def normalize_classification_name(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(without_accents.casefold().split())


def _next_code(db, *, scope: str, prefix: str) -> str:
    db.execute(
        text(
            "INSERT INTO classification_sequences (scope, value, updated_at) "
            "VALUES (:scope, 0, CURRENT_TIMESTAMP) ON CONFLICT (scope) DO NOTHING"
        ),
        {"scope": scope},
    )
    value = db.scalar(
        update(ClassificationSequence)
        .where(ClassificationSequence.scope == scope)
        .values(value=ClassificationSequence.value + 1, updated_at=datetime.now(UTC))
        .returning(ClassificationSequence.value)
    )
    if value is None:
        raise RuntimeError("Não foi possível reservar o código técnico da classificação.")
    return f"{prefix}-{value:06d}"


def _proposal_hierarchy_key(
    *,
    kind: str,
    department_id: int,
    category_id: int | None,
    parent_proposal_id: int | None,
) -> str:
    if kind == "category":
        return f"department:{department_id}"
    if category_id:
        return f"category:{category_id}"
    return f"proposal:{parent_proposal_id}"


def proposal_snapshot(proposal: ClassificationProposal) -> dict[str, object]:
    return {
        "id": proposal.id,
        "code": proposal.provisional_code,
        "kind": proposal.kind,
        "name": proposal.proposed_name,
        "normalized_name": proposal.normalized_name,
        "status": proposal.status,
        "active": proposal.active,
        "department_id": proposal.department_id,
        "category_id": proposal.category_id,
        "parent_proposal_id": proposal.parent_proposal_id,
        "usage_count": proposal.usage_count,
        "last_used_at": proposal.last_used_at.isoformat() if proposal.last_used_at else None,
        "definitive_category_id": proposal.definitive_category_id,
        "definitive_subcategory_id": proposal.definitive_subcategory_id,
        "merged_into_proposal_id": proposal.merged_into_proposal_id,
    }


def _audit_proposal(
    db,
    proposal: ClassificationProposal,
    *,
    actor_user_id: int | None,
    action: str,
    before: dict | None = None,
    details: str | None = None,
) -> None:
    after = proposal_snapshot(proposal)
    db.add(
        ClassificationProposalAudit(
            proposal_id=proposal.id,
            actor_user_id=actor_user_id,
            action=action,
            before_json=before,
            after_json=after,
            details=details,
        )
    )
    record_audit(
        db,
        action=f"classification_proposal.{action}",
        entity_type="classification_proposal",
        entity_id=proposal.id,
        detail=details or proposal.provisional_code,
        user_id=actor_user_id,
        before_json=before,
        after_json=after,
    )


def _evolution_description(
    *,
    code: str,
    kind: str,
    name: str,
    reason: str,
    origin_module: str,
    origin_url: str | None,
    department_id: int,
    category_id: int | None,
    parent_proposal_id: int | None,
) -> str:
    kind_label = "Categoria" if kind == "category" else "Subcategoria"
    hierarchy = f"departamento={department_id}"
    if category_id:
        hierarchy += f"; categoria={category_id}"
    if parent_proposal_id:
        hierarchy += f"; proposta-pai={parent_proposal_id}"
    return (
        f"{kind_label} provisória {code}: {name}\n"
        f"Hierarquia: {hierarchy}\n"
        f"Origem: {origin_module}{' · ' + origin_url if origin_url else ''}\n"
        f"Motivo: {reason}"
    )


def create_proposal(
    db,
    *,
    kind: str,
    name: str,
    reason: str,
    department_id: int,
    proposed_by_id: int,
    origin_module: str,
    origin_url: str | None = None,
    origin_reference: str | None = None,
    category_id: int | None = None,
    parent_proposal_id: int | None = None,
    now: datetime | None = None,
) -> ClassificationProposal:
    effective_now = now or datetime.now(UTC)
    cleaned_name = " ".join(name.split())[:160]
    cleaned_reason = reason.strip()
    if kind not in {"category", "subcategory"}:
        raise ValueError("O tipo da proposta é inválido.")
    if not cleaned_name or not cleaned_reason:
        raise ValueError("Nome e motivo são obrigatórios.")
    department = db.get(WorkDepartment, department_id)
    if not department or not department.active:
        raise ValueError("O departamento superior não está ativo.")
    category = db.get(WorkCategory, category_id) if category_id else None
    parent = db.get(ClassificationProposal, parent_proposal_id) if parent_proposal_id else None
    if kind == "category" and (category or parent):
        raise ValueError("Uma categoria proposta deve depender apenas do departamento.")
    if kind == "subcategory":
        if bool(category) == bool(parent):
            raise ValueError("Indica uma categoria oficial ou proposta como hierarquia superior.")
        if category and (not category.active or category.department_id != department.id):
            raise ValueError("A categoria superior não pertence ao departamento selecionado.")
        if parent and (
            not parent.active or parent.kind != "category" or parent.department_id != department.id
        ):
            raise ValueError("A proposta de categoria superior não é válida.")
    normalized = normalize_classification_name(cleaned_name)
    hierarchy_key = _proposal_hierarchy_key(
        kind=kind,
        department_id=department.id,
        category_id=category.id if category else None,
        parent_proposal_id=parent.id if parent else None,
    )
    duplicate = db.scalar(
        select(ClassificationProposal).where(
            ClassificationProposal.kind == kind,
            ClassificationProposal.hierarchy_key == hierarchy_key,
            ClassificationProposal.normalized_name == normalized,
            ClassificationProposal.active.is_(True),
        )
    )
    if duplicate:
        raise DuplicateProposalError(duplicate)
    code = _next_code(
        db,
        scope=f"proposal:{effective_now.year}",
        prefix=f"PROP-{'CAT' if kind == 'category' else 'SUB'}-{effective_now.year}",
    )
    proposal = ClassificationProposal(
        provisional_code=code,
        kind=kind,
        proposed_name=cleaned_name,
        normalized_name=normalized,
        hierarchy_key=hierarchy_key,
        reason=cleaned_reason,
        department_id=department.id,
        category_id=category.id if category else None,
        parent_proposal_id=parent.id if parent else None,
        proposed_by_id=proposed_by_id,
        origin_module=(origin_module.strip() or "common")[:80],
        origin_url=origin_url.strip()[:500] if origin_url and origin_url.strip() else None,
        origin_reference=(
            origin_reference.strip()[:160]
            if origin_reference and origin_reference.strip()
            else None
        ),
        status="pending",
        active=True,
    )
    db.add(proposal)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ValueError(
            "A proposta colidiu com outra criação concorrente; pesquisa novamente."
        ) from exc
    evolution = EvolutionRecord(
        record_type="feature",
        module="classification_catalog",
        title=f"Classificação por validar · {code}",
        description=_evolution_description(
            code=code,
            kind=kind,
            name=cleaned_name,
            reason=cleaned_reason,
            origin_module=proposal.origin_module,
            origin_url=proposal.origin_url,
            department_id=department.id,
            category_id=category.id if category else None,
            parent_proposal_id=parent.id if parent else None,
        ),
        origin=proposal.origin_module,
        priority="normal",
        status="registered",
        created_by_id=proposed_by_id,
        updated_by_id=proposed_by_id,
    )
    db.add(evolution)
    db.flush()
    proposal.evolution_record_id = evolution.id
    _audit_proposal(
        db,
        proposal,
        actor_user_id=proposed_by_id,
        action="created",
        details=f"Proposta criada em {proposal.origin_module}.",
    )
    return proposal


def proposal_suggestions(
    db,
    *,
    kind: str,
    name: str,
    department_id: int,
    category_id: int | None = None,
    parent_proposal_id: int | None = None,
    limit: int = 8,
) -> list[dict[str, object]]:
    needle = normalize_classification_name(name)
    if not needle:
        return []
    rows: list[dict[str, object]] = []
    if kind == "category":
        official = db.scalars(
            select(WorkCategory).where(WorkCategory.department_id == department_id)
        ).all()
    else:
        official = (
            db.scalars(
                select(WorkSubcategory).where(WorkSubcategory.category_id == category_id)
            ).all()
            if category_id
            else []
        )
    for item in official:
        normalized = normalize_classification_name(item.name)
        score = SequenceMatcher(None, needle, normalized).ratio()
        if needle in normalized or normalized in needle or score >= 0.55:
            rows.append(
                {
                    "type": "official",
                    "id": item.id,
                    "code": item.code,
                    "name": item.name,
                    "active": item.active,
                    "score": score,
                    "usage_count": None,
                    "last_used_at": None,
                }
            )
    hierarchy_key = _proposal_hierarchy_key(
        kind=kind,
        department_id=department_id,
        category_id=category_id,
        parent_proposal_id=parent_proposal_id,
    )
    proposals = db.scalars(
        select(ClassificationProposal).where(
            ClassificationProposal.kind == kind,
            ClassificationProposal.hierarchy_key == hierarchy_key,
            ClassificationProposal.active.is_(True),
        )
    ).all()
    for item in proposals:
        score = SequenceMatcher(None, needle, item.normalized_name).ratio()
        if needle in item.normalized_name or item.normalized_name in needle or score >= 0.45:
            rows.append(
                {
                    "type": "proposal",
                    "id": item.id,
                    "code": item.provisional_code,
                    "name": item.proposed_name,
                    "active": item.active,
                    "status": item.status,
                    "score": score,
                    "usage_count": item.usage_count,
                    "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
                    "priority_review": item.usage_count >= 3,
                }
            )
    return sorted(rows, key=lambda row: (-float(row["score"]), row["name"]))[:limit]


def validate_proposal_selection(
    db,
    *,
    department_id: int,
    official_category_id: int | None,
    category_proposal_id: int | None,
    subcategory_proposal_id: int | None,
) -> ProposalSelection:
    category = (
        db.get(ClassificationProposal, category_proposal_id) if category_proposal_id else None
    )
    subcategory = (
        db.get(ClassificationProposal, subcategory_proposal_id) if subcategory_proposal_id else None
    )
    for proposal, expected_kind in ((category, "category"), (subcategory, "subcategory")):
        if proposal and (
            not proposal.active
            or proposal.status not in OPEN_PROPOSAL_STATUSES
            or proposal.kind != expected_kind
            or proposal.department_id != department_id
        ):
            raise ValueError("A classificação provisória selecionada não está disponível.")
    if category_proposal_id and not category:
        raise ValueError("A proposta de categoria não existe.")
    if subcategory_proposal_id and not subcategory:
        raise ValueError("A proposta de subcategoria não existe.")
    if subcategory:
        if subcategory.category_id != official_category_id:
            if not category or subcategory.parent_proposal_id != category.id:
                raise ValueError("A subcategoria provisória não pertence à categoria selecionada.")
    return ProposalSelection(category=category, subcategory=subcategory)


def attach_proposal_usage(
    db,
    *,
    proposal: ClassificationProposal,
    entity_type: str,
    entity_id: int,
    module: str,
    actor_user_id: int,
    origin_url: str | None = None,
    now: datetime | None = None,
) -> ClassificationProposalUsage:
    effective_now = now or datetime.now(UTC)
    usage = db.scalar(
        select(ClassificationProposalUsage).where(
            ClassificationProposalUsage.proposal_id == proposal.id,
            ClassificationProposalUsage.entity_type == entity_type,
            ClassificationProposalUsage.entity_id == entity_id,
        )
    )
    if usage:
        usage.active = True
        usage.resolved_action = None
        usage.resolved_at = None
        usage.last_used_by_id = actor_user_id
        usage.updated_at = effective_now
        usage.origin_url = origin_url or usage.origin_url
    else:
        usage = ClassificationProposalUsage(
            proposal_id=proposal.id,
            entity_type=entity_type,
            entity_id=entity_id,
            module=module,
            origin_url=origin_url,
            first_used_by_id=actor_user_id,
            last_used_by_id=actor_user_id,
            active=True,
        )
        db.add(usage)
    db.flush()
    refresh_proposal_usage(db, proposal, now=effective_now)
    return usage


def attach_selection_to_entity(
    db,
    *,
    entity: Task | EmailThread,
    selection: ProposalSelection,
    actor_user_id: int,
    module: str,
    origin_url: str | None = None,
) -> None:
    entity_type = "task" if isinstance(entity, Task) else "email_thread"
    entity.provisional_category_id = selection.category.id if selection.category else None
    entity.provisional_subcategory_id = selection.subcategory.id if selection.subcategory else None
    if selection.category:
        entity.work_category_id = None
    if selection.subcategory:
        entity.work_subcategory_id = None
    entity.classification_status = "provisional"
    db.flush()
    for proposal in (selection.category, selection.subcategory):
        if proposal:
            attach_proposal_usage(
                db,
                proposal=proposal,
                entity_type=entity_type,
                entity_id=entity.id,
                module=module,
                actor_user_id=actor_user_id,
                origin_url=origin_url,
            )


def detach_entity_proposals(
    db,
    *,
    entity: Task | EmailThread,
    actor_user_id: int,
    action: str = "manual_reclassification",
    now: datetime | None = None,
) -> None:
    effective_now = now or datetime.now(UTC)
    entity_type = "task" if isinstance(entity, Task) else "email_thread"
    proposal_ids = {
        item for item in (entity.provisional_category_id, entity.provisional_subcategory_id) if item
    }
    if not proposal_ids:
        return
    usages = db.scalars(
        select(ClassificationProposalUsage).where(
            ClassificationProposalUsage.proposal_id.in_(proposal_ids),
            ClassificationProposalUsage.entity_type == entity_type,
            ClassificationProposalUsage.entity_id == entity.id,
            ClassificationProposalUsage.active.is_(True),
        )
    ).all()
    for usage in usages:
        usage.active = False
        usage.resolved_action = action
        usage.resolved_at = effective_now
        usage.last_used_by_id = actor_user_id
    entity.provisional_category_id = None
    entity.provisional_subcategory_id = None
    db.flush()
    for proposal_id in proposal_ids:
        proposal = db.get(ClassificationProposal, proposal_id)
        if proposal:
            refresh_proposal_usage(db, proposal, now=effective_now)


def refresh_proposal_usage(
    db, proposal: ClassificationProposal, *, now: datetime | None = None
) -> None:
    db.flush()
    count, last_used = db.execute(
        select(
            func.count(ClassificationProposalUsage.id),
            func.max(ClassificationProposalUsage.updated_at),
        ).where(
            ClassificationProposalUsage.proposal_id == proposal.id,
            ClassificationProposalUsage.active.is_(True),
        )
    ).one()
    proposal.usage_count = int(count or 0)
    proposal.last_used_at = last_used
    if proposal.evolution_record_id:
        evolution = db.get(EvolutionRecord, proposal.evolution_record_id)
        if evolution:
            evolution.priority = "high" if proposal.usage_count >= 3 else "normal"
            last_used_label = (
                proposal.last_used_at.isoformat() if proposal.last_used_at else "-"
            )
            evolution.notes = (
                f"Utilizações ativas: {proposal.usage_count}. "
                f"Última utilização: {last_used_label}"
            )


def _catalog_code(db, *, kind: str) -> str:
    prefix = "CAT" if kind == "category" else "SUB"
    model = WorkCategory if kind == "category" else WorkSubcategory
    for _ in range(10):
        code = _next_code(db, scope=f"catalog:{kind}", prefix=prefix)
        if not db.scalar(select(model.id).where(model.code == code)):
            return code
    raise RuntimeError("Não foi possível reservar um código definitivo único.")


def _record_entity_reclassification(
    db,
    *,
    entity: Task | EmailThread,
    proposal: ClassificationProposal,
    action: str,
    actor_user_id: int,
) -> None:
    if isinstance(entity, Task):
        target_label = (
            f"{entity.work_category_id or '-'}:{entity.work_subcategory_id or '-'}"
        )
        db.add(
            TaskHistory(
                task_id=entity.id,
                user_id=actor_user_id,
                field_name="classification_proposal",
                old_value=proposal.provisional_code,
                new_value=f"{action}:{target_label}",
            )
        )
    else:
        db.add(
            EmailAuditEvent(
                thread_id=entity.id,
                user_id=actor_user_id,
                action="classification_proposal_resolved",
                details_json={
                    "proposal": proposal.provisional_code,
                    "decision": action,
                    "category_id": entity.work_category_id,
                    "subcategory_id": entity.work_subcategory_id,
                },
            )
        )


def _resolve_usage_to_official(
    db,
    *,
    proposal: ClassificationProposal,
    usage: ClassificationProposalUsage,
    target: WorkCategory | WorkSubcategory,
    actor_user_id: int,
    action: str,
    now: datetime,
) -> None:
    entity = (
        db.get(Task, usage.entity_id)
        if usage.entity_type == "task"
        else db.get(EmailThread, usage.entity_id)
    )
    if entity:
        if proposal.kind == "category":
            category = target
            department = db.get(WorkDepartment, category.department_id)
            entity.work_queue_id = department.queue_id
            entity.work_department_id = department.id
            entity.work_category_id = category.id
            if entity.work_subcategory_id:
                current_sub = db.get(WorkSubcategory, entity.work_subcategory_id)
                if not current_sub or current_sub.category_id != category.id:
                    entity.work_subcategory_id = None
            entity.provisional_category_id = None
        else:
            subcategory = target
            category = db.get(WorkCategory, subcategory.category_id)
            department = db.get(WorkDepartment, category.department_id)
            entity.work_queue_id = department.queue_id
            entity.work_department_id = department.id
            entity.work_category_id = category.id
            entity.work_subcategory_id = subcategory.id
            entity.provisional_subcategory_id = None
        entity.classification_status = (
            "provisional"
            if entity.provisional_category_id or entity.provisional_subcategory_id
            else "classified"
        )
        entity.classification_updated_by_id = actor_user_id
        entity.classification_updated_at = now
        _record_entity_reclassification(
            db,
            entity=entity,
            proposal=proposal,
            action=action,
            actor_user_id=actor_user_id,
        )
    usage.active = False
    usage.resolved_action = action
    usage.resolved_at = now
    usage.last_used_by_id = actor_user_id


def _update_evolution_decision(
    db,
    proposal: ClassificationProposal,
    *,
    actor_user_id: int,
    status: str,
    decision: str,
) -> None:
    if not proposal.evolution_record_id:
        return
    evolution = db.get(EvolutionRecord, proposal.evolution_record_id)
    if not evolution:
        return
    old = evolution.status
    evolution.status = status
    evolution.decision = decision
    evolution.updated_by_id = actor_user_id
    db.add(
        EvolutionRecordHistory(
            record_id=evolution.id,
            user_id=actor_user_id,
            field_name="classification_decision",
            old_value=old,
            new_value=f"{status}: {decision}",
        )
    )


def approve_proposal(
    db,
    *,
    proposal: ClassificationProposal,
    actor_user_id: int,
    approved_name: str | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> WorkCategory | WorkSubcategory:
    if not proposal.active or proposal.status not in OPEN_PROPOSAL_STATUSES:
        raise ValueError("A proposta já não está disponível para aprovação.")
    before = proposal_snapshot(proposal)
    effective_now = now or datetime.now(UTC)
    name = " ".join((approved_name or proposal.proposed_name).split())[:160]
    if not name:
        raise ValueError("O nome definitivo é obrigatório.")
    if proposal.kind == "category":
        target = WorkCategory(
            department_id=proposal.department_id,
            code=_catalog_code(db, kind="category"),
            name=name,
            description=proposal.reason,
            requires_description=False,
            active=True,
            sort_order=100,
        )
        db.add(target)
        db.flush()
        proposal.definitive_category_id = target.id
    else:
        category_id = proposal.category_id
        if not category_id and proposal.parent_proposal_id:
            parent = db.get(ClassificationProposal, proposal.parent_proposal_id)
            category_id = parent.definitive_category_id if parent else None
        if not category_id:
            raise ValueError("A categoria superior deve ser validada antes da subcategoria.")
        target = WorkSubcategory(
            category_id=category_id,
            code=_catalog_code(db, kind="subcategory"),
            name=name,
            description=proposal.reason,
            requires_description=False,
            active=True,
            sort_order=100,
        )
        db.add(target)
        db.flush()
        proposal.definitive_subcategory_id = target.id
    usages = db.scalars(
        select(ClassificationProposalUsage).where(
            ClassificationProposalUsage.proposal_id == proposal.id,
            ClassificationProposalUsage.active.is_(True),
        )
    ).all()
    for usage in usages:
        _resolve_usage_to_official(
            db,
            proposal=proposal,
            usage=usage,
            target=target,
            actor_user_id=actor_user_id,
            action="approved",
            now=effective_now,
        )
    proposal.proposed_name = name
    proposal.normalized_name = normalize_classification_name(name)
    proposal.status = "approved"
    proposal.active = False
    proposal.reviewed_by_id = actor_user_id
    proposal.reviewed_at = effective_now
    proposal.decision_notes = notes
    refresh_proposal_usage(db, proposal, now=effective_now)
    decision = f"Aprovada como {target.code} · {target.name}. {notes or ''}".strip()
    _update_evolution_decision(
        db, proposal, actor_user_id=actor_user_id, status="completed", decision=decision
    )
    _audit_proposal(
        db,
        proposal,
        actor_user_id=actor_user_id,
        action="approved",
        before=before,
        details=decision,
    )
    return target


def associate_proposal(
    db,
    *,
    proposal: ClassificationProposal,
    actor_user_id: int,
    target_id: int,
    notes: str | None = None,
    now: datetime | None = None,
) -> WorkCategory | WorkSubcategory:
    if not proposal.active or proposal.status not in OPEN_PROPOSAL_STATUSES:
        raise ValueError("A proposta já não está disponível.")
    before = proposal_snapshot(proposal)
    target = db.get(WorkCategory if proposal.kind == "category" else WorkSubcategory, target_id)
    if not target or not target.active:
        raise ValueError("A classificação oficial de destino não está ativa.")
    effective_now = now or datetime.now(UTC)
    for usage in db.scalars(
        select(ClassificationProposalUsage).where(
            ClassificationProposalUsage.proposal_id == proposal.id,
            ClassificationProposalUsage.active.is_(True),
        )
    ).all():
        _resolve_usage_to_official(
            db,
            proposal=proposal,
            usage=usage,
            target=target,
            actor_user_id=actor_user_id,
            action="linked",
            now=effective_now,
        )
    if proposal.kind == "category":
        proposal.definitive_category_id = target.id
    else:
        proposal.definitive_subcategory_id = target.id
    proposal.status = "linked"
    proposal.active = False
    proposal.reviewed_by_id = actor_user_id
    proposal.reviewed_at = effective_now
    proposal.decision_notes = notes
    refresh_proposal_usage(db, proposal, now=effective_now)
    decision = f"Associada a {target.code} · {target.name}. {notes or ''}".strip()
    _update_evolution_decision(
        db, proposal, actor_user_id=actor_user_id, status="completed", decision=decision
    )
    _audit_proposal(
        db,
        proposal,
        actor_user_id=actor_user_id,
        action="linked",
        before=before,
        details=decision,
    )
    return target


def merge_proposals(
    db,
    *,
    source: ClassificationProposal,
    target: ClassificationProposal,
    actor_user_id: int,
    notes: str | None = None,
    now: datetime | None = None,
) -> None:
    if source.id == target.id or source.kind != target.kind:
        raise ValueError("Seleciona outra proposta do mesmo tipo.")
    if not source.active or not target.active or target.status not in OPEN_PROPOSAL_STATUSES:
        raise ValueError("A origem e o destino devem estar ativos.")
    before = proposal_snapshot(source)
    effective_now = now or datetime.now(UTC)
    usages = db.scalars(
        select(ClassificationProposalUsage).where(
            ClassificationProposalUsage.proposal_id == source.id,
            ClassificationProposalUsage.active.is_(True),
        )
    ).all()
    for usage in usages:
        entity = (
            db.get(Task, usage.entity_id)
            if usage.entity_type == "task"
            else db.get(EmailThread, usage.entity_id)
        )
        if entity:
            if source.kind == "category" and entity.provisional_category_id == source.id:
                entity.provisional_category_id = target.id
            if source.kind == "subcategory" and entity.provisional_subcategory_id == source.id:
                entity.provisional_subcategory_id = target.id
            _record_entity_reclassification(
                db,
                entity=entity,
                proposal=source,
                action=f"merged:{target.provisional_code}",
                actor_user_id=actor_user_id,
            )
        attach_proposal_usage(
            db,
            proposal=target,
            entity_type=usage.entity_type,
            entity_id=usage.entity_id,
            module=usage.module,
            actor_user_id=actor_user_id,
            origin_url=usage.origin_url,
            now=effective_now,
        )
        usage.active = False
        usage.resolved_action = "merged"
        usage.resolved_at = effective_now
    source.status = "merged"
    source.active = False
    source.merged_into_proposal_id = target.id
    source.reviewed_by_id = actor_user_id
    source.reviewed_at = effective_now
    source.decision_notes = notes
    refresh_proposal_usage(db, source, now=effective_now)
    refresh_proposal_usage(db, target, now=effective_now)
    decision = f"Fundida em {target.provisional_code}. {notes or ''}".strip()
    _update_evolution_decision(
        db, source, actor_user_id=actor_user_id, status="completed", decision=decision
    )
    _audit_proposal(
        db,
        source,
        actor_user_id=actor_user_id,
        action="merged",
        before=before,
        details=decision,
    )


def reject_proposal(
    db,
    *,
    proposal: ClassificationProposal,
    actor_user_id: int,
    reason: str,
    now: datetime | None = None,
) -> None:
    if not reason.strip():
        raise ValueError("A recusa exige um motivo e instrução de reclassificação.")
    if not proposal.active or proposal.status not in OPEN_PROPOSAL_STATUSES:
        raise ValueError("A proposta já não está disponível.")
    before = proposal_snapshot(proposal)
    effective_now = now or datetime.now(UTC)
    usages = db.scalars(
        select(ClassificationProposalUsage).where(
            ClassificationProposalUsage.proposal_id == proposal.id,
            ClassificationProposalUsage.active.is_(True),
        )
    ).all()
    for usage in usages:
        entity = (
            db.get(Task, usage.entity_id)
            if usage.entity_type == "task"
            else db.get(EmailThread, usage.entity_id)
        )
        if entity:
            if proposal.kind == "category":
                entity.provisional_category_id = None
                entity.work_category_id = None
                entity.work_subcategory_id = None
            else:
                entity.provisional_subcategory_id = None
                entity.work_subcategory_id = None
            entity.classification_status = "reclassification_required"
            entity.classification_updated_by_id = actor_user_id
            entity.classification_updated_at = effective_now
            _record_entity_reclassification(
                db,
                entity=entity,
                proposal=proposal,
                action="rejected_reclassification_required",
                actor_user_id=actor_user_id,
            )
        usage.active = False
        usage.resolved_action = "rejected"
        usage.resolved_at = effective_now
    proposal.status = "rejected"
    proposal.active = False
    proposal.reviewed_by_id = actor_user_id
    proposal.reviewed_at = effective_now
    proposal.decision_notes = reason.strip()
    refresh_proposal_usage(db, proposal, now=effective_now)
    _update_evolution_decision(
        db,
        proposal,
        actor_user_id=actor_user_id,
        status="rejected",
        decision=reason.strip(),
    )
    _audit_proposal(
        db,
        proposal,
        actor_user_id=actor_user_id,
        action="rejected",
        before=before,
        details=reason.strip(),
    )


def observe_proposal(
    db,
    *,
    proposal: ClassificationProposal,
    actor_user_id: int,
    notes: str,
    now: datetime | None = None,
) -> None:
    if not proposal.active or proposal.status not in OPEN_PROPOSAL_STATUSES:
        raise ValueError("A proposta já não está disponível.")
    before = proposal_snapshot(proposal)
    proposal.status = "observation"
    proposal.reviewed_by_id = actor_user_id
    proposal.reviewed_at = now or datetime.now(UTC)
    proposal.decision_notes = notes.strip() or None
    _update_evolution_decision(
        db,
        proposal,
        actor_user_id=actor_user_id,
        status="analysis",
        decision=notes.strip() or "Mantida em observação.",
    )
    _audit_proposal(
        db,
        proposal,
        actor_user_id=actor_user_id,
        action="observation",
        before=before,
        details=notes.strip() or "Mantida em observação.",
    )


def archive_proposal(
    db,
    *,
    proposal: ClassificationProposal,
    actor_user_id: int,
    notes: str | None = None,
    now: datetime | None = None,
) -> None:
    refresh_proposal_usage(db, proposal)
    if proposal.usage_count:
        raise ValueError("Reclassifica ou associa as utilizações antes de arquivar.")
    if not proposal.active:
        raise ValueError("A proposta já não está ativa.")
    before = proposal_snapshot(proposal)
    proposal.status = "archived"
    proposal.active = False
    proposal.reviewed_by_id = actor_user_id
    proposal.reviewed_at = now or datetime.now(UTC)
    proposal.decision_notes = notes
    _update_evolution_decision(
        db,
        proposal,
        actor_user_id=actor_user_id,
        status="deferred",
        decision=notes or "Arquivada sem eliminação.",
    )
    _audit_proposal(
        db,
        proposal,
        actor_user_id=actor_user_id,
        action="archived",
        before=before,
        details=notes or "Arquivada sem eliminação.",
    )


def archive_suggested(proposal: ClassificationProposal, *, now: datetime | None = None) -> bool:
    reference = proposal.last_used_at or proposal.created_at
    if not reference:
        return False
    effective_now = now or datetime.now(UTC)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=UTC)
    return (
        proposal.active
        and proposal.usage_count == 0
        and reference <= effective_now - timedelta(days=30)
    )
