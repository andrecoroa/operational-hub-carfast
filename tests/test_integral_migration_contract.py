from __future__ import annotations

import pytest
from sqlalchemy import MetaData, Table

import app.models  # noqa: F401
from app.models.base import Base
from app.platform.integral_migration_contract import (
    ADDITIVE_RELATIONS,
    IntegralMigrationContractError,
    contracted_inventories,
    source_metadata,
)


def test_versioned_inventories_are_exactly_162_to_166() -> None:
    source, target = contracted_inventories(Base.metadata)
    assert len(source) == 162
    assert len(target) == 166
    assert target - source == ADDITIVE_RELATIONS
    assert set(source_metadata(Base.metadata).tables) == source


def test_inventory_drift_fails_closed() -> None:
    drifted = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(drifted)
    Table("unexpected_relation", drifted)
    with pytest.raises(IntegralMigrationContractError, match="inventory drift"):
        contracted_inventories(drifted)
