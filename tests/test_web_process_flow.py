from sqlalchemy import select

from app.models.tasks import Task, TaskHistory


def test_web_task_process_creates_task_and_audit_history(authenticated_client, db_session):
    form = authenticated_client.get("/task-board/new")
    assert form.status_code == 200
    assert "Nova tarefa" in form.text

    created = authenticated_client.post(
        "/task-board/new",
        data={
            "title": "Validar processo automatico",
            "task_type": "task",
            "category": "operations",
            "source": "manual",
            "priority": "high",
            "customer_name": "Cliente Teste",
            "customer_email": "cliente.teste@example.com",
            "plate": "AA 11 AA",
            "description": "Teste automatico do processo de criacao de tarefas.",
        },
        follow_redirects=False,
    )

    assert created.status_code == 303
    assert created.headers["location"] == "/task-board/manage?created=1"

    task = db_session.scalar(select(Task).where(Task.title == "Validar processo automatico"))
    assert task is not None
    assert task.status == "new"
    assert task.priority == "high"
    assert task.source == "manual"
    assert task.category == "operations"
    assert task.customer_name == "Cliente Teste"
    assert task.customer_email == "cliente.teste@example.com"
    assert task.plate == "AA11AA"
    assert task.created_by_id is not None

    history = db_session.scalar(select(TaskHistory).where(TaskHistory.task_id == task.id))
    assert history is not None
    assert history.user_id == task.created_by_id
    assert history.field_name == "status"
    assert history.new_value == "new"

    detail = authenticated_client.get(f"/task-board/{task.id}")
    assert detail.status_code == 200
    assert "Validar processo automatico" in detail.text
