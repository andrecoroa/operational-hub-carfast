from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = (ROOT / "app/templates/clean_task_center.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/ui-contract-v1.css").read_text(encoding="utf-8")
ROUTER = (ROOT / "app/web/router.py").read_text(encoding="utf-8")


def test_approved_task_center_has_five_independent_keyboard_counters() -> None:
    assert 'class="task-center-approved-metrics"' in TEMPLATE
    assert TEMPLATE.count('class="task-center-approved-metric') == 5
    assert TEMPLATE.count('data-task-counter=') == 5
    assert '<button' in TEMPLATE


def test_approved_safe_default_and_reset_are_explicit() -> None:
    assert 'value="mine"' in TEMPLATE
    assert 'value="open"' in TEMPLATE
    assert 'name="category"' in TEMPLATE
    assert 'data-task-safe-reset' in TEMPLATE
    assert 'Fechadas excluídas' in TEMPLATE
    assert 'default_task_category' in ROUTER


def test_approved_categories_are_exclusive_and_workspace_is_62_38() -> None:
    for label in ("Documentação", "Oficina", "Sinistros", "Todas"):
        assert label in TEMPLATE
    assert 'role="radiogroup"' in TEMPLATE
    assert 'name="category"' in TEMPLATE
    assert "grid-template-columns:minmax(0,62fr) minmax(360px,38fr)" in CSS


def test_approved_queue_has_exactly_seven_fields_and_42px_rows() -> None:
    expected = ("Prior.", "Referência", "Assunto", "Categoria", "Responsável", "Prazo", "Estado")
    for label in expected:
        assert f"<th>{label}</th>" in TEMPLATE
    assert 'data-task-field-count="7"' in TEMPLATE
    assert "height:42px" in CSS


def test_approved_preview_is_inline_and_has_at_most_four_rbac_actions() -> None:
    assert 'class="task-center-approved-preview"' in TEMPLATE
    assert 'aria-live="polite"' in TEMPLATE
    assert 'data-task-preview-close' in TEMPLATE
    assert 'data-task-preview-action' in TEMPLATE
    assert TEMPLATE.count('data-task-preview-action') <= 4
    assert "task_update_allowed_by_id" in TEMPLATE
    assert "task_close_allowed_by_id" in TEMPLATE


def test_approved_selection_preserves_return_context() -> None:
    assert 'data-task-row' in TEMPLATE
    assert 'data-return-context' in TEMPLATE
    assert 'history.replaceState' in TEMPLATE
    assert 'sessionStorage' in TEMPLATE


def test_server_side_scope_is_shared_by_list_and_counters() -> None:
    assert "visibility_filter =" in ROUTER
    assert "task_visibility_filter" in ROUTER
    assert "task_counter_metrics" in ROUTER
    assert "counter_base_filters" in ROUTER

