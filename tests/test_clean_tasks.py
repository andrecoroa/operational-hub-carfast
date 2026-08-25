from datetime import date

from sqlalchemy import select

from app.models import (
    Document,
    Task,
    TaskDocument,
    TaskEmailOrigin,
    TaskHelpRequest,
    TaskHistory,
    TaskParticipant,
    User,
    Vehicle,
    VehicleDocumentRecord,
    WorkshopPhasedProcess,
)
from app.services.users import create_user


def test_clean_task_shortcut_opens_creation_form(authenticated_client):
    shortcut = authenticated_client.get("/v2-clean/tasks/new", follow_redirects=False)

    assert shortcut.status_code == 303
    assert shortcut.headers["location"] == "/v2-clean/tasks?create=1#new-task"

    form = authenticated_client.get(shortcut.headers["location"])
    assert form.status_code == 200
    assert 'id="new-task" open' in form.text
    assert '<option value="">Selecionar fila</option>' in form.text
    assert 'name="work_queue_id" required' in form.text
    assert 'name="work_department_id" required' in form.text
    assert 'name="work_category_id"' in form.text
    assert 'name="work_subcategory_id"' in form.text


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
    assert response.headers["location"].endswith(f"task_created=1&task_id={task.id}")
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
    assert task.status == "in_execution"
    assert task.priority == "high"
    assert task.plate == "AA-11-BB"
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
    assert "Auditar fatura" in audit_page.text
    assert "FAC/2026/88" in audit_page.text


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
