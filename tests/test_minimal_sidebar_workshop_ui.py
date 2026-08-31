from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from app.web.router import clean_workshop_preserve_return_context


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


def test_sidebar_marks_the_exact_active_fleet_and_documentation_sublinks() -> None:
    sidebar = _read("app/templates/_sidebar.html")

    assert 'fleet_sales_pipeline_current = active_menu == "fleet_sales"' in sidebar
    assert 'fleet_sales_proposals_current = request.url.path.startswith("/v2-clean/fleet/sales/proposals")' in sidebar
    assert 'documentation_by_vehicle' in sidebar
    for current in (
        "fleet_vehicles_current",
        "fleet_sales_pipeline_current",
        "fleet_sales_proposals_current",
        "fleet_sales_opportunities_current",
        "fleet_sales_publications_current",
    ):
        assert f"if {current} %}} aria-current=\"page\"" in sidebar
    for current in (
        "documentation_triage",
        "documentation_treatment",
        "documentation_by_vehicle",
        "documentation_imports",
        "documentation_archive",
    ):
        assert f"active_menu == '{current}' %}} aria-current=\"page\"" in sidebar


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


def test_workshop_return_context_survives_redirects_without_losing_anchor() -> None:
    url = clean_workshop_preserve_return_context(
        "/v2-clean/workshop/validacao?process_id=17&saved=1#pedido",
        "signed-token",
    )

    parsed = urlsplit(url)
    assert parsed.path == "/v2-clean/workshop/validacao"
    assert parse_qs(parsed.query) == {
        "process_id": ["17"],
        "saved": ["1"],
        "return_context": ["signed-token"],
    }
    assert parsed.fragment == "pedido"


def test_sidebar_renders_exactly_one_current_sublink_per_active_surface(
    authenticated_client,
) -> None:
    for url, label in (
        ("/v2-clean/fleet", "Viaturas"),
        ("/v2-clean/fleet/sales", "Pipeline"),
        ("/v2-clean/documentation/triage", "Triagem"),
        ("/v2-clean/documentation/treatment", "Tratamento"),
    ):
        response = authenticated_client.get(url)
        assert response.status_code == 200
        assert response.text.count('aria-current="page"') == 1
        assert re.search(
            rf'<a[^>]*aria-current="page"[^>]*>{re.escape(label)}</a>',
            response.text,
        )
