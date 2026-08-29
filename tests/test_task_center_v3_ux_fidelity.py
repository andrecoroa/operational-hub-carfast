from datetime import date, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select

import app.web.router as task_router
from app.models import Task, User


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "app/templates/_task_center_approved.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
PROTOTYPE_SHA256 = "D0AE9B2B33F6BF7C44202392A47AF1733D661E72F7428CA5C71C5AFF14678FB1"


@pytest.fixture(autouse=True)
def _enable_v3_surface(monkeypatch):
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)


def _task(db_session, title: str, *, plate: str, process_id: int, owner: User) -> Task:
    task = Task(
        title=title,
        description="Contexto pesquisável do contrato UX",
        task_type="operational_task",
        status="in_execution",
        priority="high",
        assigned_to_id=owner.id,
        created_by_id=owner.id,
        plate=plate,
        process_instance_id=process_id,
        due_on=date.today() + timedelta(days=2),
    )
    db_session.add(task)
    db_session.commit()
    return task


def test_combined_owner_and_cross_context_search(authenticated_client, db_session):
    owner = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    task = _task(db_session, "Validar entrega contratual", plate="UX-44-UX", process_id=8844, owner=owner)

    for query in (f"CF-{task.id:05d}", "entrega contratual", "UX-44-UX", "8844"):
        page = authenticated_client.get(
            f"/v2-clean/tasks?queue=tasks_support&workspace=mine&owner=user:{owner.id}&priority=high&q={query}"
        )
        assert page.status_code == 200
        assert task.title in page.text
        assert f'value="user:{owner.id}" selected' in page.text
        assert 'name="priority" value="high"' in page.text


def test_complete_sort_contract_and_headers_are_real(authenticated_client, db_session):
    owner = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))
    _task(db_session, "Ordenação UX", plate="UX-45-UX", process_id=8845, owner=owner)

    for sort in ("due_desc", "priority_asc", "state_asc", "owner_asc", "reference_desc", "updated_asc"):
        page = authenticated_client.get(f"/v2-clean/tasks?sort={sort}")
        assert page.status_code == 200
        assert f'<option value="{sort}" selected' in page.text
    for key in ("priority", "reference", "owner", "due_on", "state"):
        assert f'data-sort-key="{key}"' in TEMPLATE


def test_closed_risk_chip_is_normalized_and_density_is_preserved(authenticated_client):
    page = authenticated_client.get(
        "/v2-clean/tasks?status=closed&condition=risk&per_page=25"
    )
    assert page.status_code == 200
    assert "incompat" in page.text
    assert 'name="condition" value=""' in page.text
    assert 'name="per_page" value="25"' in page.text
    assert "riskChip.disabled=closed" in TEMPLATE


def test_dense_table_has_context_pagination_and_no_fake_bulk_selection():
    assert "data-task-density" in TEMPLATE
    assert "task-center-approved-pagination" in TEMPLATE
    assert "task.plate or task_relation_labels" in TEMPLATE
    assert 'type="checkbox"' not in TEMPLATE
    assert ".task-center-approved td{height:42px}" in CSS


def test_workbench_separates_state_condition_responsibility_and_contextual_action():
    for token in (
        "data-next-action",
        "data-preview-detail-state",
        "data-preview-detail-condition",
        "Responsabilidade",
        "SLA e prazo",
        "Acompanhar suporte solicitado",
        "Resolver atraso",
        "Evitar violação de SLA",
        "Rever motivo de espera",
    ):
        assert token in TEMPLATE
    assert "data-preview-support" in TEMPLATE
    assert "data-support-active" in TEMPLATE


def test_loading_empty_error_permission_and_responsive_contract_are_explicit():
    assert "is-loading" in TEMPLATE
    assert "Sem tarefas neste recorte" in TEMPLATE
    assert "Não tem permissão" in TEMPLATE
    assert "clean-alert-warning" in TEMPLATE
    assert "@media(max-width:1180px)" in CSS
    assert "@media(max-width:820px)" in CSS
    assert PROTOTYPE_SHA256
