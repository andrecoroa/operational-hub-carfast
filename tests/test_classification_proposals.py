from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.models.admin import Permission, Role, RolePermission, User
from app.models.classification_proposals import (
    ClassificationProposal,
    ClassificationProposalAudit,
    ClassificationProposalUsage,
)
from app.models.email import EmailChannel, EmailThread
from app.models.evolution import EvolutionRecord
from app.models.tasks import Task, TaskHistory
from app.models.work_hierarchy import WorkCategory, WorkDepartment, WorkQueue, WorkSubcategory
from app.services.classification_proposals import (
    DuplicateProposalError,
    approve_proposal,
    archive_proposal,
    archive_suggested,
    associate_proposal,
    attach_selection_to_entity,
    create_proposal,
    merge_proposals,
    normalize_classification_name,
    observe_proposal,
    proposal_suggestions,
    reject_proposal,
    validate_proposal_selection,
)
from app.services.users import create_user


def _hierarchy(db):
    queue = db.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == queue.id,
            WorkDepartment.requires_description.is_(False),
        )
    )
    category = WorkCategory(
        department_id=department.id,
        code=f"test-{datetime.now(UTC).timestamp()}",
        name="Operação existente",
        active=True,
    )
    db.add(category)
    db.flush()
    subcategory = WorkSubcategory(
        category_id=category.id,
        code=f"test-sub-{category.id}",
        name="Validação existente",
        active=True,
    )
    db.add(subcategory)
    db.flush()
    return queue, department, category, subcategory


def _proposal(db, admin_id, department, *, name="Nova Operação", kind="category", category=None):
    return create_proposal(
        db,
        kind=kind,
        name=name,
        reason="A classificação atual não representa este processo.",
        department_id=department.id,
        category_id=category.id if category else None,
        proposed_by_id=admin_id,
        origin_module="service_desk",
        origin_url="/v2-clean/tasks?open_task=1",
    )


def _task(db, queue, department, category=None):
    task = Task(
        title="Registo provisório",
        status="new",
        source="test",
        task_type="operational_task",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id if category else None,
        classification_status="unclassified",
    )
    db.add(task)
    db.flush()
    return task


def test_normalization_ignores_case_spacing_and_accents():
    assert normalize_classification_name("  Gestão   de ÁGUA ") == "gestao de agua"


def test_creation_generates_immutable_code_evolution_and_duplicate_guard(db_session):
    queue, department, _category, _subcategory = _hierarchy(db_session)
    proposer_id = db_session.scalar(select(User.id).where(User.email.like("admin.tests@%")))

    first = _proposal(db_session, proposer_id, department, name="Gestão de Água")
    second = _proposal(db_session, proposer_id, department, name="Outra Operação")
    db_session.commit()

    assert first.provisional_code.startswith("PROP-CAT-")
    assert first.provisional_code != second.provisional_code
    original_code = first.provisional_code
    first.proposed_name = "Nome editado"
    db_session.commit()
    assert first.provisional_code == original_code
    evolution = db_session.get(EvolutionRecord, first.evolution_record_id)
    assert evolution.title == f"Classificação por validar · {first.provisional_code}"
    assert evolution.module == "classification_catalog"

    with pytest.raises(DuplicateProposalError):
        _proposal(db_session, proposer_id, department, name="  GESTÃO   DE ÁGUA ")


def test_suggestions_return_official_and_reusable_proposals(db_session):
    _queue, department, category, _subcategory = _hierarchy(db_session)
    proposal = _proposal(db_session, 1, department, name="Operação Existente Nova")
    db_session.commit()

    rows = proposal_suggestions(
        db_session,
        kind="category",
        name="operacao existente",
        department_id=department.id,
    )

    assert any(item["type"] == "official" and item["id"] == category.id for item in rows)
    assert any(item["type"] == "proposal" and item["id"] == proposal.id for item in rows)


def test_usage_priority_and_approval_rename_reclassify_task_and_email(db_session):
    queue, department, _category, _subcategory = _hierarchy(db_session)
    proposal = _proposal(db_session, 1, department)
    selection = validate_proposal_selection(
        db_session,
        department_id=department.id,
        official_category_id=None,
        category_proposal_id=proposal.id,
        subcategory_proposal_id=None,
    )
    tasks = [_task(db_session, queue, department) for _ in range(2)]
    for task in tasks:
        attach_selection_to_entity(
            db_session,
            entity=task,
            selection=selection,
            actor_user_id=1,
            module="service_desk",
        )
    channel = db_session.scalar(select(EmailChannel).limit(1))
    thread = EmailThread(
        channel_id=channel.id,
        subject="Pedido por email",
        work_queue_id=queue.id,
        work_department_id=department.id,
        classification_status="unclassified",
    )
    db_session.add(thread)
    db_session.flush()
    attach_selection_to_entity(
        db_session,
        entity=thread,
        selection=selection,
        actor_user_id=1,
        module="email",
    )
    db_session.commit()
    assert proposal.usage_count == 3
    assert db_session.get(EvolutionRecord, proposal.evolution_record_id).priority == "high"

    target = approve_proposal(
        db_session,
        proposal=proposal,
        actor_user_id=1,
        approved_name="Operação definitiva editada",
    )
    db_session.commit()

    assert target.code.startswith("CAT-")
    assert target.name == "Operação definitiva editada"
    assert proposal.status == "approved" and proposal.usage_count == 0
    for entity in [*tasks, thread]:
        db_session.refresh(entity)
        assert entity.work_category_id == target.id
        assert entity.provisional_category_id is None
        assert entity.classification_status == "classified"
    assert db_session.scalar(
        select(ClassificationProposalAudit).where(
            ClassificationProposalAudit.proposal_id == proposal.id,
            ClassificationProposalAudit.action == "approved",
        )
    )


def test_associate_subcategory_reclassifies_without_other_fallback(db_session):
    queue, department, category, existing_subcategory = _hierarchy(db_session)
    proposal = _proposal(
        db_session,
        1,
        department,
        name="Subcategoria provisória",
        kind="subcategory",
        category=category,
    )
    task = _task(db_session, queue, department, category)
    selection = validate_proposal_selection(
        db_session,
        department_id=department.id,
        official_category_id=category.id,
        category_proposal_id=None,
        subcategory_proposal_id=proposal.id,
    )
    attach_selection_to_entity(
        db_session,
        entity=task,
        selection=selection,
        actor_user_id=1,
        module="service_desk",
    )
    db_session.commit()

    associate_proposal(
        db_session,
        proposal=proposal,
        actor_user_id=1,
        target_id=existing_subcategory.id,
    )
    db_session.commit()

    assert task.work_subcategory_id == existing_subcategory.id
    assert task.provisional_subcategory_id is None
    assert task.classification_other_text is None
    assert proposal.status == "linked"


def test_merge_moves_all_usages_and_preserves_audit(db_session):
    queue, department, _category, _subcategory = _hierarchy(db_session)
    source = _proposal(db_session, 1, department, name="Origem")
    target = _proposal(db_session, 1, department, name="Destino")
    task = _task(db_session, queue, department)
    attach_selection_to_entity(
        db_session,
        entity=task,
        selection=validate_proposal_selection(
            db_session,
            department_id=department.id,
            official_category_id=None,
            category_proposal_id=source.id,
            subcategory_proposal_id=None,
        ),
        actor_user_id=1,
        module="service_desk",
    )
    db_session.commit()

    merge_proposals(
        db_session,
        source=source,
        target=target,
        actor_user_id=1,
        notes="Mesma necessidade operacional.",
    )
    db_session.commit()

    assert task.provisional_category_id == target.id
    assert source.status == "merged" and source.merged_into_proposal_id == target.id
    assert source.usage_count == 0 and target.usage_count == 1
    usage = db_session.scalar(
        select(ClassificationProposalUsage).where(
            ClassificationProposalUsage.proposal_id == target.id,
            ClassificationProposalUsage.entity_type == "task",
            ClassificationProposalUsage.entity_id == task.id,
            ClassificationProposalUsage.active.is_(True),
        )
    )
    assert usage


def test_reject_requires_reason_and_marks_manual_reclassification(db_session):
    queue, department, _category, _subcategory = _hierarchy(db_session)
    proposal = _proposal(db_session, 1, department)
    task = _task(db_session, queue, department)
    attach_selection_to_entity(
        db_session,
        entity=task,
        selection=validate_proposal_selection(
            db_session,
            department_id=department.id,
            official_category_id=None,
            category_proposal_id=proposal.id,
            subcategory_proposal_id=None,
        ),
        actor_user_id=1,
        module="service_desk",
    )
    db_session.commit()

    with pytest.raises(ValueError):
        reject_proposal(db_session, proposal=proposal, actor_user_id=1, reason="")
    reject_proposal(
        db_session,
        proposal=proposal,
        actor_user_id=1,
        reason="Escolher manualmente uma classificação oficial adequada.",
    )
    db_session.commit()

    assert task.classification_status == "reclassification_required"
    assert task.work_category_id is None
    assert task.category != "other"
    assert db_session.scalar(
        select(TaskHistory).where(
            TaskHistory.task_id == task.id,
            TaskHistory.new_value.like("rejected_reclassification_required%"),
        )
    )


def test_observation_and_archive_suggestion_never_delete(db_session):
    _queue, department, _category, _subcategory = _hierarchy(db_session)
    proposal = _proposal(db_session, 1, department)
    db_session.flush()
    observe_proposal(
        db_session,
        proposal=proposal,
        actor_user_id=1,
        notes="Recolher mais utilizações.",
    )
    proposal.created_at = datetime.now(UTC) - timedelta(days=31)
    db_session.commit()

    assert proposal.status == "observation"
    assert archive_suggested(proposal)
    archive_proposal(db_session, proposal=proposal, actor_user_id=1)
    db_session.commit()
    assert db_session.get(ClassificationProposal, proposal.id).status == "archived"


def test_decision_rolls_back_catalog_and_reclassification_together(db_session):
    queue, department, _category, _subcategory = _hierarchy(db_session)
    proposal = _proposal(db_session, 1, department)
    task = _task(db_session, queue, department)
    attach_selection_to_entity(
        db_session,
        entity=task,
        selection=validate_proposal_selection(
            db_session,
            department_id=department.id,
            official_category_id=None,
            category_proposal_id=proposal.id,
            subcategory_proposal_id=None,
        ),
        actor_user_id=1,
        module="service_desk",
    )
    db_session.commit()
    proposal_id, task_id = proposal.id, task.id

    approve_proposal(db_session, proposal=proposal, actor_user_id=1)
    db_session.rollback()

    proposal = db_session.get(ClassificationProposal, proposal_id)
    task = db_session.get(Task, task_id)
    assert proposal.status == "pending" and proposal.active
    assert task.provisional_category_id == proposal.id
    assert task.work_category_id is None


def _login(client, email, password):
    response = client.post(
        "/login", data={"email": email, "password": password}, follow_redirects=False
    )
    assert response.status_code == 303
    client.post("/change-notice", data={"next_url": "/v2-clean"}, follow_redirects=False)


def test_server_authorization_separates_propose_and_provisional_use(client, db_session):
    _queue, department, _category, _subcategory = _hierarchy(db_session)
    role = Role(code="classification_limited", name="Classificação limitada", active=True)
    db_session.add(role)
    db_session.flush()
    for code in {"dashboard.read", "tasks.write", "classification.active.use"}:
        permission = db_session.scalar(select(Permission).where(Permission.code == code))
        db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    user = create_user(
        db_session,
        name="Utilizador Classificação",
        email="classification.tests@carfast.local",
        password="Secret123!",
        role_codes=[role.code],
        organizational_unit_codes=["carfast"],
    )
    db_session.commit()
    _login(client, user.email, "Secret123!")
    payload = {
        "kind": "category",
        "name": "Proposta sem permissão",
        "reason": "Teste de autorização no servidor.",
        "department_id": department.id,
        "origin_module": "service_desk",
    }
    denied = client.post("/api/classification-proposals", json=payload, follow_redirects=False)
    assert (denied.status_code, denied.headers.get("location")) == (403, None)

    permission = db_session.scalar(
        select(Permission).where(Permission.code == "classification.propose")
    )
    db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db_session.commit()
    created = client.post("/api/classification-proposals", json=payload)
    assert created.status_code == 201
    proposal_id = created.json()["id"]

    task_payload = {
        "title": "Uso provisório sem permissão",
        "status": "new",
        "work_queue_id": department.queue_id,
        "work_department_id": department.id,
        "provisional_category_id": proposal_id,
    }
    assert client.post("/api/tasks", json=task_payload).status_code == 403
    permission = db_session.scalar(
        select(Permission).where(Permission.code == "classification.provisional.use")
    )
    db_session.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db_session.commit()
    response = client.post("/api/tasks", json=task_payload)
    assert response.status_code == 201
    assert response.json()["classification_status"] == "provisional"


def test_admin_and_operational_ui_expose_provisional_workflow(authenticated_client, db_session):
    _queue, department, _category, _subcategory = _hierarchy(db_session)
    _proposal(db_session, 1, department, name="Proposta UI A")
    _proposal(db_session, 1, department, name="Proposta UI B")
    db_session.commit()
    task_page = authenticated_client.get("/v2-clean/tasks?create=1")
    assert task_page.status_code == 200
    assert "+ Propor nova categoria" in task_page.text
    assert "classification_proposals.js" in task_page.text

    admin_page = authenticated_client.get("/v2-clean/admin/work-classification?view=proposals")
    assert admin_page.status_code == 200
    assert "Propostas de Categoria/Subcategoria" in admin_page.text
    assert "Fundir noutra proposta" in admin_page.text
