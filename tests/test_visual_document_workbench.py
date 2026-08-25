from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "app" / "templates" / "clean_documentation_triage.html"
CSS = ROOT / "app" / "static" / "css" / "visual-v2.css"
JS = ROOT / "app" / "static" / "js" / "visual-v2.js"
ROUTER = ROOT / "app" / "web" / "router.py"
BASE = ROOT / "app" / "templates" / "base.html"


def test_document_workbench_rebuilds_canonical_three_pane_composition() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    for contract in (
        "visual-document-workbench",
        "visual-document-context",
        "visual-document-grid",
        "visual-document-queue",
        "visual-document-preview",
        "visual-document-review",
        "visual-document-confidence",
        "visual-document-matching",
        "visual-document-associate",
        "visual-document-history",
        'title="Documento selecionado"',
        "Guardar decisão",
        "Ver auditoria completa",
    ):
        assert contract in source


def test_document_workbench_keeps_real_routes_data_and_decision_form() -> None:
    source = TEMPLATE.read_text(encoding="utf-8")
    assert 'src="{{ selected_row.preview_href }}"' in source
    assert 'href="{{ selected_row.detail_href }}"' in source
    assert 'action="/v2-clean/documentation/triage/{{ selected_row.document.id }}"' in source
    assert 'name="destination" required' in source
    assert 'name="decision_reason"' in source
    assert "foundation_ui_enabled" in source
    assert "doc-arch-table" in source  # feature-flag OFF fallback remains usable
    assert 'class="doc-arch-filters"' in source
    assert "Triar documento selecionado" in source
    assert '&selected={{ row.document.id }}">Triar</a>' in source


def test_document_selection_is_server_derived_and_defaults_to_first_row() -> None:
    source = ROUTER.read_text(encoding="utf-8")
    assert "selected: int | None = None" in source
    assert 'view: str = "queue"' in source
    assert 'row["document"].id == selected' in source
    assert 'rows[0] if rows else None' in source
    assert '"selected_row": selected_row' in source
    assert '"foundation_ui_enabled": settings.visual_foundation_enabled' in source


def test_document_workbench_responsive_contract() -> None:
    css = CSS.read_text(encoding="utf-8")
    for contract in (
        ".visual-document-grid { display: grid; min-height: 640px;",
        "grid-template-columns: minmax(280px,24%) minmax(410px,1fr) minmax(330px,30%);",
        ".visual-document-preview iframe { width: 100%; height: 100%;",
        "@media (max-width:1199px)",
        ".visual-document-review { grid-column: 1 / -1;",
        "@media (max-width:767px)",
        ".visual-document-grid { display: block; min-height: 0; }",
        ".visual-document-preview iframe { min-height: 470px; }",
        "@media (max-width:1100px)",
        ".visual-document-actions > * { min-height: 44px;",
    ):
        assert contract in css


def test_document_asset_is_cache_busted() -> None:
    assert "visual-v2.css?v=20260825-documents1" in BASE.read_text(encoding="utf-8")


def test_document_views_preserve_return_context_and_scroll() -> None:
    template = TEMPLATE.read_text(encoding="utf-8")
    script = JS.read_text(encoding="utf-8")
    assert "return_context=queue" in template
    assert "return_context=preview" in template
    assert "data-document-view-link" in template
    assert "carfast-document-scroll:" in script
    assert "sessionStorage.setItem(documentViewKey" in script
    assert "8 * 60 * 60 * 1000" in script
    assert "document_return_context" in template
