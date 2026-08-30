"""Contract-first acceptance tests for the approved Task Center v3 tranche."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select
import pytest
import app.web.router as task_router

from app.models import (
    Task,
    TaskComment,
    TaskHelpRequest,
    TaskHistory,
    TaskSlaEvent,
    Team,
    TeamMember,
    User,
    WorkDepartment,
    WorkQueue,
)


RETURN_CONTEXT = (
    "/v2-clean/tasks?queue=tasks_support&view=team&status=open"
    "&risk=all&sort=due_on&direction=asc#task-42"
)
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/fff59a0b1c2d_add_transactional_task_support.py"
).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _enable_v3_surface(monkeypatch):
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)


def _new_task(db_session, *, title: str = "Contrato v3") -> Task:
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    queue = db_session.scalar(select(WorkQueue).where(WorkQueue.code == "tasks_support"))
    department = db_session.scalar(
        select(WorkDepartment).where(
            WorkDepartment.queue_id == queue.id,
            WorkDepartment.code == "operations",
        )
    )
    task = Task(
        title=title,
        task_type="operational_task",
        category="Documentação",
        status="in_execution",
        priority="high",
        created_by_id=actor.id,
        assigned_to_id=actor.id,
        due_on=date.today() + timedelta(days=2),
        work_queue_id=queue.id,
        work_department_id=department.id,
        classification_status="classified",
    )
    db_session.add(task)
    db_session.commit()
    return task


def _support_team_with_eligible_member(db_session) -> Team:
    actor = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    team = db_session.scalar(select(Team).where(Team.code == "support"))
    existing = db_session.scalar(
        select(TeamMember).where(
            TeamMember.team_id == team.id,
            TeamMember.user_id == actor.id,
        )
    )
    if not existing:
        db_session.add(TeamMember(team_id=team.id, user_id=actor.id))
        db_session.commit()
    return team


def test_support_migration_fails_before_ddl_on_legacy_inconsistencies() -> None:
    assert "invalid_targets" in MIGRATION
    assert "duplicate_active_tasks" in MIGRATION
    assert MIGRATION.index("Task support migration preflight failed") < MIGRATION.index(
        'batch_op.add_column(sa.Column("due_at"'
    )


def test_queue_and_view_contract_rejects_aggregation_and_silent_fallback(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Visível na fila operacional")

    default = authenticated_client.get("/v2-clean/tasks")
    aggregated = authenticated_client.get("/v2-clean/tasks?queue=all&view=mine")
    invalid_view = authenticated_client.get(
        "/v2-clean/tasks?queue=tasks_support&view=unknown"
    )

    assert default.status_code == 200
    assert task.title in default.text
    assert 'data-active-queue="tasks_support"' in default.text
    assert 'data-active-view="mine"' in default.text
    assert aggregated.status_code in {400, 422}
    assert invalid_view.status_code in {400, 422}


def test_incompatible_team_to_mine_and_closed_risk_filters_fail_closed(
    authenticated_client,
) -> None:
    team_to_mine = authenticated_client.get(
        "/v2-clean/tasks?queue=tasks_support&view=mine&preset=team"
    )
    closed_at_risk = authenticated_client.get(
        "/v2-clean/tasks?queue=tasks_support&view=mine&status=closed&risk=at_risk"
    )

    assert team_to_mine.status_code in {400, 422}
    assert closed_at_risk.status_code in {400, 422}


def test_sort_contract_is_explicit_and_reflected_in_the_surface(
    authenticated_client, db_session
) -> None:
    _new_task(db_session, title="Ordenação contratual")
    page = authenticated_client.get(
        "/v2-clean/tasks?queue=tasks_support&view=mine&status=open"
        "&sort=due_on&direction=desc"
    )

    assert page.status_code == 200
    assert 'data-sort-criterion="due_on"' in page.text
    assert 'data-sort-direction="desc"' in page.text
    assert "Prazo" in page.text and "descendente" in page.text.lower()


def test_empty_comment_is_rejected_without_state_or_audit_side_effect(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Comentário vazio")
    before_status = task.status
    before_comments = db_session.scalar(
        select(func.count(TaskComment.id)).where(TaskComment.task_id == task.id)
    )

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/comments",
        data={"comment": "   ", "return_url": RETURN_CONTEXT},
        follow_redirects=False,
    )

    assert response.status_code in {400, 422} or (
        response.status_code == 303
        and any(flag in response.headers["location"] for flag in ("comment_required", "invalid_comment", "error="))
    )
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == before_status
    assert db_session.scalar(
        select(func.count(TaskComment.id)).where(TaskComment.task_id == task.id)
    ) == before_comments


def test_support_request_is_transactional_audited_and_preserves_return_context(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Suporte transacional")
    support_team = _support_team_with_eligible_member(db_session)

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_target": f"team:{support_team.id}",
            "message": "Revisão técnica necessária",
            "due_at": (date.today() + timedelta(days=1)).isoformat(),
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    query = parse_qs(location.query)
    assert {
        key: query.get(key)
        for key in ("queue", "view", "status", "risk", "sort", "direction")
    } == {
        "queue": ["tasks_support"],
        "view": ["team"],
        "status": ["open"],
        "risk": ["all"],
        "sort": ["due_on"],
        "direction": ["asc"],
    }
    assert location.fragment.startswith("task-")
    db_session.expire_all()
    persisted = db_session.get(Task, task.id)
    request = db_session.scalar(
        select(TaskHelpRequest).where(TaskHelpRequest.task_id == task.id)
    )
    assert persisted.status == "support_requested"
    assert request.previous_task_status == "in_execution"
    assert request.requested_team_id == support_team.id
    assert request.requested_user_id is None
    assert request.due_at is not None
    assert db_session.scalar(
        select(TaskHistory).where(
            TaskHistory.task_id == task.id,
            TaskHistory.field_name == "status",
            TaskHistory.old_value == "in_execution",
            TaskHistory.new_value == "support_requested",
        )
    )


def test_support_resolution_requires_explicit_bounded_return_and_fails_closed(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Retorno explícito do suporte")
    support_team = _support_team_with_eligible_member(db_session)
    requested = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_target": f"team:{support_team.id}",
            "message": "Apoio técnico",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )
    assert requested.status_code == 303
    item = db_session.scalar(
        select(TaskHelpRequest).where(TaskHelpRequest.task_id == task.id)
    )

    for next_status in ("", "planned", "support_requested", "closed"):
        rejected = authenticated_client.post(
            f"/v2-clean/tasks/{task.id}/help/{item.id}",
            data={
                "response": "responded",
                "comment": "Tentativa inválida",
                "next_status": next_status,
                "return_url": RETURN_CONTEXT,
            },
            follow_redirects=False,
        )
        assert rejected.status_code == 303
        assert "error=" in rejected.headers["location"]
        db_session.expire_all()
        assert db_session.get(Task, task.id).status == "support_requested"
        assert db_session.get(TaskHelpRequest, item.id).status == "pending"

    page = authenticated_client.get(RETURN_CONTEXT.split("#", 1)[0])
    assert page.status_code == 200
    assert "Após fechar o pedido" in page.text
    assert 'value="in_execution"' in page.text
    assert 'value="waiting"' in page.text

    completed = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help/{item.id}",
        data={
            "response": "responded",
            "comment": "Apoio concluído",
            "next_status": "waiting",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )
    assert completed.status_code == 303
    assert completed.headers["location"].endswith(f"#task-{task.id}")
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == "waiting"
    assert db_session.get(TaskHelpRequest, item.id).status == "completed"


def test_support_cancellation_explicitly_restores_captured_state(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Cancelar suporte explicitamente")
    support_team = _support_team_with_eligible_member(db_session)
    authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_target": f"team:{support_team.id}",
            "message": "Pedido cancelável",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )
    item = db_session.scalar(
        select(TaskHelpRequest).where(TaskHelpRequest.task_id == task.id)
    )

    cancelled = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help/{item.id}",
        data={
            "response": "cancelled",
            "next_status": "in_execution",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )

    assert cancelled.status_code == 303
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == "in_execution"
    assert db_session.get(TaskHelpRequest, item.id).status == "cancelled"


def test_support_return_from_resolved_reopens_sla_consistently(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Retomar tarefa resolvida após suporte")
    task.status = "resolved"
    task.resolved_at = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    task.sla_resolution_minutes = 240
    db_session.commit()
    support_team = _support_team_with_eligible_member(db_session)
    authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_target": f"team:{support_team.id}",
            "message": "Confirmar reabertura",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )
    item = db_session.scalar(
        select(TaskHelpRequest).where(TaskHelpRequest.task_id == task.id)
    )

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help/{item.id}",
        data={
            "response": "responded",
            "comment": "Retomar execução",
            "next_status": "in_execution",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    persisted = db_session.get(Task, task.id)
    assert persisted.status == "in_execution"
    assert persisted.resolved_at is None
    assert persisted.sla_paused_at is None
    assert persisted.resolution_due_at is not None
    assert db_session.scalar(
        select(TaskSlaEvent.id).where(
            TaskSlaEvent.task_id == task.id,
            TaskSlaEvent.action == "reopened",
        )
    )


@pytest.mark.parametrize("archived_status", ("closed", "cancelled", "no_action_needed"))
def test_archived_task_cannot_start_support(
    authenticated_client, db_session, archived_status
) -> None:
    task = _new_task(db_session, title=f"Sem suporte em {archived_status}")
    task.status = archived_status
    task.closed_at = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    db_session.commit()
    support_team = _support_team_with_eligible_member(db_session)

    page = authenticated_client.get(
        "/v2-clean/tasks?queue=tasks_support&status=closed&view=mine"
    )
    assert page.status_code == 200
    assert f'"{task.id}": []' in page.text
    detail = authenticated_client.get(f"/v2-clean/tasks/{task.id}/detail")
    assert detail.status_code == 200
    assert 'id="task-support"' not in detail.text
    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_target": f"team:{support_team.id}",
            "message": "Pedido forjado em arquivo",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db_session.expire_all()
    persisted = db_session.get(Task, task.id)
    assert persisted.status == archived_status
    assert persisted.closed_at is not None
    assert not db_session.scalar(
        select(TaskHelpRequest.id).where(TaskHelpRequest.task_id == task.id)
    )


def test_support_return_to_waiting_preserves_sla_pause(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Suporte durante espera")
    paused_at = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    task.status = "waiting"
    task.sla_paused_at = paused_at
    db_session.commit()
    support_team = _support_team_with_eligible_member(db_session)
    authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={
            "requested_target": f"team:{support_team.id}",
            "message": "Apoio sem retomar SLA",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )
    item = db_session.scalar(
        select(TaskHelpRequest).where(TaskHelpRequest.task_id == task.id)
    )

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help/{item.id}",
        data={
            "response": "cancelled",
            "next_status": "waiting",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    persisted = db_session.get(Task, task.id)
    assert persisted.status == "waiting"
    assert persisted.sla_paused_at.replace(tzinfo=UTC) == paused_at


@pytest.mark.parametrize(
    "persisted_status",
    ("new", "in_execution", "waiting", "support_requested", "resolved", "closed", "cancelled"),
)
def test_edit_never_changes_status_without_explicit_transition(
    authenticated_client, db_session, persisted_status
) -> None:
    task = _new_task(db_session, title=f"Edição preserva {persisted_status}")
    task.status = persisted_status
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/update",
        data={
            "title": f"{task.title} revista",
            "priority": "normal",
            "status": "closed" if persisted_status != "closed" else "new",
            "return_url": RETURN_CONTEXT,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    db_session.expire_all()
    assert db_session.get(Task, task.id).status == persisted_status


def test_duplicate_and_out_of_scope_support_requests_fail_closed(
    authenticated_client, db_session
) -> None:
    task = _new_task(db_session, title="Suporte sem duplicados")
    support_team = _support_team_with_eligible_member(db_session)
    payload = {
        "requested_target": f"team:{support_team.id}",
        "message": "Mesmo pedido ativo",
        "return_url": RETURN_CONTEXT,
    }
    first = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help", data=payload, follow_redirects=False
    )
    duplicate = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help", data=payload, follow_redirects=False
    )
    eligible_member_id = db_session.scalar(
        select(TeamMember.user_id).where(TeamMember.team_id == support_team.id)
    )
    different_target = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={**payload, "requested_target": f"user:{eligible_member_id}"},
        follow_redirects=False,
    )
    forged = authenticated_client.post(
        f"/v2-clean/tasks/{task.id}/help",
        data={**payload, "requested_target": "team:999999"},
        follow_redirects=False,
    )

    assert first.status_code == 303
    assert duplicate.status_code in {409, 422} or (
        duplicate.status_code == 303
        and any(flag in duplicate.headers["location"] for flag in ("duplicate", "already_active", "error="))
    )
    assert different_target.status_code in {409, 422} or (
        different_target.status_code == 303
        and any(flag in different_target.headers["location"] for flag in ("duplicate", "already_active", "error="))
    )
    assert forged.status_code in {403, 422} or (
        forged.status_code == 303
        and any(flag in forged.headers["location"] for flag in ("forbidden", "invalid_target", "error="))
    )
    assert db_session.scalar(
        select(func.count(TaskHelpRequest.id)).where(TaskHelpRequest.task_id == task.id)
    ) == 1
