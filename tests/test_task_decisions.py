from pathlib import Path

from sqlalchemy import select

import app.web.router as task_router
from app.models import (
    Permission,
    RolePermission,
    Task,
    TaskDecision,
    TaskHistory,
    TaskNotification,
    User,
    UserRole,
)
from app.services.users import create_user


MIGRATION = (
    Path(__file__).parents[1]
    / "migrations/versions/fffaef5a6b7c_add_task_decisions.py"
).read_text(encoding="utf-8")


def _actor(db):
    return db.scalar(select(User).where(User.email == "admin.tests@carfast.local"))


def _task(db, actor):
    item = Task(
        title="Decisão controlada",
        task_type="operational_task",
        status="new",
        priority="normal",
        created_by_id=actor.id,
        assigned_to_id=actor.id,
        assignment_mode="manual",
        assignment_state="assigned_user",
    )
    db.add(item)
    db.commit()
    return item


def _remove_permission(db, user, code):
    role_ids = select(UserRole.role_id).where(UserRole.user_id == user.id)
    permission_id = db.scalar(select(Permission.id).where(Permission.code == code))
    links = db.scalars(
        select(RolePermission).where(
            RolePermission.role_id.in_(role_ids),
            RolePermission.permission_id == permission_id,
        )
    ).all()
    for link in links:
        db.delete(link)
    db.commit()


def _grant_permissions(db, user, *codes):
    role_id = db.scalar(select(UserRole.role_id).where(UserRole.user_id == user.id))
    for code in codes:
        permission_id = db.scalar(select(Permission.id).where(Permission.code == code))
        db.add(RolePermission(role_id=role_id, permission_id=permission_id))
    db.commit()


def test_decision_migration_is_additive_and_does_not_grant_roles() -> None:
    assert 'op.create_table(' in MIGRATION
    assert '"task_decisions"' in MIGRATION
    assert "role_permissions" not in MIGRATION
    assert "op.drop_column(\"tasks\"" not in MIGRATION


def test_request_and_approve_decision_preserve_owner_and_audit(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "task_decisions_enabled", True)
    actor = _actor(db_session)
    _grant_permissions(
        db_session, actor, "tasks.request_decision", "tasks.resolve_decision"
    )
    task = _task(db_session, actor)

    requested = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/decisions",
        data={
            "decider_id": actor.id,
            "decision_needed": "Aprovar valor",
            "recommendation": "Aprovar",
            "impact_value": "1 000 EUR",
            "return_url": "/v2-clean/tasks?task_scope_view=mine",
        },
        follow_redirects=False,
    )

    assert requested.status_code == 303
    db_session.refresh(task)
    item = db_session.scalar(select(TaskDecision).where(TaskDecision.task_id == task.id))
    assert task.status == "waiting_decision"
    assert task.assigned_to_id == actor.id
    assert item.previous_task_status == "new"
    assert db_session.scalar(
        select(TaskHistory.id).where(
            TaskHistory.task_id == task.id,
            TaskHistory.field_name == "decision_requested",
        )
    )
    assert db_session.scalar(
        select(TaskNotification.id).where(
            TaskNotification.task_id == task.id,
            TaskNotification.event_type == "decision_requested",
        )
    )

    resolved = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/decisions/{item.id}",
        data={
            "action": "approve",
            "comment": "Aprovado",
            "return_url": "/v2-clean/tasks?decision=mine",
        },
        follow_redirects=False,
    )

    assert resolved.status_code == 303
    db_session.refresh(task)
    db_session.refresh(item)
    assert item.status == "approved"
    assert task.status == "in_execution"
    assert task.assigned_to_id == actor.id


def test_decision_request_and_resolution_fail_closed_without_permissions(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "task_decisions_enabled", True)
    actor = _actor(db_session)
    _grant_permissions(db_session, actor, "tasks.resolve_decision")
    task = _task(db_session, actor)
    _remove_permission(db_session, actor, "tasks.request_decision")

    denied = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/decisions",
        data={
            "decider_id": actor.id,
            "decision_needed": "Decidir",
            "recommendation": "Sim",
            "impact_value": "Baixo",
        },
        follow_redirects=False,
    )

    assert denied.status_code == 303
    db_session.refresh(task)
    assert task.status == "new"
    assert db_session.scalar(select(TaskDecision.id)) is None


def test_decision_target_must_be_active_explicit_resolver(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "task_decisions_enabled", True)
    actor = _actor(db_session)
    _grant_permissions(db_session, actor, "tasks.request_decision")
    target = create_user(
        db_session,
        name="Sem permissão de decisão",
        email="no.decision@carfast.local",
        password="Secret123!",
        role_codes=["viewer"],
        organizational_unit_codes=["carfast"],
    )
    task = _task(db_session, actor)

    denied = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/decisions",
        data={
            "decider_id": target.id,
            "decision_needed": "Decidir",
            "recommendation": "Sim",
            "impact_value": "Baixo",
        },
        follow_redirects=False,
    )

    assert denied.status_code == 303
    assert db_session.scalar(select(TaskDecision.id)) is None


def test_decisions_for_me_filter_and_information_request(
    authenticated_client, db_session, monkeypatch
) -> None:
    monkeypatch.setattr(task_router.settings, "task_decisions_enabled", True)
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = _actor(db_session)
    _grant_permissions(
        db_session, actor, "tasks.request_decision", "tasks.resolve_decision"
    )
    task = _task(db_session, actor)
    item = TaskDecision(
        task_id=task.id,
        requested_by_id=actor.id,
        decider_id=actor.id,
        decision_needed="Escolher opção",
        recommendation="Opção A",
        impact_value="Sem custo",
        previous_task_status="new",
        status="pending",
    )
    task.status = "waiting_decision"
    db_session.add(item)
    db_session.commit()

    page = authenticated_client.get(
        "/v2-clean/tasks?decision=mine&task_scope_view=mine&status=open"
    )
    assert page.status_code == 200
    assert "Decisões para mim" in page.text
    assert "Decisão controlada" in page.text

    missing_detail = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/decisions/{item.id}",
        data={"action": "request_information", "comment": ""},
        follow_redirects=False,
    )
    assert missing_detail.status_code == 303
    db_session.refresh(item)
    assert item.status == "pending"

    requested = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/decisions/{item.id}",
        data={"action": "request_information", "comment": "Falta orçamento"},
        follow_redirects=False,
    )
    assert requested.status_code == 303
    db_session.refresh(item)
    db_session.refresh(task)
    assert item.status == "information_requested"
    assert task.status == "waiting_decision"


def test_decision_feature_is_off_by_default(authenticated_client, db_session) -> None:
    actor = _actor(db_session)
    task = _task(db_session, actor)
    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/decisions",
        data={
            "decider_id": actor.id,
            "decision_needed": "Decidir",
            "recommendation": "Sim",
            "impact_value": "Baixo",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert db_session.scalar(select(TaskDecision.id)) is None
