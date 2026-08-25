from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
MATRIX = ROOT / "docs" / "evidence" / "visual-route-matrix" / "ROUTE_CONTENT_MATRIX.md"


def _template(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_three_final_surfaces_use_canonical_composition() -> None:
    financial = _template("clean_vehicle_financial_audit.html")
    access = _template("clean_portal_access.html")
    recurrence = _template("clean_task_recurrence.html")
    for source in (financial, access, recurrence):
        assert '_visual_topbar.html' in source
        assert "visual-final-closeout" in source
        assert "visual-final-metrics" in source
        assert "visual-final-empty" in source
    assert '_sales_context_nav.html' in financial
    assert '_sales_context_nav.html' in access
    assert "visual-final-workbench" in financial
    assert "visual-final-workbench" in recurrence


def test_recurrence_dialog_is_keyboard_and_return_focus_safe() -> None:
    source = _template("clean_task_recurrence.html")
    assert "event.key !== 'Escape'" in source
    assert "event.key === 'Tab'" in source
    assert 'aria-labelledby="recurrence-edit-title-' in source
    assert "data-recurrence-edit" in source
    assert "?.focus()" in source
    assert "aria-hidden" in source


def test_financial_audit_return_context_preserves_active_filters() -> None:
    source = _template("clean_vehicle_financial_audit.html")
    assert "request.url.query" in source
    assert "return_to=" in source


def test_final_closeout_css_contains_responsive_local_layouts() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert ".visual-final-metrics" in css
    assert "repeat(2, minmax(0, 1fr))" in css
    assert ".visual-sales-access .portal-admin-grid" in css
    assert ".visual-financial-audit .clean-task-filter-row" in css


def test_matrix_keeps_residuals_explicit_until_runtime_gate() -> None:
    source = MATRIX.read_text(encoding="utf-8")
    assert source.count("| parcial |") == 3
    assert "`/v2-clean/fleet/financial-audit`" in source
    assert "`/v2-clean/fleet/sales-access`" in source
    assert "`/v2-clean/tasks/recurring`" in source
