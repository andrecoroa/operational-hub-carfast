from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSS = (ROOT / "app/static/css/app.css").read_text(encoding="utf-8")
JS = (ROOT / "app/static/js/admin-table-tools.js").read_text(encoding="utf-8")
WORKSHOP_MODELS = (ROOT / "app/templates/clean_workshop_models_admin.html").read_text(encoding="utf-8")


def test_admin_tables_get_local_keyboard_scroll_regions() -> None:
    assert 'table.closest(".clean-table-scroll, .table-wrap")' in JS
    assert 'container.classList.add("clean-admin-table-region")' in JS
    assert 'container.setAttribute("role", "region")' in JS
    assert 'container.setAttribute("aria-label"' in JS
    assert 'container.setAttribute("aria-describedby", hint.id)' in JS
    assert "container.tabIndex = 0" in JS
    assert "Deslize horizontalmente" in JS


def test_admin_table_regions_keep_context_visible_on_narrow_screens() -> None:
    assert ".clean-admin-table-region {" in CSS
    assert "overflow-x: auto" in CSS
    assert ".clean-admin-table-scroll-hint {" in CSS
    assert "position: sticky" in CSS
    assert ".clean-admin-table-region table thead th:first-child" in CSS
    assert ".clean-admin-table-region .email-access-matrix" in CSS
    assert 'min-width: 180px' in CSS


def test_structure_table_no_longer_creates_a_vertical_scroll_pane() -> None:
    structure = CSS.split(".clean-work-structure-wrap {", 1)[1].split("}", 1)[0]
    assert "max-height: none" in structure
    assert "overflow-x: auto" in structure
    assert "max-height: min(62vh" not in structure


def test_workshop_models_uses_the_same_admin_table_contract() -> None:
    assert '<script src="/static/js/admin-table-tools.js"></script>' in WORKSHOP_MODELS
