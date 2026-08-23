"""Versioned 162-source to 166-target migration contract."""

from __future__ import annotations

import hashlib
import json

from sqlalchemy import MetaData, inspect, text
from sqlalchemy.engine import Connection

SOURCE_RELEASE_SHA = "58a150c701221b64c43bd14fcb671683f3722ebe"
SOURCE_REVISION = "ffae1f2a3b4c"
TARGET_RELEASE_SHA = "9c691d332c80dff4a1d529d7f0d4ef16a71add46"
TARGET_REVISION = "fff37f8a9b0d"
SOURCE_INVENTORY_SHA256 = "8c58213167886700194abe4ad094f060d875d8883f3faafc4d56acf154eb225f"
TARGET_INVENTORY_SHA256 = "411ff98d293ddcdc8f1f94d1a99be6aaa02641306294a282ba12c4b970ad292f"
ADDITIVE_RELATIONS = frozenset(
    {
        "installation_modules",
        "module_capabilities",
        "module_definitions",
        "module_dependencies",
    }
)
EXPECTED_ADDITIVE_COUNTS = {
    "installation_modules": 1,
    "module_capabilities": 0,
    "module_definitions": 1,
    "module_dependencies": 0,
}
EXPECTED_INDEXES = {
    "installation_modules": {"ix_installation_modules_module_code"},
    "module_capabilities": {"ix_module_capabilities_module_code"},
    "module_definitions": set(),
    "module_dependencies": {
        "ix_module_dependencies_dependency_code",
        "ix_module_dependencies_module_code",
    },
}
EXPECTED_COLUMNS = {
    "module_definitions": {"code", "version", "name", "required", "created_at"},
    "module_capabilities": {"id", "module_code", "code", "independently_switchable"},
    "module_dependencies": {
        "id",
        "module_code",
        "dependency_code",
        "minimum_version",
    },
    "installation_modules": {
        "id",
        "installation_key",
        "module_code",
        "state",
        "configured_version",
        "configuration",
        "changed_at",
    },
}
EXPECTED_PRIMARY_KEYS = {
    "installation_modules": ("id",),
    "module_capabilities": ("id",),
    "module_definitions": ("code",),
    "module_dependencies": ("id",),
}
EXPECTED_UNIQUES = {
    "installation_modules": {("installation_key", "module_code")},
    "module_capabilities": {("module_code", "code")},
    "module_definitions": set(),
    "module_dependencies": {("module_code", "dependency_code")},
}
EXPECTED_FOREIGN_KEYS = {
    "installation_modules": {("module_code", "module_definitions", "code", "RESTRICT")},
    "module_capabilities": {("module_code", "module_definitions", "code", "CASCADE")},
    "module_definitions": set(),
    "module_dependencies": {
        ("dependency_code", "module_definitions", "code", "RESTRICT"),
        ("module_code", "module_definitions", "code", "CASCADE"),
    },
}


class IntegralMigrationContractError(RuntimeError):
    pass


def inventory_digest(names: set[str] | frozenset[str]) -> str:
    encoded = json.dumps(sorted(names), separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def contracted_inventories(metadata: MetaData) -> tuple[frozenset[str], frozenset[str]]:
    target = frozenset(metadata.tables)
    source = target - ADDITIVE_RELATIONS
    if len(source) != 162 or inventory_digest(source) != SOURCE_INVENTORY_SHA256:
        raise IntegralMigrationContractError("versioned 162-relation source inventory drift")
    if len(target) != 166 or inventory_digest(target) != TARGET_INVENTORY_SHA256:
        raise IntegralMigrationContractError("versioned 166-relation target inventory drift")
    return source, target


def source_metadata(metadata: MetaData) -> MetaData:
    source, _target = contracted_inventories(metadata)
    result = MetaData()
    for name in sorted(source):
        metadata.tables[name].to_metadata(result)
    return result


def validate_database_phase(
    connection: Connection,
    metadata: MetaData,
    phase: str,
    *,
    validate_additive: bool = True,
) -> None:
    source, target = contracted_inventories(metadata)
    expected = source if phase in {"source", "staging"} else target
    expected_revision = SOURCE_REVISION if phase in {"source", "staging"} else TARGET_REVISION
    actual = frozenset(inspect(connection).get_table_names(schema="public")) - {
        "alembic_version"
    }
    if actual != expected:
        raise IntegralMigrationContractError(
            f"{phase} relation inventory mismatch; missing={sorted(expected-actual)}, "
            f"unexpected={sorted(actual-expected)}"
        )
    revisions = tuple(
        connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num"))
        .scalars()
        .all()
    )
    if revisions != (expected_revision,):
        raise IntegralMigrationContractError(
            f"{phase} revision mismatch; expected={expected_revision}, actual={revisions}"
        )
    if phase == "target" and validate_additive:
        validate_additive_contract(connection)


def validate_additive_contract(connection: Connection) -> None:
    inspector = inspect(connection)
    for relation in sorted(ADDITIVE_RELATIONS):
        columns = {item["name"] for item in inspector.get_columns(relation, schema="public")}
        if columns != EXPECTED_COLUMNS[relation]:
            raise IntegralMigrationContractError(
                f"additive column contract mismatch for {relation}: {sorted(columns)}"
            )
        primary_key = tuple(
            inspector.get_pk_constraint(relation, schema="public")["constrained_columns"]
        )
        if primary_key != EXPECTED_PRIMARY_KEYS[relation]:
            raise IntegralMigrationContractError(
                f"additive primary-key contract mismatch for {relation}: {primary_key}"
            )
        uniques = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(relation, schema="public")
        }
        if uniques != EXPECTED_UNIQUES[relation]:
            raise IntegralMigrationContractError(
                f"additive unique contract mismatch for {relation}: {sorted(uniques)}"
            )
        foreign_keys = {
            (
                item["constrained_columns"][0],
                item["referred_table"],
                item["referred_columns"][0],
                item.get("options", {}).get("ondelete", "NO ACTION"),
            )
            for item in inspector.get_foreign_keys(relation, schema="public")
        }
        if foreign_keys != EXPECTED_FOREIGN_KEYS[relation]:
            raise IntegralMigrationContractError(
                f"additive foreign-key contract mismatch for {relation}: "
                f"{sorted(foreign_keys)}"
            )
        count = int(connection.execute(text(f'SELECT count(*) FROM "{relation}"')).scalar_one())
        if count != EXPECTED_ADDITIVE_COUNTS[relation]:
            raise IntegralMigrationContractError(
                f"additive seed count mismatch for {relation}: {count}"
            )
        indexes = {
            item["name"]
            for item in inspector.get_indexes(relation, schema="public")
            if not item.get("duplicates_constraint")
        }
        if indexes != EXPECTED_INDEXES[relation]:
            raise IntegralMigrationContractError(
                f"additive index contract mismatch for {relation}: {sorted(indexes)}"
            )
    checks = {item["name"] for item in inspector.get_check_constraints("installation_modules")}
    if checks != {"ck_installation_modules_installation_module_state"}:
        raise IntegralMigrationContractError(
            f"installation_modules check contract mismatch: {sorted(checks)}"
        )
    core = connection.execute(
        text("SELECT code, version, name, required FROM module_definitions")
    ).one()
    if tuple(core) != ("core", "1", "Core", True):
        raise IntegralMigrationContractError("module_definitions seed contract mismatch")
    installation = connection.execute(
        text(
            "SELECT installation_key, module_code, state, configured_version, configuration "
            "FROM installation_modules"
        )
    ).one()
    if tuple(installation[:4]) != ("default", "core", "active", "1") or installation[4] != {}:
        raise IntegralMigrationContractError("installation_modules seed contract mismatch")
