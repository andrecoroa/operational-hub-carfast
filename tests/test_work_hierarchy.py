from sqlalchemy import select

from app.models import (
    EmailMessage,
    EmailThread,
    Role,
    RoleWorkScope,
    Task,
    User,
    WorkCategory,
    WorkDepartment,
    WorkQueue,
    WorkSubcategory,
)
from app.services.email_postmark import ingest_inbound
from app.services.work_classification import (
    user_work_scope_allows,
    validate_work_hierarchy,
)


def _queue_department(db, queue_code: str, department_code: str):
    queue = db.scalar(select(WorkQueue).where(WorkQueue.code == queue_code))
    department = db.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == queue.id,
            WorkDepartment.code == department_code,
        )
    )
    return queue, department


def test_hierarchy_enforces_active_parent_chain_and_other_description(db_session):
    queue, operations = _queue_department(db_session, "tasks_support", "operations")
    _, other = _queue_department(db_session, "tasks_support", "other")
    category = WorkCategory(
        department_id=operations.id,
        code="logistics",
        name="Logística",
        active=True,
    )
    db_session.add(category)
    db_session.flush()
    subcategory = WorkSubcategory(
        category_id=category.id,
        code="transfers",
        name="Transfers",
        active=True,
    )
    db_session.add(subcategory)
    db_session.commit()

    valid = validate_work_hierarchy(
        db_session,
        queue_id=queue.id,
        department_id=operations.id,
        category_id=category.id,
        subcategory_id=subcategory.id,
    )
    assert valid is not None and valid.status == "classified"
    assert validate_work_hierarchy(
        db_session,
        queue_id=queue.id,
        department_id=other.id,
    ) is None
    review = validate_work_hierarchy(
        db_session,
        queue_id=queue.id,
        department_id=other.id,
        other_text="Departamento ainda não parametrizado",
    )
    assert review is not None and review.status == "review"

    subcategory.active = False
    db_session.commit()
    assert validate_work_hierarchy(
        db_session,
        queue_id=queue.id,
        department_id=operations.id,
        category_id=category.id,
        subcategory_id=subcategory.id,
    ) is None


def test_task_v3_classification_preserves_legacy_fields(authenticated_client, db_session):
    queue, department = _queue_department(db_session, "tasks_support", "fleet")
    task = Task(
        title="Classificação anterior",
        task_type="operational_task",
        category="Oficina",
        subcategory="Diagnóstico",
        legacy_classification="Oficina / Diagnóstico",
        status="new",
        priority="normal",
    )
    db_session.add(task)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "title": task.title,
            "classification_version": "3",
            "work_queue_id": str(queue.id),
            "work_department_id": str(department.id),
            "status": "new",
            "priority": "normal",
            "return_url": "/v2-clean/tasks",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.refresh(task)
    assert task.work_queue_id == queue.id
    assert task.work_department_id == department.id
    assert task.classification_status == "classified"
    assert task.category == "Oficina"
    assert task.subcategory == "Diagnóstico"
    assert task.legacy_classification == "Oficina / Diagnóstico"


def test_role_scope_can_limit_actions_to_one_department(db_session):
    queue, operations = _queue_department(db_session, "tasks_support", "operations")
    _, fleet = _queue_department(db_session, "tasks_support", "fleet")
    admin_role = db_session.scalar(select(Role).where(Role.code == "admin"))
    user = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    db_session.add(
        RoleWorkScope(
            role_id=admin_role.id,
            queue_id=queue.id,
            department_id=operations.id,
            can_read=True,
            can_create=True,
        )
    )
    db_session.commit()

    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=queue.id,
        department_id=operations.id,
        category_id=None,
        subcategory_id=None,
        action="create",
    ) is True
    assert user_work_scope_allows(
        db_session,
        user_id=user.id,
        queue_id=queue.id,
        department_id=fleet.id,
        category_id=None,
        subcategory_id=None,
        action="create",
    ) is False


def test_new_email_can_be_saved_as_draft(authenticated_client, db_session, monkeypatch):
    from sqlalchemy.orm import sessionmaker

    import app.web.email as email_web

    monkeypatch.setattr(
        email_web,
        "SessionLocal",
        sessionmaker(bind=db_session.get_bind(), autoflush=False, autocommit=False),
    )
    inbound, _ = ingest_inbound(
        db_session,
        {
            "MessageID": "hierarchy-email-channel",
            "From": "cliente@example.com",
            "To": "hub@carfast.pt",
            "Subject": "Criar caixa",
            "TextBody": "Mensagem de entrada",
            "Headers": [],
            "Attachments": [],
        },
    )

    response = authenticated_client.post(
        "/v2-clean/email/new",
        data={
            "channel_id": str(inbound.channel_id),
            "recipients": "destinatario@example.com",
            "subject": "Mensagem nova",
            "body": "Corpo preparado no Hub.",
            "submit": "draft",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    thread = db_session.scalar(
        select(EmailThread).where(EmailThread.subject == "Mensagem nova")
    )
    message = db_session.scalar(
        select(EmailMessage).where(EmailMessage.thread_id == thread.id)
    )
    assert thread.status == "in_progress"
    assert message.direction == "outbound"
    assert message.state == "draft"
    assert message.recipients_json == [{"Email": "destinatario@example.com"}]
