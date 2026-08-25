from pathlib import Path

from app.models import Vehicle


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
    assert "can_nav_sales" in fleet_block
    assert 'nav_has_permission(request, "fleet.commerce.manage"' in sidebar
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


def test_fleet_uses_shared_convergence_asset_version():
    base = _read("app/templates/base.html")
    runtime = _read("app/web/template_runtime.py")
    assert "/static/css/visual-v2.css?v={{ visual_asset_version }}" in base
    assert 'templates.env.globals["visual_asset_version"] = "20260825-convergence1"' in runtime


def test_fleet_list_detail_documents_and_diagnostics_render_composed_surfaces(
    authenticated_client,
    db_session,
    monkeypatch,
):
    from app.web import router

    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", True)
    monkeypatch.setattr(router.settings, "visual_foundation_enabled", True)
    vehicle = Vehicle(
        plate="FX-25-GR",
        vin="VF7SYNTHETICFLEET25",
        rentway_unit_nr="FX25",
        brand="Peugeot",
        model="208",
        active=True,
        lifecycle_status="active",
        operational_status="free",
    )
    db_session.add(vehicle)
    db_session.commit()

    pages = {
        "/v2-clean/fleet": ("visual-fleet-workbench", "Inventário operacional"),
        f"/v2-clean/fleet/{vehicle.id}": ("visual-fleet-detail-workbench", "Contexto da viatura"),
        f"/v2-clean/fleet/{vehicle.id}/documents": ("visual-fleet-documents", "Comandos documentais"),
        f"/v2-clean/fleet/{vehicle.id}/diagnostics": ("visual-fleet-diagnostics", "Linha cronológica"),
    }
    for path, markers in pages.items():
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert "visual-v2.css?v=20260825-convergence1" in response.text
        assert 'class="sidebar"' in response.text
        assert all(marker in response.text for marker in markers)


def test_fleet_context_navigation_preserves_routes_and_sales_permission_gate():
    detail = _read("app/templates/clean_fleet_detail.html")
    documents = _read("app/templates/clean_fleet_documents.html")
    diagnostics = _read("app/templates/clean_fleet_diagnostics.html")

    for template in (detail, documents, diagnostics):
        assert 'aria-label="Contexto da viatura"' in template
        assert "/documents" in template
        assert "/diagnostics" in template
    assert 'nav_has_permission(request, "fleet.commerce.manage", "vehicles.write", "admin.manage")' in detail
    assert 'href="/v2-clean/fleet/sales/{{ vehicle.id }}"' in detail


def test_sales_pipeline_is_a_composed_fleet_workbench():
    template = _read("app/templates/clean_vehicle_sales.html")
    context_nav = _read("app/templates/_sales_context_nav.html")

    assert "visual-fleet-sales" in template
    assert '{% include "_visual_topbar.html" %}' in template
    assert 'aria-label="Navegação de Vendas"' in context_nav
    assert "visual-sales-metrics" in template
    assert "visual-sales-workbench" in template
    assert "data-sale-bulk-form" in template
    assert "data-sale-preview-dialog" in template
    for path in (
        "/v2-clean/fleet/sales",
        "/v2-clean/fleet/sales/proposals",
        "/v2-clean/fleet/sales/opportunities",
        "/v2-clean/fleet/sales/publications",
    ):
        assert f'href="{path}"' in template + context_nav


def test_sales_secondary_surfaces_share_composition_and_document_authorization():
    for path, marker in (
        ("app/templates/clean_vehicle_sale_proposals.html", 'active_sales_view = "processes"'),
        ("app/templates/clean_vehicle_sale_opportunities.html", 'active_sales_view = "customers"'),
        ("app/templates/clean_vehicle_sale_publications.html", 'active_sales_view = "publications"'),
    ):
        template = _read(path)
        assert "visual-sales-secondary-page" in template
        assert '{% include "_visual_topbar.html" %}' in template
        assert '{% include "_sales_context_nav.html" %}' in template
        assert marker in template

    detail = _read("app/templates/clean_vehicle_sale_detail.html")
    public = _read("app/templates/public_vehicle_sale.html")
    assert 'name="document_ids"' in detail
    assert "Documentos autorizados para esta publicação" in detail
    assert 'snapshot.get("documents", [])' in public
    assert "Apenas os documentos selecionados explicitamente" in public
    assert "visual-secondary-menu" in _read("app/templates/clean_vehicle_sales.html")


def test_fleet_empty_diagnostics_state_remains_explicit_and_non_mutating(
    authenticated_client,
    db_session,
):
    vehicle = Vehicle(
        plate="EMPTY-25",
        active=True,
        lifecycle_status="active",
        operational_status="free",
    )
    db_session.add(vehicle)
    db_session.commit()

    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/diagnostics")

    assert response.status_code == 200
    assert "Não existem diagnósticos para os filtros selecionados." in response.text
    assert "Seleciona um diagnóstico para consultar os dados técnicos." in response.text


def test_fleet_return_context_survives_detail_documents_and_diagnostics(
    authenticated_client,
    db_session,
    monkeypatch,
):
    from app.web import router

    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", True)
    monkeypatch.setattr(router.settings, "visual_foundation_enabled", True)
    vehicle = Vehicle(plate="RC-25-GR", active=True, lifecycle_status="active")
    db_session.add(vehicle)
    db_session.commit()
    return_to = "/v2-clean/fleet?scope=active&page=2#vehicle-99"

    detail = authenticated_client.get(
        f"/v2-clean/fleet/{vehicle.id}", params={"return_to": return_to}
    )
    documents = authenticated_client.get(
        f"/v2-clean/fleet/{vehicle.id}/documents", params={"return_to": return_to}
    )
    diagnostics = authenticated_client.get(
        f"/v2-clean/fleet/{vehicle.id}/diagnostics", params={"return_to": return_to}
    )

    assert detail.status_code == documents.status_code == diagnostics.status_code == 200
    encoded = "/v2-clean/fleet%3Fscope%3Dactive%26page%3D2%23vehicle-99"
    assert f"/documents?return_to={encoded}" in detail.text
    assert f"/diagnostics?return_to={encoded}" in detail.text
    assert f"?return_to={encoded}" in documents.text
    assert f"?return_to={encoded}" in diagnostics.text
    assert 'href="/v2-clean/fleet?scope=active&amp;page=2#vehicle-99"' in detail.text


def test_fleet_detail_documents_diagnostics_and_sales_have_true_flag_off_fallback(
    authenticated_client,
    db_session,
    monkeypatch,
):
    from app.web import router

    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", False)
    monkeypatch.setattr(router.settings, "visual_foundation_enabled", False)
    vehicle = Vehicle(plate="OFF-25-GR", active=True, lifecycle_status="active")
    db_session.add(vehicle)
    db_session.commit()

    for path in (
        f"/v2-clean/fleet/{vehicle.id}",
        f"/v2-clean/fleet/{vehicle.id}/documents",
        f"/v2-clean/fleet/{vehicle.id}/diagnostics",
        "/v2-clean/fleet/sales",
        "/v2-clean/fleet/sales/proposals",
        "/v2-clean/fleet/sales/opportunities",
        "/v2-clean/fleet/sales/publications",
        f"/v2-clean/fleet/sales/{vehicle.id}",
    ):
        response = authenticated_client.get(path)
        assert response.status_code == 200
        assert "visual-v2.css" not in response.text
        assert "visual-fleet-context-nav" not in response.text
        assert "visual-fleet-detail-workbench" not in response.text
        assert "visual-fleet-documents" not in response.text
        assert "visual-fleet-diagnostics" not in response.text
        assert "visual-fleet-sales" not in response.text
