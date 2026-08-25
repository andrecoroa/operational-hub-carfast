from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_fleet_list_uses_compositional_workbench_not_css_only():
    template = _read("app/templates/clean_fleet.html")

    assert 'class="content clean-content{% if foundation_ui_enabled %} visual-fleet{% endif %}"' in template
    assert '{% include "_visual_topbar.html" %}' in template
    assert 'class="visual-fleet-heading"' in template
    assert 'class="visual-fleet-metrics"' in template
    assert "visual-fleet-workbench" in template
    assert "visual-fleet-workbench-header" in template
    assert "visual-fleet-filters" in template
    assert "visual-fleet-table-scroll" in template


def test_fleet_preserves_filters_routes_and_return_context():
    template = _read("app/templates/clean_fleet.html")

    assert 'action="/v2-clean/fleet"' in template
    assert 'name="q"' in template
    assert 'name="scope"' in template
    assert "current_list_url" in template
    assert "data-fleet-open" in template
    assert "sessionStorage.setItem(storageKey" in template
    assert 'href="/v2-clean/fleet/sales"' in template


def test_sales_is_composed_under_fleet_but_remains_independent():
    sidebar = _read("app/templates/_sidebar.html")
    sales_router = _read("app/web/vehicle_sales.py")

    fleet_start = sidebar.index('data-nav-icon="fleet"')
    fleet_end = sidebar.index("{% if can_nav_stock and not can_nav_workshop %}")
    fleet_block = sidebar[fleet_start:fleet_end]
    assert "Vendas" in fleet_block
    assert "/v2-clean/fleet/sales" in fleet_block
    assert "/v2-clean/fleet/sales/proposals" in fleet_block
    assert "/v2-clean/fleet/sales/opportunities" in fleet_block
    assert "Publicações" in fleet_block
    assert 'active_menu in ["fleet", "fleet_sales"]' in sidebar
    assert 'nav_has_permission(request, "fleet.commerce.manage"' in fleet_block
    assert '"/v2-clean/fleet/sales/opportunities"' in sales_router
    assert 'publication_status=published' not in fleet_block


def test_fleet_sidebar_exposes_approved_operational_structure():
    sidebar = _read("app/templates/_sidebar.html")

    for label in ("Viaturas", "Alertas", "Ocorrências", "Documentos", "Configuração"):
        assert label in sidebar
    for path in (
        "/v2-clean/fleet",
        "/alerts",
        "/v2-clean/tasks?workspace=fleet",
        "/v2-clean/documentation/by-vehicle",
    ):
        assert f'href="{path}"' in sidebar
    assert 'nav_has_permission(request, "documents.read", "documents.write", "admin.manage") and nav_has_permission(request, "vehicles.read", "vehicles.write", "admin.manage")' in sidebar


def test_fleet_visual_composition_falls_back_when_feature_flag_is_off():
    template = _read("app/templates/clean_fleet.html")

    assert "{% if foundation_ui_enabled %}" in template
    assert "clean-workshop-header clean-workshop-header-final" in template
    assert "clean-metric-grid clean-fleet-metrics" in template
    assert "{% if foundation_ui_enabled %} visual-fleet-workbench{% endif %}" in template


def test_fleet_responsive_contract_uses_local_table_overflow():
    css = _read("app/static/css/visual-v2.css")

    assert ".visual-fleet-metrics { display: grid" in css
    assert "grid-template-columns: repeat(4,minmax(0,1fr))" in css
    assert ".visual-fleet-table-scroll { border: 0" in css
    assert '.visual-fleet-table-scroll::before' in css
    assert 'content: "Deslize para consultar todos os dados →"' in css
    assert "@media (max-width:1199px)" in css
    assert "@media (max-width:767px)" in css


def test_fleet_asset_is_cache_busted():
    base = _read("app/templates/base.html")
    assert "/static/css/visual-v2.css?v=20260825-fleet1" in base
