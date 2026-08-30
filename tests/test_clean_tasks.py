from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import (
    Document,
    Task,
    TaskDocument,
    TaskEmailOrigin,
    TaskHelpRequest,
    TaskHistory,
    TaskParticipant,
    ServiceDeskCategoryExecutor,
    Team,
    User,
    Vehicle,
    VehicleDocumentRecord,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
    WorkSubcategory,
    WorkshopPhasedProcess,
)
from app.services.users import create_user
from app.services.work_classification import (
    validate_work_hierarchy,
    work_hierarchy_context,
)


def test_clean_task_shortcut_opens_creation_form(authenticated_client):
    shortcut = authenticated_client.get("/v2-clean/tasks/new", follow_redirects=False)

    assert shortcut.status_code == 303
    assert shortcut.headers["location"] == "/v2-clean/tasks?create=1#new-task"

    form = authenticated_client.get(shortcut.headers["location"])
    assert form.status_code == 200
    if 'data-task-create-dialog' in form.text:
        assert 'data-create-model="request"' in form.text
        assert 'data-create-model="information"' in form.text
        assert 'data-create-model="task"' in form.text
        assert 'name="classification_version" value="3"' in form.text
        assert 'name="work_queue_id" required' in form.text
        assert 'name="work_department_id" required' in form.text
        assert 'name="work_category_id" required' in form.text
        assert 'name="work_subcategory_id"' in form.text
        assert 'name="classification_other_text"' in form.text
        assert 'data-requires-description=' in form.text
        assert 'action="/v2-clean/tasks"' in form.text
    else:
        assert 'id="new-task" open' in form.text
        assert 'name="work_queue_id" required' in form.text
        assert 'name="work_department_id" required' in form.text
        assert 'name="work_category_id"' in form.text
        assert 'name="work_subcategory_id"' in form.text


def test_clean_task_creation_models_have_distinct_persisted_contracts(
    authenticated_client,
    db_session,
):
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.scalar(
        select(WorkDepartment).where(WorkDepartment.queue_id == queue.id)
    )
    category = WorkCategory(
        department_id=department.id,
        code="functional_models",
        name="Modelos funcionais",
        active=True,
        requires_description=True,
    )
    db_session.add(category)
    db_session.flush()
    subcategory = WorkSubcategory(
        category_id=category.id,
        code="initial_triage",
        name="Triagem inicial",
        active=True,
    )
    db_session.add(subcategory)
    db_session.commit()
    hierarchy = {
        "classification_version": "3",
        "work_queue_id": str(queue.id),
        "work_department_id": str(department.id),
        "work_category_id": str(category.id),
        "work_subcategory_id": str(subcategory.id) if subcategory else "",
        "classification_other_text": "Contrato partilhado validado",
    }

    incomplete = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "record_type": "request",
            "title": "Modelo incompleto bloqueado",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
            "work_subcategory_id": str(subcategory.id),
        },
        follow_redirects=False,
    )
    assert incomplete.status_code == 303
    assert "missing_classification" in incomplete.headers["location"]
    assert db_session.scalar(
        select(Task).where(Task.title == "Modelo incompleto bloqueado")
    ) is None

    cases = (
        (
            "request",
            "Necessidade de apoio",
            {"description": "Destino: equipa operacional", "entity_type": "vehicle", "entity_id": "42"},
            "request",
        ),
        (
            "information",
            "Informação recebida",
            {"description": "Comunicação para registo", "entity_type": "process", "entity_id": "PROC-7"},
            "request_info",
        ),
        (
            "task",
            "Trabalho planeado",
            {"description": "Executar validação", "priority": "high", "due_on": "2026-09-05"},
            "operational_task",
        ),
    )
    for record_type, title, fields, expected_type in cases:
        response = authenticated_client.post(
            "/v2-clean/tasks",
            data={"record_type": record_type, "title": title, **hierarchy, **fields},
            follow_redirects=False,
        )
        assert response.status_code == 303, response.text
        task = db_session.scalar(select(Task).where(Task.title == title))
        assert task is not None
        assert task.task_type == expected_type
        assert task.work_queue_id == queue.id
        assert task.work_department_id == department.id
        assert task.work_category_id == category.id
        assert task.classification_other_text == "Contrato partilhado validado"

    request_task = db_session.scalar(select(Task).where(Task.title == "Necessidade de apoio"))
    information_task = db_session.scalar(select(Task).where(Task.title == "Informação recebida"))
    complete_task = db_session.scalar(select(Task).where(Task.title == "Trabalho planeado"))
    assert (request_task.entity_type, request_task.entity_id) == ("vehicle", "42")
    assert (information_task.entity_type, information_task.entity_id) == ("process", "PROC-7")
    assert information_task.due_on is None
    assert complete_task.priority == "high"
    assert complete_task.due_on == date(2026, 9, 5)

    update = authenticated_client.post(
        f"/v2-clean/tasks/{request_task.id}/update",
        data={
            "title": "Necessidade de apoio editada",
            "description": "Destino revisto",
            "status": request_task.status,
            "priority": "high",
            "workspace": "operational",
            **hierarchy,
        },
        follow_redirects=False,
    )
    assert update.status_code == 303
    db_session.refresh(request_task)
    assert request_task.task_type == "request"
    assert request_task.classification_other_text == "Contrato partilhado validado"


def test_task_classification_contract_rejects_cross_parent_and_tracks_requirement_changes(
    authenticated_client,
    db_session,
):
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department_false = WorkDepartment(
        queue_id=queue.id,
        code="contract_false",
        name="Contrato sem descrição",
        active=True,
        requires_description=False,
    )
    department_true = WorkDepartment(
        queue_id=queue.id,
        code="contract_true",
        name="Contrato com descrição",
        active=True,
        requires_description=False,
    )
    db_session.add_all([department_false, department_true])
    db_session.flush()
    category_false = WorkCategory(
        department_id=department_false.id,
        code="duplicate_false",
        name="Contratos e Reservas",
        active=True,
        requires_description=False,
    )
    category_true = WorkCategory(
        department_id=department_true.id,
        code="duplicate_true",
        name="Contratos e Reservas",
        active=True,
        requires_description=True,
    )
    db_session.add_all([category_false, category_true])
    db_session.flush()
    subcategory_false = WorkSubcategory(
        category_id=category_false.id,
        code="client_process_false",
        name="Processo com Cliente",
        active=True,
        requires_description=False,
    )
    subcategory_true = WorkSubcategory(
        category_id=category_true.id,
        code="client_process_true",
        name="Processo com Cliente",
        active=True,
        requires_description=False,
    )
    db_session.add_all([subcategory_false, subcategory_true])
    db_session.commit()

    contract = work_hierarchy_context(db_session)["work_hierarchy_contract"]
    assert contract["categories"][category_false.id] == {
        "id": category_false.id,
        "parent_id": department_false.id,
        "name": "Contratos e Reservas",
        "requires_description": False,
    }
    assert contract["categories"][category_true.id]["requires_description"] is True
    assert contract["subcategories"][subcategory_true.id]["parent_id"] == category_true.id

    forged = validate_work_hierarchy(
        db_session,
        queue_id=queue.id,
        department_id=department_false.id,
        category_id=category_false.id,
        subcategory_id=subcategory_true.id,
        other_text="forged client metadata cannot repair parentage",
        require_category=True,
    )
    assert forged is None

    create = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "record_type": "request",
            "title": "Contrato dinâmico",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department_false.id),
            "work_category_id": str(category_false.id),
            "work_subcategory_id": str(subcategory_false.id),
            "requires_description": "true",
        },
        follow_redirects=False,
    )
    assert create.status_code == 303
    assert "missing_classification" not in create.headers["location"]
    task = db_session.scalar(select(Task).where(Task.title == "Contrato dinâmico"))
    assert task is not None
    assert task.classification_other_text is None

    forged_update = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "workspace": "operational",
            "status": task.status,
            "title": "Não persiste parent forjado",
            "priority": task.priority,
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department_false.id),
            "work_category_id": str(category_false.id),
            "work_subcategory_id": str(subcategory_true.id),
            "classification_other_text": "presente mas inválido",
        },
        follow_redirects=False,
    )
    assert "missing_classification=1" in forged_update.headers["location"]
    db_session.refresh(task)
    assert task.title == "Contrato dinâmico"

    missing_required = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "workspace": "operational",
            "status": task.status,
            "title": "Não persiste sem descrição",
            "priority": task.priority,
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department_true.id),
            "work_category_id": str(category_true.id),
            "work_subcategory_id": str(subcategory_true.id),
            "requires_description": "false",
        },
        follow_redirects=False,
    )
    assert "missing_classification=1" in missing_required.headers["location"]

    valid_required = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "workspace": "operational",
            "status": task.status,
            "title": "Contrato com descrição",
            "priority": task.priority,
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department_true.id),
            "work_category_id": str(category_true.id),
            "work_subcategory_id": str(subcategory_true.id),
            "classification_other_text": "Descrição exigida pelo servidor",
        },
        follow_redirects=False,
    )
    assert valid_required.status_code == 303
    db_session.refresh(task)
    assert task.work_category_id == category_true.id
    assert task.classification_other_text == "Descrição exigida pelo servidor"

    back_to_optional = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "workspace": "operational",
            "status": task.status,
            "title": "Contrato novamente opcional",
            "priority": task.priority,
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department_false.id),
            "work_category_id": str(category_false.id),
            "work_subcategory_id": str(subcategory_false.id),
        },
        follow_redirects=False,
    )
    assert back_to_optional.status_code == 303
    db_session.refresh(task)
    assert task.work_category_id == category_false.id
    assert task.classification_other_text is None

    db_session.delete(task)
    db_session.commit()
    assert db_session.get(Task, task.id) is None


def test_clean_task_v3_attachment_is_persisted_and_fixture_is_cleaned(
    authenticated_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("app.web.router.document_archive_root", lambda: tmp_path)
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.scalar(
        select(WorkDepartment).where(WorkDepartment.queue_id == queue.id)
    )
    category = WorkCategory(
        department_id=department.id,
        code="v3_attachment",
        name="Anexo V3",
        active=True,
    )
    db_session.add(category)
    db_session.commit()
    response = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "record_type": "request",
            "title": "Fixture V3 com anexo",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
        },
        files={"attachments": ("fixture-v3.txt", b"synthetic-only", "text/plain")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    task = db_session.scalar(select(Task).where(Task.title == "Fixture V3 com anexo"))
    document = db_session.scalar(select(Document).where(Document.task_id == task.id))
    stored_path = Path(document.storage_path)
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"synthetic-only"

    stored_path.unlink()
    link = db_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task.id))
    db_session.delete(link)
    db_session.delete(document)
    db_session.delete(task)
    db_session.commit()
    assert not stored_path.exists()
    assert db_session.scalar(select(Task).where(Task.title == "Fixture V3 com anexo")) is None


def test_clean_task_update_round_trips_hierarchy_and_exclusive_assignment(
    authenticated_client,
    db_session,
):
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.scalar(
        select(WorkDepartment).where(WorkDepartment.queue_id == queue.id)
    )
    category = WorkCategory(
        department_id=department.id,
        code="update_round_trip",
        name="Atualização integral",
        active=True,
        requires_description=True,
    )
    db_session.add(category)
    db_session.flush()
    subcategory = WorkSubcategory(
        category_id=category.id,
        code="validated",
        name="Validada",
        active=True,
    )
    executor = db_session.scalar(
        select(User).where(User.email == "admin.tests@carfast.local")
    )
    team = db_session.scalar(select(Team).where(Team.code == "operations"))
    db_session.add_all(
        [
            subcategory,
            ServiceDeskCategoryExecutor(
                category_id=category.id,
                user_id=executor.id,
                active=True,
            ),
            ServiceDeskCategoryExecutor(
                category_id=category.id,
                team_id=team.id,
                active=True,
            ),
        ]
    )
    db_session.flush()
    task = Task(
        title="Antes do read-back",
        description="Descrição anterior",
        task_type="operational_task",
        status="new",
        priority="normal",
        work_queue_id=queue.id,
        work_department_id=department.id,
        work_category_id=category.id,
        work_subcategory_id=subcategory.id,
        classification_status="classified",
        created_by_id=executor.id,
    )
    db_session.add(task)
    db_session.commit()

    detail = authenticated_client.get(f"/v2-clean/tasks/{task.id}/detail")
    assert detail.status_code == 200
    assert 'name="classification_other_text"' in detail.text
    assert 'data-requires-description="true"' in detail.text

    incomplete = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "return_url": f"/v2-clean/tasks/{task.id}/detail",
            "post_action": "stay",
            "workspace": "operational",
            "status": "new",
            "title": "Não deve persistir",
            "description": "Sem descrição da classificação",
            "priority": "high",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
            "work_subcategory_id": str(subcategory.id),
        },
        follow_redirects=False,
    )
    assert incomplete.status_code == 303
    assert "missing_classification=1" in incomplete.headers["location"]
    db_session.refresh(task)
    assert task.title == "Antes do read-back"

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "return_url": f"/v2-clean/tasks/{task.id}/detail",
            "post_action": "stay",
            "workspace": "operational",
            "status": "new",
            "title": "Depois do read-back",
            "description": "Descrição atualizada",
            "priority": "high",
            "due_on": "2026-09-09",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
            "work_subcategory_id": str(subcategory.id),
            "classification_other_text": "Processo com Cliente",
            "assigned_to_id": str(executor.id),
            "assigned_team_id": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    db_session.refresh(task)
    assert (
        task.title,
        task.description,
        task.priority,
        task.due_on,
        task.work_queue_id,
        task.work_department_id,
        task.work_category_id,
        task.work_subcategory_id,
        task.assigned_to_id,
        task.team_id,
    ) == (
        "Depois do read-back",
        "Descrição atualizada",
        "high",
        date(2026, 9, 9),
        queue.id,
        department.id,
        category.id,
        subcategory.id,
        executor.id,
        None,
    )
    assert task.classification_other_text == "Processo com Cliente"

    forged_hierarchy = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "return_url": f"/v2-clean/tasks/{task.id}/detail",
            "post_action": "stay",
            "workspace": "operational",
            "status": "new",
            "title": "Hierarquia forjada",
            "description": task.description,
            "priority": task.priority,
            "classification_version": "3",
            "work_queue_id": str(queue.id + 99999),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
            "work_subcategory_id": str(subcategory.id),
            "classification_other_text": "Texto presente",
        },
        follow_redirects=False,
    )
    assert forged_hierarchy.status_code == 303
    assert "missing_classification=1" in forged_hierarchy.headers["location"]
    db_session.refresh(task)
    assert task.title == "Depois do read-back"

    rejected_update = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "return_url": f"/v2-clean/tasks/{task.id}/detail",
            "post_action": "stay",
            "workspace": "operational",
            "status": "new",
            "title": "Combinação inválida no detalhe",
            "description": task.description,
            "priority": task.priority,
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
            "work_subcategory_id": str(subcategory.id),
            "classification_other_text": "Processo com Cliente",
            "assigned_to_id": str(executor.id),
            "assigned_team_id": str(team.id),
        },
        follow_redirects=False,
    )
    assert rejected_update.status_code == 303
    assert "assignment_not_allowed" in rejected_update.headers["location"]
    db_session.refresh(task)
    assert task.title == "Depois do read-back"

    rejected = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "record_type": "task",
            "title": "Combinação rejeitada",
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "work_category_id": str(category.id),
            "classification_other_text": "Processo com Cliente",
            "assigned_to_id": str(executor.id),
            "assigned_team_id": str(team.id),
        },
        follow_redirects=False,
    )
    assert rejected.status_code == 303
    assert "assignment_not_allowed" in rejected.headers["location"]
    assert db_session.scalar(select(Task).where(Task.title == "Combinação rejeitada")) is None


def test_clean_task_creation_requires_three_classifications(authenticated_client):
    response = authenticated_client.post(
        "/v2-clean/tasks",
        data={"title": "Sem classificação", "classification_version": "2"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=missing_classification" in response.headers["location"]


def test_clean_task_creation_accepts_document_attachments(
    authenticated_client,
    db_session,
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr("app.web.router.document_archive_root", lambda: tmp_path)

    response = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "Tarefa com anexo",
            "classification_version": "2",
            "workspace": "operational",
            "category": "Operação",
            "subcategory": "Pedido",
        },
        files={"attachments": ("pedido.txt", b"conteudo", "text/plain")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    task = db_session.scalar(select(Task).where(Task.title == "Tarefa com anexo"))
    assert task is not None
    document = db_session.scalar(select(Document).where(Document.task_id == task.id))
    assert document is not None
    assert document.original_name == "pedido.txt"
    assert document.file_size == 8
    assert db_session.scalar(
        select(TaskDocument).where(
            TaskDocument.task_id == task.id,
            TaskDocument.document_id == document.id,
        )
    ) is not None


def test_clean_task_center_supports_explicit_sorting(authenticated_client, db_session):
    older = Task(
        title="Prazo distante",
        task_type="operational_task",
        category="Operação",
        subcategory="Pedido",
        status="new",
        priority="normal",
        due_on=date(2026, 9, 20),
    )
    sooner = Task(
        title="Prazo próximo",
        task_type="operational_task",
        category="Operação",
        subcategory="Pedido",
        status="new",
        priority="normal",
        due_on=date(2026, 8, 20),
    )
    db_session.add_all([older, sooner])
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=operational&sort=due_asc")

    assert page.status_code == 200
    assert page.text.index("Prazo próximo") < page.text.index("Prazo distante")


def test_clean_task_center_never_mixes_administration_into_operational_default(
    authenticated_client,
    db_session,
):
    operational = Task(
        title="Trabalho operacional visível",
        task_type="operational_task",
        category="Operação",
        status="new",
        priority="normal",
    )
    administrative = Task(
        title="Trabalho administrativo separado",
        task_type="administration_task",
        category="Administração",
        status="new",
        priority="normal",
    )
    db_session.add_all([operational, administrative])
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=all")

    assert page.status_code == 200
    assert "Trabalho operacional visível" in page.text
    assert "Trabalho administrativo separado" not in page.text
    assert '<option value="administration">' not in page.text
    assert "Todas autorizadas" not in page.text
    assert "Tarefas e Suporte" in page.text


def test_clean_task_center_creates_document_task_with_audit(authenticated_client, db_session):
    response = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "Confirmar classificação da fatura",
            "description": "Rever serviços relevantes.",
            "workspace": "workshop",
            "record_type": "task",
            "priority": "high",
            "plate": "bb-69-te",
            "category": "documentacao",
            "entity_type": "vehicle_document_record",
            "entity_id": "423",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    task = db_session.scalar(select(Task).where(Task.title == "Confirmar classificação da fatura"))
    assert task is not None
    assert "task_created=1" in response.headers["location"]
    assert f"open_task={task.id}" in response.headers["location"]
    assert response.headers["location"].endswith(f"#task-{task.id}")
    assert task.source == "v2_clean"
    assert task.task_type == "workshop_task"
    assert task.subcategory == "documentacao"
    assert task.plate == "BB-69-TE"
    assert task.entity_type == "vehicle_document_record"
    assert task.entity_id == "423"
    assert task.created_by_id is not None
    assert task.team_id is not None

    history = db_session.scalar(
        select(TaskHistory).where(TaskHistory.task_id == task.id, TaskHistory.field_name == "created")
    )
    assert history is not None
    assert history.user_id == task.created_by_id

    center = authenticated_client.get("/v2-clean/tasks?workspace=workshop")
    assert center.status_code == 200
    assert "Confirmar classificação da fatura" in center.text
    assert f'task-preview-{task.id}' in center.text
    assert f'/task-board/{task.id}' not in center.text


def test_clean_task_center_filters_due_today_and_shows_creation_date(
    authenticated_client,
    db_session,
):
    due_today = Task(
        title="Tarefa com prazo hoje",
        task_type="operational_task",
        source="v2_clean",
        category="Operação",
        subcategory="Validação",
        status="new",
        priority="normal",
        due_on=date.today(),
    )
    later = Task(
        title="Tarefa para outro dia",
        task_type="operational_task",
        source="v2_clean",
        status="new",
        priority="normal",
        due_on=date(2099, 1, 1),
    )
    db_session.add_all([due_today, later])
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=all&status=open&due=today")

    assert page.status_code == 200
    assert "Tarefa com prazo hoje" in page.text
    assert "Tarefa para outro dia" not in page.text
    assert "Criada em" in page.text
    assert 'name="work_category_id"' in page.text
    assert 'name="work_subcategory_id"' in page.text
    mine_page = authenticated_client.get("/v2-clean/tasks?workspace=mine")
    assert "Suporte solicitado" in mine_page.text


def test_clean_task_center_creates_problem_and_closes_it(authenticated_client, db_session):
    created = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "OCR com campos incorretos",
            "workspace": "workshop",
            "record_type": "problem",
            "plate": "BC-98-FA",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303

    problem = db_session.scalar(select(Task).where(Task.title == "OCR com campos incorretos"))
    assert problem is not None
    assert problem.subcategory == "problem"

    closed = authenticated_client.post(
        f"/v2-clean/tasks/{problem.id}/close",
        data={"return_url": "/v2-clean/tasks?kind=problem"},
        follow_redirects=False,
    )
    assert closed.status_code == 303
    db_session.refresh(problem)
    assert problem.status == "closed"
    assert problem.closed_at is not None

    reopened = authenticated_client.post(
        f"/v2-clean/tasks/{problem.id}/reopen",
        data={"return_url": "/v2-clean/tasks?kind=problem"},
        follow_redirects=False,
    )
    assert reopened.status_code == 303
    db_session.refresh(problem)
    assert problem.status == "new"
    assert problem.closed_at is None


def test_clean_task_center_rejects_external_return_url(authenticated_client, db_session):
    response = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "Retorno protegido",
            "workspace": "operational",
            "record_type": "task",
            "return_url": "https://example.com",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/tasks?workspace=operational")


def test_clean_task_center_limits_problems_to_workshop_and_updates_inline(authenticated_client, db_session):
    created = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "Registo operacional",
            "workspace": "operational",
            "record_type": "problem",
            "priority": "normal",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    task = db_session.scalar(select(Task).where(Task.title == "Registo operacional"))
    assert task is not None
    assert task.subcategory != "problem"

    updated = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "title": "Registo operacional revisto",
            "description": "Tratado inteiramente na experiência clean.",
            "status": "in_execution",
            "priority": "high",
            "due_on": "2026-08-03",
            "category": "operacao",
            "plate": "aa-11-bb",
            "return_url": "/v2-clean/tasks?workspace=operational",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.refresh(task)
    assert task.title == "Registo operacional revisto"
    assert task.status == "new"
    assert task.priority == "high"
    assert task.plate == "AA-11-BB"

    transitioned = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/transition",
        data={
            "status": "in_execution",
            "return_url": "/v2-clean/tasks?workspace=operational",
        },
        follow_redirects=False,
    )
    assert transitioned.status_code == 303
    db_session.refresh(task)
    assert task.status == "in_execution"
    assert task.due_on.isoformat() == "2026-08-03"
    assert db_session.scalar(
        select(TaskHistory).where(
            TaskHistory.task_id == task.id,
            TaskHistory.field_name == "status",
            TaskHistory.new_value == "in_execution",
        )
    )


def test_clean_task_center_prefills_document_context(authenticated_client, db_session):
    vehicle = Vehicle(plate="AA-11-BB", brand="PEUGEOT", model="PARTNER")
    db_session.add(vehicle)
    db_session.flush()
    record = VehicleDocumentRecord(
        vehicle_id=vehicle.id,
        source_record_type="archive",
        main_group="invoices",
        status="extracted",
        external_reference="FAC 2026/42",
        plate=vehicle.plate,
        supplier_name="Fornecedor Teste",
        raw_description="Mudança de óleo",
    )
    db_session.add(record)
    db_session.commit()

    response = authenticated_client.get(
        f"/v2-clean/tasks?workspace=workshop&record_type=problem"
        f"&entity_type=vehicle_document_record&entity_id={record.id}"
    )

    assert response.status_code == 200
    assert 'value="AA-11-BB"' in response.text
    assert "Problema: Faturas FAC 2026/42" in response.text
    assert "Fornecedor: Fornecedor Teste" in response.text
    assert "Descrição: Mudança de óleo" in response.text
    assert '<option value="">Selecionar fila</option>' in response.text
    assert 'name="work_department_id"' in response.text


def test_clean_task_center_supports_mine_participants_email_and_documents(authenticated_client, db_session):
    owner = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    participant = create_user(
        db_session,
        name="Pessoa de apoio",
        email="apoio.tasks@carfast.local",
        password="Secret123!",
        role_codes=["operator"],
    )
    document = Document(
        title="Pedido recebido",
        original_name="pedido.pdf",
        file_name="pedido.pdf",
        storage_provider="local",
        storage_path="/tmp/pedido.pdf",
        status="received",
    )
    db_session.add_all([participant, document])
    db_session.commit()

    created = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "Tratar pedido recebido por email",
            "workspace": "operational",
            "record_type": "task",
            "assigned_to_id": str(owner.id),
            "source": "email",
            "email_message_id": "<message-42@carfast.test>",
            "email_sender": "cliente@example.test",
            "email_subject": "Pedido 42",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    task = db_session.scalar(select(Task).where(Task.title == "Tratar pedido recebido por email"))
    assert task.assigned_to_id == owner.id
    assert db_session.scalar(select(TaskEmailOrigin).where(TaskEmailOrigin.task_id == task.id))

    linked = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/documents",
        data={"document_id": str(document.id), "return_url": "/v2-clean/tasks?workspace=mine"},
        follow_redirects=False,
    )
    assert linked.status_code == 303
    assert db_session.scalar(select(TaskDocument).where(TaskDocument.task_id == task.id))

    added = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/participants",
        data={
            "participant_user_id": str(participant.id),
            "role": "follower",
            "return_url": "/v2-clean/tasks?workspace=mine",
        },
        follow_redirects=False,
    )
    assert added.status_code == 303
    assert db_session.scalar(
        select(TaskParticipant).where(
            TaskParticipant.task_id == task.id,
            TaskParticipant.user_id == participant.id,
            TaskParticipant.role == "follower",
        )
    )

    help_response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_user_id": str(participant.id),
            "message": "Confirmar dados do pedido",
            "return_url": "/v2-clean/tasks?workspace=mine",
        },
        follow_redirects=False,
    )
    assert help_response.status_code == 303
    assert db_session.scalar(
        select(TaskHelpRequest).where(
            TaskHelpRequest.task_id == task.id,
            TaskHelpRequest.requested_user_id == participant.id,
            TaskHelpRequest.status == "pending",
        )
    )

    mine = authenticated_client.get("/v2-clean/tasks?workspace=mine&mine_kind=assigned")
    assert mine.status_code == 200
    assert task.title in mine.text
    assert "Pedido recebido" in mine.text


def test_workshop_record_action_opens_prefilled_task_form(authenticated_client, db_session):
    process = WorkshopPhasedProcess(
        process_type="maintenance",
        title="Revisão programada",
        creation_mode="operational",
        status="open",
        plate_snapshot="CC-22-DD",
        current_phase_code="diagnostico",
        priority="normal",
        origin="v2_clean",
        initial_observation="Ruído no motor",
    )
    db_session.add(process)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/records",
        data={"record_type": "problem", "phase": "diagnostico"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/v2-clean/tasks?")
    center = authenticated_client.get(response.headers["location"])
    assert center.status_code == 200
    assert "Problema:" in center.text
    assert "Diagnóstico Técnico" in center.text
    assert "Revisão programada" in center.text
    assert "Ruído no motor" in center.text
    assert 'value="CC-22-DD"' in center.text


def test_clean_task_can_move_to_audit_and_keeps_business_context(authenticated_client, db_session):
    created = authenticated_client.post(
        "/v2-clean/tasks",
        data={
            "title": "Auditar fatura",
            "workspace": "operational",
            "plate": "AA-22-CC",
            "reservation_number": "RES-42",
            "contract_number": "CONT-9",
            "invoice_number": "FAC/2026/88",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    task = db_session.scalar(select(Task).where(Task.title == "Auditar fatura"))
    assert task.reservation_number == "RES-42"
    assert task.contract_number == "CONT-9"
    assert task.invoice_number == "FAC/2026/88"

    updated = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "title": task.title,
            "workspace": "audit",
            "category": "documents",
            "subcategory": "invoice",
            "plate": task.plate,
            "reservation_number": task.reservation_number,
            "contract_number": task.contract_number,
            "invoice_number": task.invoice_number,
            "status": "new",
            "priority": "normal",
            "return_url": "/v2-clean/tasks?workspace=audit",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.refresh(task)
    assert task.task_type == "audit_task"
    assert task.category == "documents"
    assert task.subcategory == "invoice"

    audit_page = authenticated_client.get("/v2-clean/tasks?workspace=audit")
    assert audit_page.status_code == 200
    assert "Auditar fatura" not in audit_page.text
    assert "FAC/2026/88" not in audit_page.text


def test_clean_task_context_is_editable_without_changing_management(authenticated_client, db_session):
    task = Task(
        title="Confirmar documentação",
        description="Descrição inicial",
        source="v2_clean",
        task_type="operational_task",
        status="in_execution",
        priority="high",
        category="Documentação",
    )
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/context",
        data={
            "description": "Descrição revista no contexto.",
            "plate": "bc-27-ac",
            "reservation_number": "RES-17",
            "contract_number": "CONT-44",
            "invoice_number": "FAC/2026/91",
            "return_url": "/v2-clean/tasks?workspace=operational",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(task)
    assert task.description == "Descrição revista no contexto."
    assert task.plate == "BC-27-AC"
    assert task.reservation_number == "RES-17"
    assert task.contract_number == "CONT-44"
    assert task.invoice_number == "FAC/2026/91"
    assert task.status == "in_execution"
    assert task.priority == "high"
    assert task.category == "Documentação"

    page = authenticated_client.get(
        "/v2-clean/tasks?workspace=operational&nature=Documenta%C3%A7%C3%A3o"
    )
    assert page.status_code == 200
    assert "Confirmar documentação" in page.text
    assert ">Departamento<" in page.text
    assert "Tarefas e problemas" not in page.text


def test_clean_task_update_supports_save_and_save_close(authenticated_client, db_session):
    task = Task(
        title="Validar ações do drawer",
        source="v2_clean",
        task_type="operational_task",
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()

    common = {
        "title": task.title,
        "status": "in_execution",
        "priority": "normal",
        "return_url": "/v2-clean/tasks?workspace=all",
    }
    stay = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={**common, "post_action": "stay"},
        follow_redirects=False,
    )
    close = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={**common, "post_action": "close"},
        follow_redirects=False,
    )

    assert stay.status_code == 303
    assert f"open_task={task.id}" in stay.headers["location"]
    assert close.status_code == 303
    assert "open_task=" not in close.headers["location"]
    db_session.refresh(task)
    assert task.status == "new"


@pytest.mark.parametrize(
    "persisted_status",
    ("new", "in_execution", "waiting", "support_requested", "resolved", "closed", "cancelled"),
)
def test_clean_task_edit_preserves_every_persisted_status_and_ignores_forged_status(
    authenticated_client, db_session, persisted_status
):
    task = Task(
        title=f"Preservar {persisted_status}",
        source="v2_clean",
        task_type="operational_task",
        status=persisted_status,
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "title": f"{task.title} revista",
            "priority": "high",
            "status": "new" if persisted_status != "new" else "closed",
            "return_url": "/v2-clean/tasks?workspace=mine",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    persisted = db_session.get(Task, task.id)
    assert persisted.status == persisted_status
    assert persisted.priority == "high"


def test_clean_task_center_paginates_without_hiding_total(authenticated_client, db_session):
    tasks = [
        Task(
            title=f"Tarefa paginada {index:02d}",
            source="v2_clean",
            task_type="operational_task",
            status="new",
            priority="normal",
        )
        for index in range(51)
    ]
    db_session.add_all(tasks)
    db_session.commit()

    first_page = authenticated_client.get("/v2-clean/tasks?workspace=operational")
    second_page = authenticated_client.get(
        "/v2-clean/tasks?workspace=operational&page=2"
    )

    assert first_page.status_code == 200
    assert "51 registos nos filtros atuais" in first_page.text
    assert "Página 1 de 2" in first_page.text
    assert "Tarefa paginada 00" not in first_page.text
    assert second_page.status_code == 200
    assert "Página 2 de 2" in second_page.text
    assert "Tarefa paginada 00" in second_page.text


def test_clean_task_center_can_manage_compatible_historical_task(authenticated_client, db_session):
    task = Task(
        title="Tarefa histórica compatível",
        description="Criada antes da experiência Clean.",
        source="manual",
        task_type="operational_task",
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?workspace=operational")
    assert page.status_code == 200
    assert "Tarefa histórica compatível" in page.text

    updated = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/context",
        data={
            "description": "Tratada na experiência Clean.",
            "return_url": "/v2-clean/tasks?workspace=operational",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.refresh(task)
    assert task.description == "Tratada na experiência Clean."
    assert task.source == "manual"
