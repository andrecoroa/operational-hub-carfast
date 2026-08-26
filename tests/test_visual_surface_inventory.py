from __future__ import annotations

import pytest
from pathlib import Path

from app.main import app
from app.core.config import settings
from app.web import clean_admin, email, router
from scripts.check_visual_surface_inventory import static_html_surface_paths
from scripts.check_visual_surface_inventory import EXPECTED_STATIC_HTML_SURFACES


CANONICAL_ASSET = "/static/css/visual-v2.css?v=20260826-elevation-v3"
CANONICAL_SCRIPT = "/static/js/visual-v2.js?v=20260826-elevation-v3"
CANONICAL_SIDEBAR = 'id="visual-sidebar"'


@pytest.fixture()
def visual_runtime_enabled():
    environments = (router.templates.env, email.templates.env, clean_admin.templates.env)
    previous = [environment.globals.get("foundation_ui_enabled") for environment in environments]
    previous_setting = settings.visual_foundation_enabled
    previous_email_session_local = email.SessionLocal
    settings.visual_foundation_enabled = True
    email.SessionLocal = router.SessionLocal
    for environment in environments:
        environment.globals["foundation_ui_enabled"] = True
    try:
        yield
    finally:
        email.SessionLocal = previous_email_session_local
        settings.visual_foundation_enabled = previous_setting
        for environment, value in zip(environments, previous, strict=True):
            environment.globals["foundation_ui_enabled"] = value


def test_every_jinja_runtime_has_global_visual_contract():
    for environment in (router.templates.env, email.templates.env, clean_admin.templates.env):
        assert "foundation_ui_enabled" in environment.globals
        assert environment.globals["visual_asset_version"] == "20260826-elevation-v3"


def test_static_v2_clean_html_inventory_is_complete_and_stable():
    paths = static_html_surface_paths(app)

    assert paths == EXPECTED_STATIC_HTML_SURFACES


def test_every_reachable_static_html_surface_uses_asset_and_sidebar(
    authenticated_client,
    visual_runtime_enabled,
):
    failures: list[str] = []
    for path in static_html_surface_paths(app):
        response = authenticated_client.get(path, follow_redirects=True)
        if response.status_code == 200 and response.headers.get("content-type", "").startswith("text/html"):
            if CANONICAL_ASSET not in response.text:
                failures.append(f"{path}: missing canonical asset")
            if CANONICAL_SCRIPT not in response.text:
                failures.append(f"{path}: missing canonical script")
            if CANONICAL_SIDEBAR not in response.text:
                failures.append(f"{path}: missing canonical sidebar")
            canonical_labels = (
                'data-nav-section="operation"',
                'data-nav-section="business"',
                'data-nav-section="system"',
            )
            if not all(label in response.text for label in canonical_labels):
                failures.append(f"{path}: missing canonical navigation groups")
            elif not (
                response.text.index(canonical_labels[0])
                < response.text.index(canonical_labels[1])
                < response.text.index(canonical_labels[2])
            ):
                failures.append(f"{path}: canonical navigation groups out of order")
        else:
            failures.append(f"{path}: unexpected status {response.status_code}")
    assert not failures, "\n".join(failures)


def test_visual_runtime_off_keeps_the_safe_legacy_fallback_on_all_template_engines(
    authenticated_client,
):
    environments = (router.templates.env, email.templates.env, clean_admin.templates.env)
    previous = [environment.globals.get("foundation_ui_enabled") for environment in environments]
    previous_setting = settings.visual_foundation_enabled
    previous_email_session_local = email.SessionLocal
    settings.visual_foundation_enabled = False
    email.SessionLocal = router.SessionLocal
    for environment in environments:
        environment.globals["foundation_ui_enabled"] = False
    try:
        responses = {
            path: authenticated_client.get(path, follow_redirects=True)
            for path in (
                "/v2-clean",
                "/v2-clean/tasks",
                "/v2-clean/email",
                "/v2-clean/admin/overview",
                "/v2-clean/documentation/triage",
                "/v2-clean/workshop",
                "/v2-clean/fleet",
            )
        }
    finally:
        email.SessionLocal = previous_email_session_local
        settings.visual_foundation_enabled = previous_setting
        for environment, value in zip(environments, previous, strict=True):
            environment.globals["foundation_ui_enabled"] = value

    for path, response in responses.items():
        assert response.status_code == 200, path
        assert CANONICAL_ASSET not in response.text, path
        assert CANONICAL_SCRIPT not in response.text, path
        assert CANONICAL_SIDEBAR in response.text, path


def test_sidebar_contains_approved_composition_and_independent_fallbacks():
    sidebar = (Path(__file__).resolve().parents[1] / "app/templates/_sidebar.html").read_text(
        encoding="utf-8"
    )

    assert "Stock e Compras" in sidebar
    assert "Vendas" in sidebar
    assert "/v2-clean/fleet/sales/proposals" in sidebar
    assert "/v2-clean/fleet/sales/opportunities" in sidebar
    assert "can_nav_sales and not can_nav_fleet" in sidebar
    assert "can_nav_stock and not can_nav_workshop" in sidebar


def test_sidebar_has_the_canonical_global_group_order():
    sidebar = (Path(__file__).resolve().parents[1] / "app/templates/_sidebar.html").read_text(
        encoding="utf-8"
    )

    operation = sidebar.index('data-nav-section="operation"')
    alerts = sidebar.index("Alertas personalizados", operation)
    tasks = sidebar.index("Centro de Tarefas", alerts)
    processes = sidebar.index("Centro de Processos", tasks)
    email = sidebar.index(">Email</a>", processes)
    business = sidebar.index('data-nav-section="business"', email)
    workshop = sidebar.index(">Oficina</summary>", business)
    stock = sidebar.index(">Stock e Compras</summary>", workshop)
    fleet = sidebar.index(">Frota</summary>", stock)
    sales = sidebar.index(">Vendas</summary>", fleet)
    partners = sidebar.index("Parceiros / Fornecedores", sales)
    documents = sidebar.index(">Documentação</summary>", partners)
    system = sidebar.index('data-nav-section="system"', documents)
    administration = sidebar.index(">Administração</a>", system)

    assert operation < alerts < tasks < processes < email < business
    assert business < workshop < stock < fleet < sales < partners < documents < system
    assert system < administration


def test_sidebar_keeps_independent_child_promotion_and_mobile_drawer_contract():
    sidebar = (Path(__file__).resolve().parents[1] / "app/templates/_sidebar.html").read_text(
        encoding="utf-8"
    )
    visual_script = (Path(__file__).resolve().parents[1] / "app/static/js/visual-v2.js").read_text(
        encoding="utf-8"
    )

    assert "can_nav_sales and not can_nav_fleet" in sidebar
    assert "can_nav_stock and not can_nav_workshop" in sidebar
    assert ">Stock e Compras</a>" in sidebar
    assert 'id="visual-sidebar"' in sidebar
    assert 'querySelector("#visual-sidebar")' in visual_script
    assert 'classList.toggle("visual-nav-open"' in visual_script
