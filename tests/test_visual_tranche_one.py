from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
VISUAL_CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
VISUAL_JS = ROOT / "app" / "static" / "js" / "visual-v2.js"


def test_visual_stylesheet_is_feature_gated() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "{% if foundation_ui_enabled %}" in base
    assert "/static/css/visual-v2.css?v=20260825-dashboard-pilot3" in base
    assert "/static/js/visual-v2.js?v=20260825-dashboard-pilot3" in base


def test_priority_surfaces_share_the_canonical_topbar() -> None:
    for name in (
        "clean_home.html",
        "clean_task_center.html",
        "clean_fleet_detail.html",
        "clean_admin.html",
    ):
        source = (TEMPLATES / name).read_text(encoding="utf-8")
        assert '{% include "_visual_topbar.html" %}' in source, name


def test_visual_tokens_and_responsive_contract_are_present() -> None:
    css = VISUAL_CSS.read_text(encoding="utf-8")

    for contract in (
        "--visual-sidebar-width: 208px",
        "--visual-sidebar-collapsed: 64px",
        "--visual-topbar-height: 64px",
        "--visual-grid: 8px",
        "min-height: 40px",
        "@media (max-width: 1199px)",
        "@media (max-width: 767px)",
        ":focus-visible",
        "prefers-reduced-motion: reduce",
        '.clean-shell .sidebar > .sidebar-brand::before { display: flex; width: 42px;',
        '.clean-shell .sidebar-collapse-toggle,.clean-shell .sidebar-logout { display: none;',
        '.clean-shell .sidebar-footer { grid-row: 3; align-self: end;',
        'grid-auto-rows: 48px;',
        '.visual-nav-open .clean-shell .sidebar-evolution-create,.visual-nav-open .clean-shell .sidebar a.sidebar-legacy-link { width: 48px;',
        '.visual-menu-button { display: inline-grid; width: 48px; min-width: 48px; height: 48px;',
        '.clean-shell .sidebar > .sidebar-brand::before { display: none;',
        '.visual-brand-mark svg { width: 30px;',
        'width: 64px; padding-right: 18px; text-align: right; white-space: nowrap;',
    ):
        assert contract in css


def test_topbar_exposes_navigation_and_accessible_controls() -> None:
    source = (TEMPLATES / "_visual_topbar.html").read_text(encoding="utf-8")

    assert "{% if foundation_ui_enabled %}" in source
    assert 'aria-label="Breadcrumb"' in source
    assert 'aria-label="Abrir navegação"' in source
    assert 'role="search"' in source
    assert "data-visual-global-search" in source
    assert 'action="/v2-clean/tasks"' not in source
    assert 'name="q"' in source
    assert 'aria-label="Pesquisar tarefas"' in source
    assert 'aria-label="Notificações"' in source
    assert 'title="Notificações"' in source
    assert '<small>{{ visual_page or "Operação" }}</small>' in source
    assert "♢" not in source
    assert '"navigation.tasks.access" in visual_topbar_perms' in source
    assert '"dashboard.read" in visual_topbar_perms' in source
    assert "⌘ K" not in source
    script = VISUAL_JS.read_text(encoding="utf-8")
    assert 'window.location.assign(`/v2-clean/tasks?q=${encodeURIComponent(term)}`)' in script


def test_dashboard_pilot_rebuilds_markup_instead_of_reusing_legacy_cards() -> None:
    source = (TEMPLATES / "clean_home.html").read_text(encoding="utf-8")

    for component in (
        'class="visual-dashboard-heading"',
        'class="visual-dashboard-metrics"',
        'class="visual-work-table"',
        'class="visual-attention-list"',
        'class="visual-quick-grid"',
        '<table class="visual-work-table"',
    ):
        assert component in source
    assert "{% if foundation_ui_enabled %}" in source
    assert "{% else %}" in source
    assert 'class="clean-home-metrics"' in source
    assert 'class="clean-home-main-grid"' in source
    for placeholder in (">▱<", ">⌁<", ">◎<", ">□<"):
        assert placeholder not in source
    assert source.count("<svg viewBox=") >= 10
    for permission_guard in (
        "{% if home_can_fleet %}",
        "{% if home_can_tasks %}",
        "{% if home_can_workshop %}",
        "{% if home_can_processes %}",
    ):
        assert permission_guard in source


def test_brand_and_sidebar_use_one_accessible_icon_language() -> None:
    sidebar = (TEMPLATES / "_sidebar.html").read_text(encoding="utf-8")
    css = VISUAL_CSS.read_text(encoding="utf-8")

    assert '{% if foundation_ui_enabled %}<span class="visual-brand-mark"' in sidebar
    assert '<p class="eyebrow">CarFast</p>' in sidebar
    assert 'aria-label="Terminar sessão"' in sidebar
    assert 'data-nav-icon="workshop"' in sidebar
    assert 'data-nav-icon="fleet"' in sidebar
    assert 'data-nav-icon="documents"' in sidebar
    assert 'content: "◇"' not in css
    assert 'grid-template-columns: repeat(2,minmax(0,1fr)); gap: 10px;' in css
    assert 'content: "Deslize para ver mais →"' in css
    assert 'height: 42px; padding: 0; justify-content: center; content: "CF"; color: #fff; background: transparent; border: 0;' in css
    assert '.visual-nav-open .clean-shell .sidebar-logout button { width: 48px; min-width: 48px; height: 48px; min-height: 48px; }' in css


def test_mobile_navigation_is_keyboard_closeable() -> None:
    sidebar = (TEMPLATES / "_sidebar.html").read_text(encoding="utf-8")
    script = VISUAL_JS.read_text(encoding="utf-8")

    assert 'id="visual-sidebar"' in sidebar
    assert 'event.key === "Escape"' in script
    assert 'event.key === "Tab"' in script
    assert 'setAttribute("aria-expanded"' in script
    assert 'menuButton.focus()' in script


def test_priority_routes_propagate_the_visual_feature_flag() -> None:
    router = (ROOT / "app" / "web" / "router.py").read_text(encoding="utf-8")
    admin = (ROOT / "app" / "web" / "clean_admin.py").read_text(encoding="utf-8")

    home_block = router[router.index('"clean_home.html"') : router.index('"clean_home.html"') + 400]
    fleet_block = router[
        router.index('"clean_fleet_detail.html"') : router.index('"clean_fleet_detail.html"') + 900
    ]
    layout_block = admin[admin.index("def _layout_context(") : admin.index("def _redirect(")]

    assert '"foundation_ui_enabled": settings.visual_foundation_enabled' in home_block
    assert '"foundation_ui_enabled": settings.visual_foundation_enabled' in fleet_block
    assert '"foundation_ui_enabled": settings.visual_foundation_enabled' in layout_block
