"""Fail-closed evidence for integral database and storage rehearsals."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import MetaData, Table, and_, func, inspect, select
from sqlalchemy.engine import Connection

MANIFEST_VERSION = 1
MINIMUM_RELATION_INVENTORY = 163


class IntegralReconciliationError(RuntimeError):
    """An invariant required for a zero-tolerance rehearsal was violated."""


@dataclass(frozen=True, slots=True)
class ForeignKeyEvidence:
    code: str
    orphan_count: int


@dataclass(frozen=True, slots=True)
class RelationEvidence:
    name: str
    row_count: int
    schema_sha256: str
    primary_key_sha256: str
    rows_sha256: str
    foreign_keys: tuple[ForeignKeyEvidence, ...]


@dataclass(frozen=True, slots=True)
class StorageEvidence:
    path: str
    size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class IntegralManifest:
    release_sha: str
    database_label: str
    relations: tuple[RelationEvidence, ...]
    storage: tuple[StorageEvidence, ...]
    version: int = MANIFEST_VERSION

    def payload(self) -> dict[str, Any]:
        return asdict(self)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def _canonical(value: Any) -> Any:
    if value is None:
        return ["null"]
    if type(value) is bool:
        return ["bool", value]
    if isinstance(value, int):
        return ["int", str(value)]
    if isinstance(value, Decimal):
        return ["decimal", str(value)]
    if isinstance(value, float):
        return ["float", value.hex()]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, bytes):
        return ["bytes", len(value), hashlib.sha256(value).hexdigest()]
    if isinstance(value, (datetime, date, time)):
        return [type(value).__name__, value.isoformat()]
    if isinstance(value, UUID):
        return ["uuid", str(value)]
    if isinstance(value, Mapping):
        return ["mapping", {str(key): _canonical(item) for key, item in value.items()}]
    if isinstance(value, (list, tuple)):
        return ["sequence", [_canonical(item) for item in value]]
    raise IntegralReconciliationError(f"unsupported database value type: {type(value).__name__}")


def _digest_rows(rows: Iterable[Mapping[str, Any]], columns: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        encoded = _json_bytes([[column, _canonical(row[column])] for column in columns])
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _schema_payload(table: Table) -> dict[str, Any]:
    return {
        "name": table.name,
        "columns": [
            {
                "name": column.name,
                "type": str(column.type),
                "nullable": column.nullable,
                "primary_key": column.primary_key,
            }
            for column in table.columns
        ],
        "foreign_keys": sorted(
            (
                {
                "local": tuple(element.parent.name for element in constraint.elements),
                "remote_table": constraint.referred_table.name,
                "remote": tuple(element.column.name for element in constraint.elements),
                }
                for constraint in table.foreign_key_constraints
            ),
            key=lambda item: (item["local"], item["remote_table"], item["remote"]),
        ),
    }


def _foreign_key_evidence(connection: Connection, table: Table) -> tuple[ForeignKeyEvidence, ...]:
    evidence: list[ForeignKeyEvidence] = []
    constraints = sorted(
        table.foreign_key_constraints,
        key=lambda item: tuple(
            (element.parent.name, element.target_fullname) for element in item.elements
        ),
    )
    for constraint in constraints:
        remote = constraint.referred_table.alias(f"remote_{table.name}_{len(evidence)}")
        local_columns = [element.parent for element in constraint.elements]
        remote_columns = [remote.c[element.column.name] for element in constraint.elements]
        join_condition = and_(
            *(local == target for local, target in zip(local_columns, remote_columns, strict=True))
        )
        populated = and_(*(column.is_not(None) for column in local_columns))
        missing = and_(*(column.is_(None) for column in remote_columns))
        query = (
            select(func.count())
            .select_from(table.outerjoin(remote, join_condition))
            .where(populated, missing)
        )
        local_names = ",".join(column.name for column in local_columns)
        remote_names = ",".join(element.column.name for element in constraint.elements)
        code = f"{table.name}({local_names})->{constraint.referred_table.name}({remote_names})"
        evidence.append(ForeignKeyEvidence(code, int(connection.execute(query).scalar_one())))
    return tuple(evidence)


def build_database_evidence(
    connection: Connection,
    declared_metadata: MetaData,
    *,
    batch_size: int = 500,
    schema: str | None = "public",
    minimum_relations: int = MINIMUM_RELATION_INVENTORY,
) -> tuple[RelationEvidence, ...]:
    declared = tuple(sorted(declared_metadata.tables))
    if len(declared) < minimum_relations:
        raise IntegralReconciliationError(
            f"relation inventory shrank below {minimum_relations}: {len(declared)}"
        )
    actual = set(inspect(connection).get_table_names(schema=schema)) - {"alembic_version"}
    if actual != set(declared):
        missing = sorted(set(declared) - actual)
        unexpected = sorted(actual - set(declared))
        raise IntegralReconciliationError(
            f"database relation inventory mismatch; missing={missing}, unexpected={unexpected}"
        )

    result: list[RelationEvidence] = []
    for name in declared:
        table = declared_metadata.tables[name]
        columns = tuple(column.name for column in table.columns)
        primary_key = tuple(column.name for column in table.primary_key.columns)
        if not primary_key:
            raise IntegralReconciliationError(f"relation has no deterministic primary key: {name}")
        ordered = select(table).order_by(*(table.c[column] for column in primary_key))
        rows = connection.execution_options(stream_results=True, yield_per=batch_size).execute(
            ordered
        )
        row_digest = hashlib.sha256()
        pk_digest = hashlib.sha256()
        row_count = 0
        for row in rows.mappings():
            row_count += 1
            encoded = _json_bytes([[column, _canonical(row[column])] for column in columns])
            row_digest.update(len(encoded).to_bytes(8, "big"))
            row_digest.update(encoded)
            encoded_pk = _json_bytes([[column, _canonical(row[column])] for column in primary_key])
            pk_digest.update(len(encoded_pk).to_bytes(8, "big"))
            pk_digest.update(encoded_pk)
        schema_sha256 = hashlib.sha256(_json_bytes(_schema_payload(table))).hexdigest()
        result.append(
            RelationEvidence(
                name=name,
                row_count=row_count,
                schema_sha256=schema_sha256,
                primary_key_sha256=pk_digest.hexdigest(),
                rows_sha256=row_digest.hexdigest(),
                foreign_keys=_foreign_key_evidence(connection, table),
            )
        )
    return tuple(result)


def build_storage_evidence(root: Path) -> tuple[StorageEvidence, ...]:
    resolved_root = root.resolve(strict=True)
    if not resolved_root.is_dir():
        raise IntegralReconciliationError("storage root must be a directory")
    evidence: list[StorageEvidence] = []
    for path in sorted(resolved_root.rglob("*")):
        if path.is_symlink():
            raise IntegralReconciliationError(f"storage symlink is forbidden: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise IntegralReconciliationError(f"unsupported storage object: {path}")
        relative = path.relative_to(resolved_root).as_posix()
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        evidence.append(StorageEvidence(relative, size, digest.hexdigest()))
    return tuple(evidence)


def compare_manifests(source: IntegralManifest, target: IntegralManifest) -> tuple[str, ...]:
    differences: list[str] = []
    if source.version != target.version:
        differences.append("manifest.version")
    if source.release_sha != target.release_sha:
        differences.append("release_sha")
    source_relations = {item.name: item for item in source.relations}
    target_relations = {item.name: item for item in target.relations}
    for name in sorted(set(source_relations) | set(target_relations)):
        if source_relations.get(name) != target_relations.get(name):
            differences.append(f"relation.{name}")
    source_storage = {item.path: item for item in source.storage}
    target_storage = {item.path: item for item in target.storage}
    for path in sorted(set(source_storage) | set(target_storage)):
        if source_storage.get(path) != target_storage.get(path):
            differences.append(f"storage.{path}")
    return tuple(differences)


def load_manifest(path: Path) -> IntegralManifest:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if set(payload) != {"version", "release_sha", "database_label", "relations", "storage"}:
        raise IntegralReconciliationError("invalid integral manifest shape")
    relations = tuple(
        RelationEvidence(
            name=item["name"],
            row_count=item["row_count"],
            schema_sha256=item["schema_sha256"],
            primary_key_sha256=item["primary_key_sha256"],
            rows_sha256=item["rows_sha256"],
            foreign_keys=tuple(ForeignKeyEvidence(**fk) for fk in item["foreign_keys"]),
        )
        for item in payload["relations"]
    )
    storage = tuple(StorageEvidence(**item) for item in payload["storage"])
    return IntegralManifest(
        version=payload["version"],
        release_sha=payload["release_sha"],
        database_label=payload["database_label"],
        relations=relations,
        storage=storage,
    )


def write_manifest(path: Path, manifest: IntegralManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest.payload(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)
