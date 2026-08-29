from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.sql import literal

import app.web.router as task_router
from app.models import AuditLog, Permission, Role, RolePermission, Task, TaskCase, TaskHistory, User
from app.services.task_cases import (
    TaskCaseError,
    add_task_to_case,
    calculated_case_state,
    create_case_with_first_task,
    create_related_case,
)

MIGRATION = (
    Path(__file__).parents[1] / "migrations/versions/fff6ab1c2d3e_add_task_cases.py"
).read_text(encoding="utf-8")


def _actor(db):
    return db.scalar(select(User).where(User.email == "admin.tests@carfast.local"))


def _task(db, title="Tarefa", *, status="new", due_on=None):
    actor = _actor(db)
    item = Task(
        title=title,
        task_type="operational_task",
        category="operations",
        subcategory="task",
        source="test",
        status=status,
        priority="normal",
        created_by_id=actor.id,
        due_on=due_on,
        assignment_mode="manual",
        assignment_state="waiting_assignment",
    )
    db.add(item)
    db.flush()
    return item


def _grant_cases(db):
    role = db.scalar(select(Role).where(Role.code == "admin"))
    for code in ("cases.read", "cases.create", "cases.update"):
        permission = Permission(code=code, name=code)
        db.add(permission)
        db.flush()
        db.add(RolePermission(role_id=role.id, permission_id=permission.id))
    db.commit()


def test_migration_is_additive_and_downgrade_fails_closed() -> None:
    assert 'sa.Column("case_id", sa.Integer(), nullable=True)' in MIGRATION
    assert 'ondelete="SET NULL"' in MIGRATION
    assert "cases={case_count}, grants={grants}" in MIGRATION
    assert "INSERT INTO role_permissions" not in MIGRATION
    assert "DELETE FROM permissions" not in MIGRATION
    service_source = Path(
        Path(__file__).parents[1] / "app/services/task_cases.py"
    ).read_text(encoding="utf-8")
    assert ".with_for_update()" in service_source
    assert "populate_existing=True" in service_source


def test_case_is_not_a_task_and_state_is_calculated(db_session) -> None:
    actor = _actor(db_session)
    first = _task(db_session, "Primeira")
    case = create_case_with_first_task(
        db_session, title="Caso operacional", first_task=first, actor_user_id=actor.id
    )
    db_session.flush()

    assert db_session.scalar(select(func.count(Task.id))) == 1
    assert db_session.scalar(select(func.count(TaskCase.id))) == 1
    assert first.case_id == case.id
    assert calculated_case_state([first]) == "active"
    assert (
        db_session.scalar(
            select(func.count(TaskHistory.id)).where(TaskHistory.field_name == "case_id")
        )
        == 1
    )
    assert (
        db_session.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.entity_type == "task_case")
        )
        == 1
    )


def test_three_atomic_case_flows_and_one_level_rule(db_session) -> None:
    actor = _actor(db_session)
    first = _task(db_session, "Primeira")
    case = create_case_with_first_task(
        db_session, title="Caso A", first_task=first, actor_user_id=actor.id
    )
    second = Task(
        title="Segunda",
        task_type="operational_task",
        category="operations",
        subcategory="task",
        source="test",
        status="new",
        priority="normal",
        created_by_id=actor.id,
        assignment_mode="manual",
        assignment_state="waiting_assignment",
    )
    add_task_to_case(db_session, case=case, task=second, actor_user_id=actor.id)

    original = _task(db_session, "Original")
    related = Task(
        title="Relacionada",
        task_type="operational_task",
        category="operations",
        subcategory="task",
        source="test",
        status="new",
        priority="normal",
        created_by_id=actor.id,
        assignment_mode="manual",
        assignment_state="waiting_assignment",
    )
    related_case = create_related_case(
        db_session,
        title="Caso B",
        original_task=original,
        related_task=related,
        actor_user_id=actor.id,
    )
    db_session.flush()

    assert {first.case_id, second.case_id} == {case.id}
    assert {original.case_id, related.case_id} == {related_case.id}
    with pytest.raises(TaskCaseError, match="task_already_in_case"):
        create_related_case(
            db_session,
            title="Nested",
            original_task=first,
            related_task=Task(
                title="Nunca",
                task_type="operational_task",
                status="new",
                source="test",
                priority="normal",
                created_by_id=actor.id,
                assignment_mode="manual",
                assignment_state="waiting_assignment",
            ),
            actor_user_id=actor.id,
        )


def test_failed_related_flow_rolls_back_new_task(db_session) -> None:
    actor = _actor(db_session)
    original = _task(db_session, "Original")
    before = db_session.scalar(select(func.count(Task.id)))
    with pytest.raises(TaskCaseError, match="case_title_required"):
        create_related_case(
            db_session,
            title=" ",
            original_task=original,
            related_task=Task(
                title="Transitória",
                task_type="operational_task",
                category="operations",
                subcategory="task",
                source="test",
                status="new",
                priority="normal",
                created_by_id=actor.id,
                assignment_mode="manual",
                assignment_state="waiting_assignment",
            ),
            actor_user_id=actor.id,
        )
    assert db_session.scalar(select(func.count(Task.id))) == before
    assert original.case_id is None


def test_calculated_case_state_uses_worst_child_condition(db_session) -> None:
    overdue = _task(db_session, "Atrasada", due_on=date.today() - timedelta(days=1))
    risk = _task(db_session, "Risco", due_on=date.today())
    assert calculated_case_state([overdue, risk]) == "overdue"
    overdue.status = "closed"
    assert calculated_case_state([overdue, risk]) == "at_risk"
    risk.status = "closed"
    assert calculated_case_state([overdue, risk]) == "completed"


def test_feature_flag_off_hides_surface_and_blocks_endpoint(
    authenticated_client, db_session, monkeypatch
) -> None:
    _grant_cases(db_session)
    monkeypatch.setattr(task_router.settings, "task_cases_enabled", False)
    page = authenticated_client.get("/v2-clean/tasks?grouping=case")
    denied = authenticated_client.post(
        "/v2-clean/task-cases",
        data={"case_title": "Caso", "task_title": "Primeira"},
        follow_redirects=False,
    )
    assert page.status_code == 200
    assert "data-grouping-mode" not in page.text
    assert denied.status_code == 303 and "forbidden" in denied.headers["location"]


def test_grouped_web_flow_preserves_filters_and_exposes_preview(
    authenticated_client, db_session, monkeypatch
) -> None:
    _grant_cases(db_session)
    monkeypatch.setattr(task_router.settings, "task_cases_enabled", True)
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    response = authenticated_client.post(
        "/v2-clean/task-cases",
        data={
            "case_title": "Preparação para venda",
            "task_title": "Retirar reservas futuras",
            "return_url": (
                "/v2-clean/tasks?queue=tasks_support&view=mine"
                "&grouping=case&q=reservas#task-7"
            ),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "queue=tasks_support" in response.headers["location"]
    assert "grouping=case" in response.headers["location"]
    assert "case_created=" in response.headers["location"].split("#", 1)[0]
    assert response.headers["location"].endswith("#task-7")
    page = authenticated_client.get("/v2-clean/tasks?grouping=case&workspace=mine")
    assert page.status_code == 200
    assert 'data-grouping="case"' in page.text
    assert "Preparação para venda" in page.text
    assert "Retirar reservas futuras" in page.text
    assert "data-group-task" in page.text
    assert "+ Criar tarefa relacionada" in page.text
    assert "Prioridade" in page.text and "Responsável" in page.text and "Prazo" in page.text


def test_group_summary_counts_all_filtered_children_across_pages(
    authenticated_client, db_session, monkeypatch
) -> None:
    _grant_cases(db_session)
    monkeypatch.setattr(task_router.settings, "task_cases_enabled", True)
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)
    actor = _actor(db_session)
    first = _task(db_session, "Filha 01")
    case = create_case_with_first_task(
        db_session, title="Caso com muitas tarefas", first_task=first, actor_user_id=actor.id
    )
    for index in range(2, 52):
        child = _task(db_session, f"Filha {index:02d}")
        child.case_id = case.id
    db_session.commit()

    page = authenticated_client.get("/v2-clean/tasks?grouping=case&workspace=mine&page=1")

    assert page.status_code == 200
    assert "51 tarefas" in page.text


def test_add_to_case_fails_closed_outside_task_scope(
    authenticated_client, db_session, monkeypatch
) -> None:
    _grant_cases(db_session)
    monkeypatch.setattr(task_router.settings, "task_cases_enabled", True)
    actor = _actor(db_session)
    first = _task(db_session, "Visível antes do scope")
    case = create_case_with_first_task(
        db_session, title="Caso restrito", first_task=first, actor_user_id=actor.id
    )
    db_session.commit()
    monkeypatch.setattr(
        task_router, "task_visibility_filter", lambda *_args, **_kwargs: literal(False)
    )

    denied = authenticated_client.post(
        f"/v2-clean/task-cases/{case.id}/tasks",
        data={"task_title": "Não deve existir"},
        follow_redirects=False,
    )

    assert denied.status_code == 303
    assert "forbidden" in denied.headers["location"]
    assert (
        db_session.scalar(select(func.count(Task.id)).where(Task.title == "Não deve existir")) == 0
    )


def test_case_surface_separates_create_and_update_capabilities() -> None:
    source = (
        Path(__file__).parents[1] / "app/templates/_task_center_approved.html"
    ).read_text(encoding="utf-8")
    assert "group.case and can_update_cases" in source
    assert "task_cases_enabled and (can_create_cases or can_update_cases)" in source
    assert "task_cases_enabled and can_create_cases" in source


def test_grouped_children_define_readable_text_and_visible_focus() -> None:
    source = (
        Path(__file__).parents[1] / "app/static/css/ui-contract-v1.css"
    ).read_text(encoding="utf-8")
    rule = source.split(".task-group-child{", 1)[1].split("}", 1)[0]
    assert "color:var(--text,#1d2939)" in rule
    assert ".task-group-child:focus-visible{outline:2px solid" in source
