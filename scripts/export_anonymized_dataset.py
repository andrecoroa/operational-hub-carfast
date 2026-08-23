"""Production-side anonymization boundary. Do not run without capture approval."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any, BinaryIO

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.platform.anonymized_stream import FIELD_MAP, EphemeralSynthesizer, stream_jsonl
from app.platform.capture_authorization import AuthorizationRejected, verify_and_consume

SCHEMA_CONTRACT_VERSION = 1
TEXT_TYPES = frozenset({"character varying", "character", "text"})
INTEGER_TYPES = frozenset({"integer", "bigint", "smallint"})
JSON_TYPES = frozenset({"json", "jsonb"})


@dataclass(frozen=True)
class SourceColumn:
    types: frozenset[str]
    nullable: bool


NON_NULL_SOURCE = {
    "users": {"id", "active", "email", "name", "password_hash"},
    "stock_suppliers": {"id", "active", "name"},
    "vehicles": {"id", "active"},
    "tasks": {"id", "status", "title"},
    "management_processes": {
        "id",
        "process_type_id",
        "internal_reference",
        "title",
        "status",
        "phase",
        "priority",
    },
    "email_messages": {"id", "thread_id", "sender", "subject"},
    "documents": {"id", "original_name", "file_name", "storage_path", "status"},
    "audit_log": {"id", "action"},
}
BOOLEAN_SOURCE = {("users", "active"), ("stock_suppliers", "active"), ("vehicles", "active")}
JSON_SOURCE = {
    ("management_processes", "raw_summary_json"),
    ("email_messages", "recipients_json"),
    ("email_messages", "cc_json"),
    ("email_messages", "bcc_json"),
    ("email_messages", "headers_json"),
    ("email_messages", "template_snapshot_json"),
    ("audit_log", "before_json"),
    ("audit_log", "after_json"),
}
INTEGER_SOURCE = {
    (table, field)
    for table, rules in FIELD_MAP.items()
    for field, rule in rules.items()
    # Infer technical identifiers from the explicit transformation contract,
    # never from a name suffix: tax_id is identifying text, not a foreign key.
    if (rule.action == "surrogate" or field == "file_size")
    and (table, field) != ("audit_log", "entity_id")
}


def _source_contract() -> dict[str, dict[str, SourceColumn]]:
    contract: dict[str, dict[str, SourceColumn]] = {}
    for table, rules in FIELD_MAP.items():
        contract[table] = {}
        for field in rules:
            key = (table, field)
            types = (
                {"boolean"}
                if key in BOOLEAN_SOURCE
                else JSON_TYPES
                if key in JSON_SOURCE
                else INTEGER_TYPES
                if key in INTEGER_SOURCE
                else TEXT_TYPES
            )
            contract[table][field] = SourceColumn(
                frozenset(types), field not in NON_NULL_SOURCE[table]
            )
    return contract


SOURCE_SCHEMA_CONTRACT = _source_contract()


def schema_preflight(connection: Any) -> None:
    """Inspect metadata only and abort before any row cursor when the pilot schema drifts."""
    for table, columns in SOURCE_SCHEMA_CONTRACT.items():
        rows = connection.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (table,),
        ).fetchall()
        actual = {row[0]: (row[1], row[2] == "YES") for row in rows}
        missing = set(columns) - set(actual)
        if missing:
            raise RuntimeError(f"schema preflight failed for {table}: missing {sorted(missing)}")
        for field, expected in columns.items():
            actual_type, actual_nullable = actual[field]
            if actual_type not in expected.types or actual_nullable != expected.nullable:
                raise RuntimeError(
                    f"schema preflight v{SCHEMA_CONTRACT_VERSION} failed for "
                    f"{table}.{field}: type/nullability drift"
                )


def batched_rows(cursor: Any, batch_size: int) -> Iterator[Mapping[str, Any]]:
    while rows := cursor.fetchmany(batch_size):
        yield from rows


def export_chunks(connection: Any, batch_size: int, key: bytes) -> Iterator[bytes]:
    synth = EphemeralSynthesizer(key)
    connection.execute("SET TRANSACTION READ ONLY")
    connection.execute("SET LOCAL statement_timeout = '30s'")
    connection.execute("SET LOCAL lock_timeout = '2s'")
    schema_preflight(connection)
    for table, rules in FIELD_MAP.items():
        columns = tuple(rules)
        query = sql.SQL("SELECT {} FROM {} ORDER BY id").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table)
        )
        with connection.cursor(name=f"anon_{table}", row_factory=dict_row) as cursor:
            cursor.itersize = batch_size
            cursor.execute(query)
            records = ((table, row) for row in batched_rows(cursor, batch_size))
            yield from stream_jsonl(records, synth)


def export_connection(connection: Any, output: BinaryIO, batch_size: int, key: bytes) -> int:
    total = 0
    for chunk in export_chunks(connection, batch_size, key):
        output.write(chunk)
        output.flush()  # The downstream pipe controls backpressure here.
        total += 1
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--read-only", action="store_true", required=True)
    parser.add_argument("--batch-size", type=int, default=250)
    args = parser.parse_args()
    if not 1 <= args.batch_size <= 1000:
        raise SystemExit("batch size must be between 1 and 1000")
    token = os.environ.get("CAPTURE_AUTHORIZATION_ID", "")
    authorization_key = os.environ.get("CAPTURE_AUTHORIZATION_KEY", "").encode()
    source = os.environ.get("CAPTURE_SOURCE_SERVICE", "")
    destination = os.environ.get("CAPTURE_DESTINATION_SERVICE", "")
    try:
        verify_and_consume(
            token,
            authorization_key,
            expected_source=source,
            expected_destination=destination,
        )
    except AuthorizationRejected as exc:
        raise SystemExit(str(exc)) from None
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        raise SystemExit("runtime DATABASE_URL is required")
    # Key lives only in process memory. It is never logged, exported or persisted.
    key = os.urandom(32)
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            export_connection(connection, sys.stdout.buffer, args.batch_size, key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
