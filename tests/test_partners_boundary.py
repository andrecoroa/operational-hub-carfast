from __future__ import annotations

from pathlib import Path

from sqlalchemy import func, select

from app.core.config import settings
from app.models import Base
from app.models.stock import StockSupplier as LegacyStockSupplier
from app.partners import (
    PARTNERS_MANIFEST,
    PartnerRecord,
    PartnerReference,
    PartnersFacade,
    decide_partner_permission,
)
from app.platform.composer import CompositionResult, compose
from app.platform.manifest import ModuleState
from app.platform.registry import ManifestRegistry


def test_partner_reference_is_stable_and_versioned() -> None:
    reference = PartnerReference(42)
    assert reference.value == "partner:v1:42"
    assert PartnerReference.parse(reference.value) == reference


def test_compatibility_record_keeps_same_mapper_table_and_ids(db_session) -> None:
    record = PartnerRecord(name="Parceiro sintético", tax_id="PT-PARTNER-1", active=True)
    db_session.add(record)
    db_session.commit()

    assert PartnerRecord is LegacyStockSupplier
    assert PartnerRecord.__tablename__ == "stock_suppliers"
    assert db_session.get(LegacyStockSupplier, record.id) is record
    assert PartnersFacade(db_session).get_record(PartnerReference(record.id)) is record


def test_facade_summary_and_authorized_historical_degradation(db_session) -> None:
    record = PartnerRecord(
        name="Oficina Parceira",
        legal_name="Oficina Parceira, Lda.",
        tax_id="PT-PARTNER-2",
        email="sandbox@example.invalid",
        active=False,
    )
    db_session.add(record)
    db_session.commit()
    facade = PartnersFacade(db_session)
    snapshot = facade.summary(record).snapshot()

    restored = facade.historical_summary(snapshot, can_read_partners=True)
    assert restored is not None
    assert restored.reference.id == record.id
    assert restored.display_name == record.name
    assert facade.historical_summary(snapshot, can_read_partners=False) is None


def test_partner_manifest_and_composer_are_still_gated() -> None:
    PARTNERS_MANIFEST.validate()
    registry = ManifestRegistry([PARTNERS_MANIFEST])
    legacy = CompositionResult((), (), (), (), source="legacy")
    assert (
        compose(
            legacy=legacy,
            registry=registry,
            module_states={"partners": ModuleState.ACTIVE},
            permission_codes={"partners.records.read"},
        )
        is legacy
    )
    active = compose(
        legacy=legacy,
        registry=registry,
        module_states={"partners": ModuleState.ACTIVE},
        permission_codes={"partners.records.read"},
        enabled=True,
    )
    assert [item.code for item in active.navigation] == ["partners.records"]


def test_canonical_permissions_exactly_map_current_effective_access() -> None:
    assert decide_partner_permission("partners.records.read", {"stock.read"}).allowed is True
    assert decide_partner_permission("partners.records.read", {"suppliers.read"}).allowed is True
    assert decide_partner_permission("partners.records.update", {"suppliers.write"}).allowed is True
    assert decide_partner_permission("partners.records.update", {"stock.manage"}).allowed is False
    assert decide_partner_permission("partners.records.configure", {"admin.manage"}).allowed is True
    assert decide_partner_permission("partners.records.unknown", {"admin.manage"}).allowed is False


def test_all_existing_supplier_foreign_keys_remain_reconcilable() -> None:
    supplier_targets = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                if foreign_key.target_fullname == "stock_suppliers.id":
                    supplier_targets.append((table.name, column.name))
    assert len(supplier_targets) >= 9
    assert ("supplier_contacts", "supplier_id") in supplier_targets
    assert ("email_templates", "supplier_id") in supplier_targets
    assert ("stock_purchase_orders", "supplier_id") in supplier_targets


def test_priority_consumers_import_partners_boundary_not_stock_owner() -> None:
    root = Path(__file__).resolve().parents[1]
    consumers = (
        "app/web/email.py",
        "app/web/suppliers.py",
        "app/web/stock.py",
        "app/services/stock.py",
        "app/services/bootstrap.py",
    )
    for relative in consumers:
        source = (root / relative).read_text(encoding="utf-8")
        assert "from app.models.stock import StockSupplier" not in source
        assert "from app.partners.compat import StockSupplier" in source


def test_supplier_pages_remain_compatible_and_use_gated_visual_primitives(
    authenticated_client, db_session, monkeypatch
) -> None:
    record = PartnerRecord(name="Fornecedor Visual Sintético", active=True)
    db_session.add(record)
    db_session.commit()
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)

    listing = authenticated_client.get("/v2-clean/suppliers")
    detail = authenticated_client.get(f"/v2-clean/suppliers/{record.id}")
    assert listing.status_code == detail.status_code == 200
    assert "/v2-clean/suppliers/" + str(record.id) in listing.text
    assert "ui-filter-bar" in listing.text
    assert "ui-table-container" in listing.text
    assert "ui-foundation" in detail.text
    assert "As relações existentes continuam a usar o mesmo ID" in detail.text
    assert db_session.scalar(select(func.count()).select_from(PartnerRecord)) >= 1
