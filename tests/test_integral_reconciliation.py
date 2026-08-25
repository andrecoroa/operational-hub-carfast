from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import (
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
)

from app.platform.integral_reconciliation import (
    ForeignKeyEvidence,
    IntegralManifest,
    IntegralReconciliationError,
    RelationEvidence,
    build_database_evidence,
    build_storage_evidence,
    compare_manifests,
    compare_migrated_manifests,
)
from scripts.check_clean_install import (
    CLEAN_INSTALL_REFERENCE_TABLES,
    DECLARED_TABLES,
    OPERATIONAL_TABLES,
)


def relation(name: str = "users") -> RelationEvidence:
    return RelationEvidence(
        name=name,
        row_count=2,
        schema_sha256="a" * 64,
        primary_key_sha256="b" * 64,
        rows_sha256="c" * 64,
        foreign_keys=(ForeignKeyEvidence(f"{name}(role_id)->roles(id)", 0),),
    )


def manifest(tmp_path: Path) -> IntegralManifest:
    storage = build_storage_evidence(tmp_path)
    return IntegralManifest("release", "source:test", (relation(),), storage)


def test_identical_database_and_storage_evidence_reconciles(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "document.bin").write_bytes(b"fixture")
    source = manifest(tmp_path)
    assert compare_manifests(source, replace(source, database_label="target:test")) == ()


@pytest.mark.parametrize(
    "changed,expected",
    [
        (replace(relation(), row_count=3), "relation.users"),
        (replace(relation(), rows_sha256="d" * 64), "relation.users"),
        (
            replace(relation(), foreign_keys=(ForeignKeyEvidence("users(role_id)->roles(id)", 1),)),
            "relation.users",
        ),
    ],
)
def test_database_difference_fails_closed(
    tmp_path: Path, changed: RelationEvidence, expected: str
) -> None:
    source = manifest(tmp_path)
    target = replace(source, database_label="target:test", relations=(changed,))
    assert compare_manifests(source, target) == (expected,)


def test_missing_or_changed_storage_object_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "document.bin").write_bytes(b"before")
    source = manifest(tmp_path)
    (tmp_path / "document.bin").write_bytes(b"after")
    target = manifest(tmp_path)
    assert compare_manifests(source, target) == ("storage.document.bin",)


def test_storage_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"fixture")
    link = tmp_path / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(IntegralReconciliationError, match="symlink"):
        build_storage_evidence(tmp_path)


def test_release_mismatch_blocks_reconciliation(tmp_path: Path) -> None:
    source = manifest(tmp_path)
    target = replace(source, release_sha="other", database_label="target:test")
    assert compare_manifests(source, target) == ("release_sha",)


def test_additive_migration_preserves_source_and_accepts_only_declared_relations(
    tmp_path: Path,
) -> None:
    source = manifest(tmp_path)
    target = replace(
        source,
        release_sha="target-release",
        database_label="target:test",
        relations=(relation(), relation("module_definitions")),
    )
    assert compare_migrated_manifests(
        source, target, frozenset({"module_definitions"})
    ) == ()
    unexpected = replace(target, relations=target.relations + (relation("unexpected"),))
    assert compare_migrated_manifests(
        source, unexpected, frozenset({"module_definitions"})
    ) == ("relation.additive_inventory",)


def test_database_evidence_hashes_rows_and_counts_orphans() -> None:
    metadata = MetaData()
    roles = Table("roles", metadata, Column("id", Integer, primary_key=True))
    users = Table(
        "users",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("role_id", ForeignKey("roles.id"), nullable=False),
        Column("name", String, nullable=False),
    )
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(roles.insert(), [{"id": 1}])
        connection.execute(
            users.insert(),
            [
                {"id": 10, "role_id": 1, "name": "fixture"},
                {"id": 11, "role_id": 999, "name": "orphan"},
            ],
        )
        first = build_database_evidence(
            connection, metadata, schema=None, minimum_relations=2
        )
        second = build_database_evidence(
            connection, metadata, schema=None, minimum_relations=2
        )
    assert first == second
    users_evidence = next(item for item in first if item.name == "users")
    assert users_evidence.row_count == 2
    assert users_evidence.foreign_keys[0].orphan_count == 1
    assert len(users_evidence.rows_sha256) == 64


def test_clean_install_classifies_every_declared_relation() -> None:
    assert len(DECLARED_TABLES) == 166
    assert set(OPERATIONAL_TABLES).isdisjoint(CLEAN_INSTALL_REFERENCE_TABLES)
    assert set(OPERATIONAL_TABLES) | CLEAN_INSTALL_REFERENCE_TABLES == DECLARED_TABLES
