from pathlib import Path

import pytest

from app.core.config import settings
from app.web import router


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def test_stock_primary_surfaces_use_canonical_visual_workbench() -> None:
    for name in (
        "clean_stock_dashboard.html",
        "clean_stock_articles.html",
        "clean_stock_movements.html",
        "clean_stock_orders.html",
        "clean_stock_receipts.html",
        "clean_stock_workshop_requests.html",
        "clean_stock_inventory.html",
    ):
        source = _read(name)
        assert "foundation_ui_enabled" in source, name
        assert "ui-page-shell" in source, name
        assert "_clean_stock_nav.html" in source, name


def test_stock_navigation_matches_approved_workshop_composition() -> None:
    source = _read("_clean_stock_nav.html")
    expected = (
        ("Stock", "/v2-clean/stock/articles"),
        ("Movimentos", "/v2-clean/stock/movements"),
        ("Pedidos", "/v2-clean/stock/workshop-requests"),
        ("Compras / Encomendas", "/v2-clean/stock/orders"),
        ("Receções", "/v2-clean/stock/receipts"),
        ("Inventários", "/v2-clean/stock/inventory"),
    )
    for label, route in expected:
        assert label in source
        assert route in source
    assert 'aria-current="page"' in source


def test_stock_forms_keep_existing_routes_and_permission_guards() -> None:
    articles = _read("clean_stock_articles.html")
    movements = _read("clean_stock_movements.html")
    orders = _read("clean_stock_orders.html")
    receipts = _read("clean_stock_receipts.html")
    inventory = _read("clean_stock_inventory.html")
    requests = _read("clean_stock_workshop_requests.html")

    assert 'action="/v2-clean/stock/articles/bulk-category"' in articles
    assert "can_operate_stock" in articles and "can_manage_stock" in articles
    assert 'action="/v2-clean/stock/movements"' in movements
    assert "can_operate_stock" in movements
    assert 'action="/v2-clean/stock/orders"' in orders
    assert "can_manage_orders" in orders
    assert 'action="/v2-clean/stock/receipts"' in receipts
    assert "can_operate_stock" in receipts
    assert 'action="/v2-clean/stock/inventory"' in inventory
    assert "can_count_inventory" in inventory and "can_confirm_inventory" in inventory
    assert "/v2-clean/stock/workshop-requests/{{ item.reference }}/deliver" in requests
    assert "can_operate_stock" in requests


def test_stock_tables_are_local_scroll_regions_not_global_overflow() -> None:
    css = (ROOT / "app" / "static" / "css" / "visual-v2.css").read_text(encoding="utf-8")
    assert ".visual-stock-workbench .stock-table-wrap{overflow-x:auto}" in css
    assert ".stock-nav" in css and "overflow-x:auto" in css
    assert "Deslize para consultar todas as colunas" in css
    assert ".stock-nav-affordance" in css
    assert "Mais →" in _read("_clean_stock_nav.html")


def test_stock_runtime_off_preserves_legacy_navigation_and_dom(
    authenticated_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "visual_foundation_enabled", False)
    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", False)
    response = authenticated_client.get("/v2-clean/stock/articles")
    assert response.status_code == 200
    assert "stock-context-bar" not in response.text
    assert "visual-stock-toolbar" not in response.text
    assert "visual-stock-table-card" not in response.text
    assert "Artigos e existências" in response.text


@pytest.mark.parametrize(
    ("route", "legacy_marker", "visual_marker"),
    (
        ("/v2-clean/stock", "Resumo de Stock", "Disponibilidade, abastecimento e conferência"),
        (
            "/v2-clean/stock/workshop-requests",
            "A entrega confirmada é o único momento que desconta existências.",
            "Priorize necessidades de material",
        ),
        ("/v2-clean/stock/inventory", "Sessões de contagem", "Conte sem revelar o saldo esperado"),
        (
            "/v2-clean/stock/orders",
            "Numeração e versão controladas; estado comercial separado da receção.",
            "Planeie a compra e acompanhe separadamente",
        ),
        (
            "/v2-clean/stock/receipts",
            "Só quantidades fisicamente aceites alteram stock.",
            "confirme documentos e divergências",
        ),
    ),
)
def test_stock_runtime_off_preserves_representative_legacy_content(
    authenticated_client, monkeypatch, route: str, legacy_marker: str, visual_marker: str
) -> None:
    monkeypatch.setattr(settings, "visual_foundation_enabled", False)
    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", False)
    response = authenticated_client.get(route)
    assert response.status_code == 200
    assert "stock-context-bar" not in response.text
    assert "visual-stock-heading" not in response.text
    assert legacy_marker in response.text
    assert visual_marker not in response.text


def test_stock_runtime_on_uses_composed_navigation(
    authenticated_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)
    monkeypatch.setitem(router.templates.env.globals, "foundation_ui_enabled", True)
    response = authenticated_client.get("/v2-clean/stock/articles")
    assert response.status_code == 200
    assert "stock-context-bar" in response.text
    assert "visual-stock-toolbar" in response.text
    assert "visual-stock-table-card" in response.text
    assert 'aria-label="Navegação Stock e Compras"' in response.text


def test_workshop_return_requires_independent_workshop_permission() -> None:
    nav = _read("_clean_stock_nav.html")
    assert '"navigation.workshop.access" in stock_nav_perms' in nav
    assert 'nav_has_permission(request, "workshop.read", "workshop.write", "admin.manage")' in nav
    assert "Voltar à Oficina" in nav
