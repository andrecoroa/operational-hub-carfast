from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from app.documents import DOCUMENTS_MANIFEST
from app.models.stock import StockArticle, StockLocation, StockMovement
from app.partners import PARTNERS_MANIFEST
from app.platform.composer import CompositionResult, compose
from app.platform.manifest import ModuleState
from app.platform.registry import ManifestRegistry
from app.schemas.stock import StockMovementCreate
from app.stock_domain import STOCK_MANIFEST, StockFacade, StockReference, decide_stock_permission


def test_stock_references_are_stable_and_versioned() -> None:
    for kind in ("article", "movement", "order", "receipt"):
        reference = StockReference(kind, 9)
        assert StockReference.parse(reference.value) == reference


def test_ledger_facade_reconciles_entry_and_reversal(db_session) -> None:
    location = StockLocation(code="SYNTH", name="Sintético", active=True)
    article = StockArticle(internal_ref="SYN-1", name="Artigo sintético", unit="un.", active=True)
    db_session.add_all([location, article])
    db_session.flush()
    facade = StockFacade(db_session)
    movement = facade.record_movement(
        StockMovementCreate(
            article_id=article.id,
            movement_type="entry",
            quantity=Decimal("5"),
            unit_cost=Decimal("2.5"),
            to_location_id=location.id,
            reason="Entrada sintética",
        ),
        user_id=None,
    )
    assert facade.movement(StockReference("movement", movement.id)) is movement
    assert facade.balances([article.id])[0].quantity == Decimal("5.000")
    reversal = facade.reverse(movement, reason="Reversão sintética", user_id=None)
    db_session.commit()
    assert reversal.reverses_movement_id == movement.id
    assert facade.balances([article.id])[0].quantity == Decimal("0.000")


def test_stock_manifest_requires_partners_and_documents_but_not_workshop() -> None:
    registry = ManifestRegistry([PARTNERS_MANIFEST, DOCUMENTS_MANIFEST, STOCK_MANIFEST])
    assert registry.get("stock") is STOCK_MANIFEST
    assert "workshop" not in STOCK_MANIFEST.dependencies
    legacy = CompositionResult((), (), (), (), source="legacy")
    active = compose(
        legacy=legacy,
        registry=registry,
        module_states={
            "partners": ModuleState.ACTIVE,
            "documents": ModuleState.ACTIVE,
            "stock": ModuleState.ACTIVE,
        },
        permission_codes={"stock.articles.read"},
        enabled=True,
    )
    assert [item.code for item in active.navigation] == ["stock.articles"]


def test_stock_permissions_preserve_effective_access() -> None:
    assert decide_stock_permission("stock.ledger.read", {"stock.read"}).allowed
    assert decide_stock_permission("stock.ledger.write", {"stock.operate"}).allowed
    assert not decide_stock_permission("stock.ledger.write", {"stock.read"}).allowed
    assert not decide_stock_permission("stock.unknown", {"admin.manage"}).allowed


def test_priority_consumers_use_domain_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    web = (root / "app/web/stock.py").read_text(encoding="utf-8")
    service = (root / "app/services/stock.py").read_text(encoding="utf-8")
    package = (root / "app/stock_domain/__init__.py").read_text(encoding="utf-8")
    assert "from app.models.workshop_phased import" not in web
    assert "stock_domain.workshop_adapter" in web
    assert "PartnersFacade(db).resolve_supplier" in service
    assert "DocumentManagementFacade(db).record_event" in service
    assert "workshop_adapter" not in package


def test_existing_ledger_storage_and_links_remain_unchanged() -> None:
    assert StockArticle.__tablename__ == "stock_articles"
    assert StockMovement.__tablename__ == "stock_movements"
    foreign_keys = {
        foreign_key.target_fullname
        for table in StockMovement.metadata.tables.values()
        for column in table.columns
        for foreign_key in column.foreign_keys
    }
    assert "stock_articles.id" in foreign_keys
    assert "stock_suppliers.id" in foreign_keys
    assert "documents.id" in foreign_keys


def test_touched_stock_surfaces_keep_visual_foundation_gated() -> None:
    root = Path(__file__).resolve().parents[1]
    dashboard = (root / "app/templates/clean_stock_dashboard.html").read_text(encoding="utf-8")
    requests = (root / "app/templates/clean_stock_workshop_requests.html").read_text(
        encoding="utf-8"
    )
    assert "foundation_ui_enabled" in dashboard
    assert "ui-page-shell" in dashboard
    assert "foundation_ui_enabled" in requests
    assert "ui-table-container" in requests
