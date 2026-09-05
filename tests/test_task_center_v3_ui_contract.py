from pathlib import Path

import pytest
import app.web.router as task_router

from app.models.tasks import Task


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "app/templates/_task_center_approved.html").read_text(
    encoding="utf-8"
)
ROUTER = (ROOT / "app/web/router.py").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _enable_v3_surface(monkeypatch):
    monkeypatch.setattr(task_router.settings, "visual_foundation_enabled", True)


def test_queue_selector_never_offers_an_aggregate() -> None:
    assert 'name="queue" data-task-queue' in TEMPLATE
    assert '<option value="">Todas autorizadas</option>' not in TEMPLATE
    assert "authorized_task_queue" in ROUTER
    assert 'queue_error == "forbidden"' in ROUTER


def test_work_views_and_queue_are_independent_and_fail_closed() -> None:
    assert 'name="task_scope_view"' in TEMPLATE
    assert 'name="queue"' in TEMPLATE
    assert 'mine_relation_conditions["team"] = literal(False)' in ROUTER
    assert "Never substitute" in ROUTER
    assert "event.target.value||'all'" not in TEMPLATE


def test_all_work_view_is_canonical_without_aggregating_queues() -> None:
    assert '("all","Todas")' in TEMPLATE
    assert "task_all_scope_allowed" in TEMPLATE
    assert "scope==='all'?'all':'assigned'" in TEMPLATE
    assert 'TaskScopeView("all", "all", "all", "")' in (
        ROOT / "app/services/task_center.py"
    ).read_text(encoding="utf-8")
    assert "task_visibility_filter" in ROUTER
    assert 'queue in {"all", "authorized", "todas"}' in ROUTER


def test_filter_grid_has_explicit_reset_column_and_responsive_stack() -> None:
    desktop_rule_start = CSS.index(
        ".task-center-approved .task-center-approved-filter-row{"
        "grid-template-columns:minmax(170px"
    )
    desktop_rule = CSS[desktop_rule_start:].split("}", 1)[0]
    assert desktop_rule.count("minmax(") == 8
    assert "[data-task-safe-reset]{height:32px;min-width:104px" in CSS
    assert "@media(max-width:1390px) and (min-width:901px)" in CSS
    assert "grid-template-columns:repeat(4,minmax(130px,1fr))" in CSS
    assert "@media(max-width:900px)" in CSS


def test_closed_plus_risk_is_blocked_on_server_and_in_ui(
    authenticated_client,
) -> None:
    page = authenticated_client.get(
        "/v2-clean/tasks?workspace=mine&status=closed&due=due_soon"
    )

    assert page.status_code == 200
    assert "incompat" in page.text
    assert '<option value="due_soon" selected' not in page.text
    assert "risk.disabled=closed" in TEMPLATE
    assert 'active_status == "closed" and active_due == "due_soon"' in ROUTER


def test_unauthorized_or_aggregate_queue_value_fails_to_one_queue(
    authenticated_client,
    db_session,
) -> None:
    db_session.add_all(
        [
            Task(
                title="Operacional singular",
                task_type="operational_task",
                status="new",
                priority="normal",
            ),
            Task(
                title="Administrativa não agregada",
                task_type="administration_task",
                status="new",
                priority="normal",
            ),
        ]
    )
    db_session.commit()

    page = authenticated_client.get(
        "/v2-clean/tasks?queue=all&workspace=all&status=open"
    )

    assert page.status_code == 400
    assert "agregada" in page.text


def test_explicit_sort_and_compact_inline_workbench_are_exposed() -> None:
    assert 'name="sort" data-task-sort' in TEMPLATE
    assert "Ordenação:" in TEMPLATE
    assert "data-workbench-tab" not in TEMPLATE
    for field in ("category", "owner", "due", "sla-detail"):
        assert f"data-preview-{field}" in TEMPLATE
    assert 'data-state="{{ task_status_labels.get(task.status, task.status) }}"' in TEMPLATE
    assert 'data-priority="{{ task_priority_labels.get(task.priority, \'Normal\') }}"' in TEMPLATE
    assert "data-preview-state" not in TEMPLATE
    assert "data-preview-priority" not in TEMPLATE
    assert "Próxima ação:" in TEMPLATE


def test_comment_and_return_context_contract_is_explicit() -> None:
    assert ">Comentar</button>" in TEMPLATE
    assert 'textarea name="comment"' in TEMPLATE
    assert "required maxlength=\"4000\"" in TEMPLATE
    assert "sem alterar o estado" in TEMPLATE
    assert 'data-return-context="{{ request.url.path }}?{{ request.url.query }}"' in TEMPLATE
    assert "return_url:location.pathname+location.search+location.hash" in TEMPLATE
