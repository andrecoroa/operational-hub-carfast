from pathlib import Path

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app" / "templates"
MATRIX = ROOT / "docs" / "evidence" / "visual-route-matrix" / "ROUTE_CONTENT_MATRIX.md"


def test_residual_documentation_navigation_is_canonical_and_complete() -> None:
    nav = (TEMPLATES / "_clean_documentation_nav.html").read_text(encoding="utf-8")
    for href in (
        "/v2-clean/documentation/triage",
        "/v2-clean/documentation/treatment",
        "/v2-clean/documentation/by-vehicle",
        "/v2-clean/documentation/imports",
        "/v2-clean/documentation/archive",
        "/v2-clean/diagnostics",
        "/v2-clean/documents/ocr-validation",
    ):
        assert f'href="{href}"' in nav
    assert "/v2-clean/documentation/imports/invoices" not in nav
    assert 'nav_has_permission(request, "vehicles.read", "vehicles.write", "admin.manage")' in nav

    sidebar = (TEMPLATES / "_sidebar.html").read_text(encoding="utf-8")
    assert 'href="/v2-clean/documentation/imports">Importações</a>' in sidebar
    assert "/v2-clean/documentation/imports/invoices" not in sidebar


def test_document_only_profile_never_sees_fleet_guarded_destinations() -> None:
    environment = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    environment.globals["nav_has_permission"] = (
        lambda _request, *required: bool(set(required).intersection(_request["permissions"]))
    )
    template = environment.get_template("_clean_documentation_nav.html")

    document_only = template.render(
        request={"permissions": {"documents.read"}},
        doc_nav="archive",
    )
    assert "/v2-clean/documentation/archive" in document_only
    assert "/v2-clean/diagnostics" not in document_only
    assert "/v2-clean/documents/ocr-validation" not in document_only

    fleet_reader = template.render(
        request={"permissions": {"documents.read", "vehicles.read"}},
        doc_nav="diagnostics",
    )
    assert "/v2-clean/diagnostics" in fleet_reader
    assert "/v2-clean/documents/ocr-validation" in fleet_reader


def test_historical_document_centers_use_the_same_clean_workbench_context() -> None:
    expected = {
        "clean_document_import_center.html": 'doc_nav = "imports"',
        "clean_document_ocr_validation.html": 'doc_nav = "models"',
        "clean_document_new.html": 'doc_nav = ""',
    }
    for filename, active_contract in expected.items():
        source = (TEMPLATES / filename).read_text(encoding="utf-8")
        assert 'class="content clean-content doc-arch-page' in source
        assert active_contract in source
        assert '{% include "_clean_documentation_nav.html" %}' in source


def test_new_document_picker_uses_canonical_blue_teal_selection() -> None:
    source = (TEMPLATES / "clean_document_new.html").read_text(encoding="utf-8")
    assert "border-color: #176b87" in source
    assert "background: #eef8fa" in source
    assert "#b05f2f" not in source
    assert "#fff7ef" not in source


def test_ocr_calibration_keeps_wide_tables_inside_local_scroll() -> None:
    css = (ROOT / "app" / "static" / "css" / "app.css").read_text(encoding="utf-8")
    assert ".clean-doc-ocr-calibration-grid > *" in css
    assert ".clean-doc-ocr-calibration-card .clean-doc-table-wrap" in css
    assert "overflow-x: auto" in css

    template = (TEMPLATES / "clean_document_ocr_validation.html").read_text(encoding="utf-8")
    assert 'clean-doc-ocr-page' in template
    assert '<button type="submit" class="ui-button ui-button--primary">Filtrar</button>' in template
    assert ".clean-doc-ocr-page" in css
    assert "overflow-x: hidden" in css


def test_route_matrix_is_frozen_at_admin_setup_release_and_lists_only_real_residuals() -> None:
    source = MATRIX.read_text(encoding="utf-8")
    assert "46166d8713bcff8222c7f954fa36ae1b0f6f18cc" in source
    assert "Green 46166d87; 9/9, RBAC e responsive PASS" in source
    assert "tranche final A, ativa" in source
    assert "regressão transversal 53/53" in source
