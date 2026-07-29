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
    assert 'value="documentacao"' in response.text


def test_clean_task_center_supports_mine_participants_email_and_documents(authenticated_client, db_session):
    owner = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    participant = User(
        name="Pessoa de apoio",
        email="apoio.tasks@carfast.local",
        password_hash="not-used",
        active=True,
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
