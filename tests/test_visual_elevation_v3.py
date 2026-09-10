from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STOCK = (ROOT / "app/templates/clean_stock_articles.html").read_text(encoding="utf-8")
CSS = (ROOT / "app/static/css/visual-v2.css").read_text(encoding="utf-8")
ICONS = (ROOT / "app/static/icons/lucide-v3.svg").read_text(encoding="utf-8")


def test_stock_pilot_uses_dense_split_workbench_and_context_preview() -> None:
    assert "v3-stock-pilot" in STOCK
    assert "v3-stock-workspace" in STOCK
    assert "v3-stock-preview" in STOCK
    assert "data-v3-stock-row" in STOCK
    assert "data-v3-preview-detail" in STOCK
    assert "grid-template-columns: minmax(0,2fr) minmax(320px,1fr)" in CSS
    assert "height: 48px" in CSS
    assert "overflow-x: clip" in CSS


def test_stock_preview_preserves_existing_routes_and_bulk_action() -> None:
    assert 'action="/v2-clean/stock/articles/bulk-category"' in STOCK
    assert "'/v2-clean/stock/articles/'+row.dataset.id" in STOCK
    assert 'href="/v2-clean/stock/articles/{{ preview.article.id' in STOCK


def test_lucide_sprite_is_the_only_icon_contract_in_the_stock_pilot() -> None:
    assert "/static/icons/lucide-v3.svg#package" in STOCK
    assert "/static/icons/lucide-v3.svg#x" in STOCK
    assert "/static/icons/lucide-v3.svg#arrow-right" in STOCK
    for icon in ("package", "x", "arrow-right", "search", "filter", "plus", "tags"):
        assert f'id="{icon}"' in ICONS
    assert "fill: none" in CSS
    assert "stroke: currentColor" in CSS


def test_v3_pilot_palette_has_no_legacy_terracotta() -> None:
    v3 = CSS.split("/* Visual Elevation v3", 1)[1].lower()
    for legacy in ("#c64f32", "#92400e", "#9f470f"):
        assert legacy not in v3
    assert "--v3-blue-600: #1d5ed8" in v3
    assert "--v3-teal-600: #0e948a" in v3
