from sqlalchemy import select

from app.models import Task, TaskHistory


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
    assert f'/task-board/{task.id}' in center.text
    assert authenticated_client.get(f"/task-board/{task.id}").status_code == 200


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
