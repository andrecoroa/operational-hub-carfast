from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_sidebar_distinguishes_current_page_from_expanded_group() -> None:
    sidebar = _read("app/templates/_sidebar.html")
    css = _read("app/static/css/visual-v2.css")

    assert 'aria-current="page"' in sidebar
    assert 'class="group-current"' in sidebar
    assert '<summary data-nav-icon="fleet" {% if fleet_menu_open %}class="group-current"{% endif %}>' in sidebar
    assert '<summary data-nav-icon="documents" {% if documentation_menu_open %}class="group-current"{% endif %}>' in sidebar
    assert ".sidebar-nav-group > summary.group-current" in css
    assert ".sidebar a.active { box-shadow:" in css


def test_sidebar_accordion_and_accessibility_contract() -> None:
    script = _read("app/static/js/visual-v2.js")

    assert 'querySelectorAll(".sidebar-nav-group")' in script
    assert 'summary?.setAttribute("aria-expanded", String(group.open))' in script
    assert "other.open = false" in script
    assert 'event.key === "Escape"' in script


def test_sidebar_scroll_keeps_stock_as_a_primary_destination() -> None:
    sidebar = _read("app/templates/_sidebar.html")
    css = _read("app/static/css/visual-v2.css")

    workshop = sidebar.index('href="/v2-clean/workshop"')
    stock = sidebar.index('href="/v2-clean/stock"', workshop)
    fleet = sidebar.index("fleet_menu_open", stock)
    assert workshop < stock < fleet
    assert 'href="/v2-clean/stock"' in sidebar
    assert "grid-template-rows: auto minmax(0,1fr) auto" in css
    assert "overflow-y: auto" in css


def test_workshop_preview_is_inline_and_wait_panel_is_not_overlaid() -> None:
    template = _read("app/templates/clean_workshop_dashboard.html")
    css = _read("app/static/css/app.css")

    assert "data-workshop-preview" in template
    assert "data-workshop-preview-close" in template
    assert 'aria-label="Abrir navegação" aria-controls="visual-sidebar"' in template
    assert "data-workshop-wait-panel" in template
    assert 'event.key !== "Escape"' in template
    assert "history.replaceState" in template
    assert ".clean-workshop-process-preview" in css
    assert ".clean-workshop-table-scroll .clean-workshop-list-head" in css
    assert ".clean-workshop-wait-control form" not in css
    preview_css = css[
        css.index(".clean-workshop-process-preview") : css.index(".clean-task-classification-row")
    ]
    assert "position: absolute" not in preview_css


def test_workshop_change_does_not_add_waiting_note_or_stock_behavior() -> None:
    template = _read("app/templates/clean_workshop_dashboard.html")

    assert 'name="waiting_reason"' in template
    assert 'name="waiting_note"' not in template
    assert "/v2-clean/stock" not in template
