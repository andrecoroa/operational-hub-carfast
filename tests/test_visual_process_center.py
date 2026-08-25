from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "clean_process_center.html"
CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
MATRIX = ROOT / "docs" / "evidence" / "visual-route-matrix" / "ROUTE_CONTENT_MATRIX.md"


def test_process_center_is_an_operational_workbench_not_a_legacy_catalog() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")

    for contract in (
        "process-command-page",
        "process-command-toolbar",
        "process-command-layout",
        "process-command-table",
        "Resumo da operação",
        'role="search"',
        'role="region"',
        'tabindex="0"',
        "Tarefas de gestão",
        "Abrir gestão completa",
    ):
        assert contract in source
    assert "Base limpa da nova experiência" not in source
    assert "sem puxar histórico antigo" not in source


def test_process_center_preserves_rbac_and_uses_local_table_overflow() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    css = CSS.read_text(encoding="utf-8")

    assert 'nav_has_permission(request, "management_center.read", "management_center.write", "admin.manage")' not in source
    assert 'nav_has_permission(request, "management_center.read", "management_center.write")' not in source
    assert ".process-command-table{overflow-x:auto}" in css
    assert ".process-command-layout{display:grid" in css
    assert "@media(max-width:1024px)" in css
    assert "@media(max-width:640px)" in css


def test_route_content_matrix_covers_every_canonical_surface_once() -> None:
    from scripts.check_visual_surface_inventory import EXPECTED_STATIC_HTML_SURFACES

    source = MATRIX.read_text(encoding="utf-8")
    for path in EXPECTED_STATIC_HTML_SURFACES:
        assert source.count(f"| `{path}` |") == 1, path
    assert "Shell: **PASS transversal em todas as 52 rotas**" in source
    assert "A presença da shell nunca altera por si só" in source
