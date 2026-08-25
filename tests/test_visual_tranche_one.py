from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
VISUAL_CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
VISUAL_JS = ROOT / "app" / "static" / "js" / "visual-v2.js"


def test_visual_stylesheet_is_feature_gated() -> None:
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")

    assert "{% if foundation_ui_enabled %}" in base
    assert "/static/css/visual-v2.css" in base


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
    ):
        assert contract in css


def test_topbar_exposes_navigation_and_accessible_controls() -> None:
    source = (TEMPLATES / "_visual_topbar.html").read_text(encoding="utf-8")

    assert "{% if foundation_ui_enabled %}" in source
    assert 'aria-label="Breadcrumb"' in source
    assert 'aria-label="Abrir navegação"' in source
    assert "Pesquisa global" not in source
    assert "Notificações" not in source


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
