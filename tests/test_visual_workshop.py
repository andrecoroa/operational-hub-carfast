from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_workshop_process_uses_canonical_composition_not_css_only():
    template = _read("app/templates/clean_workshop_phase.html")

    assert "visual-workshop-process" in template
    assert "visual-workshop-stepper" in template
    assert 'class="visual-workshop-tabs"' in template
    assert "visual-workshop-layout" in template
    assert "visual-workshop-workbench" in template
    assert 'class="visual-workshop-summary"' in template
    assert "Trabalho da fase" in template
    assert "Documentos e fotografias" in template
    assert "Peças e custos" in template
    assert 'id="workshop-documents"' in template
    assert 'id="workshop-history"' in template
    assert 'id="workshop-materials"' in template
    assert "data-workshop-summary" in template
    assert "/v2-clean/workshop/preferences/summary" in template
    assert "data-stored-open" in template
    assert "historyPreviewTrigger?.focus()" in template
    assert 'event.key === "Escape"' in template


def test_workshop_preserves_real_routes_actions_and_return_context():
    template = _read("app/templates/clean_workshop_phase.html")

    assert 'action="/v2-clean/workshop/{{ phase_key }}/save"' in template
    assert 'name="action" value="save_substep"' in template
    assert 'name="action" value="advance"' in template
    assert "return_url={{ request.url.path }}" in template
    assert "vehicle_detail_href" in template
    assert "workshop_process.id" in template


def test_stock_and_purchasing_is_composed_under_workshop_with_fallback():
    sidebar = _read("app/templates/_sidebar.html")

    workshop_start = sidebar.index('data-nav-icon="workshop"')
    fleet_start = sidebar.index('data-nav-icon="fleet"')
    workshop_block = sidebar[workshop_start:fleet_start]
    assert "Stock e Compras" in workshop_block
    assert "/v2-clean/stock" in workshop_block
    assert "Movimentos" in workshop_block
    assert "Compras / Encomendas" in workshop_block
    assert "Inventários" in workshop_block
    assert 'active_menu in ["workshop", "stock"]' in sidebar
    assert "{% if can_nav_stock and not can_nav_workshop %}" in sidebar
    assert 'href="/v2-clean/stock"' in sidebar
    for path in (
        "/v2-clean/stock/movements",
        "/v2-clean/stock/workshop-requests",
        "/v2-clean/stock/orders",
        "/v2-clean/stock/receipts",
        "/v2-clean/stock/inventory",
    ):
        assert f'href="{path}"' in sidebar


def test_visual_markup_is_fail_safe_when_foundation_flag_is_off():
    template = _read("app/templates/clean_workshop_phase.html")
    assert '{% if foundation_ui_enabled %}<nav class="visual-workshop-tabs"' in template
    assert '{% if foundation_ui_enabled %}<details class="visual-workshop-summary"' in template
    assert "{% if foundation_ui_enabled %} visual-workshop-process{% endif %}" in template


def test_workshop_responsive_contract_has_local_not_global_overflow():
    css = _read("app/static/css/visual-v2.css")

    assert ".visual-workshop-layout { display: grid" in css
    assert "grid-template-columns: minmax(0,1fr) 286px" in css
    assert ".visual-workshop-stepper" in css and "overflow-x: auto" in css
    assert "grid-template-columns: repeat(7,118px)" in css
    assert ".visual-workshop-tabs::-webkit-scrollbar { display: none; }" in css
    assert "@media (max-width:1199px)" in css
    assert "@media (max-width:767px)" in css


def test_workshop_asset_is_cache_busted():
    base = _read("app/templates/base.html")
    assert "/static/css/visual-v2.css?v=20260825-workshop1" in base


def test_workshop_summary_preference_is_server_side_and_user_scoped():
    router = _read("app/web/router.py")
    assert '@web_router.post("/v2-clean/workshop/preferences/summary")' in router
    assert 'code = f"workshop_summary_{user_id}"' in router
    assert 'SettingsCatalog.code == "user_ui_preferences"' in router
    assert '"workshop_summary_open": workshop_summary_open' in router
