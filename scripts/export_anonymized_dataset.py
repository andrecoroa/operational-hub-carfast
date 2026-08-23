"""Production-side anonymization boundary. Do not run without capture approval."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterator, Mapping
from typing import Any, BinaryIO

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.platform.anonymized_stream import FIELD_MAP, EphemeralSynthesizer, stream_jsonl


def batched_rows(cursor: Any, batch_size: int) -> Iterator[Mapping[str, Any]]:
    while rows := cursor.fetchmany(batch_size):
        yield from rows


def export_connection(connection: Any, output: BinaryIO, batch_size: int, key: bytes) -> int:
    synth = EphemeralSynthesizer(key)
    total = 0
    connection.execute("SET TRANSACTION READ ONLY")
    connection.execute("SET LOCAL statement_timeout = '30s'")
    connection.execute("SET LOCAL lock_timeout = '2s'")
    for table, rules in FIELD_MAP.items():
        columns = tuple(rules)
        query = sql.SQL("SELECT {} FROM {} ORDER BY id").format(
            sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table)
        )
        with connection.cursor(name=f"anon_{table}", row_factory=dict_row) as cursor:
            cursor.itersize = batch_size
            cursor.execute(query)
            records = ((table, row) for row in batched_rows(cursor, batch_size))
            for chunk in stream_jsonl(records, synth):
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
    if not os.environ.get("CAPTURE_AUTHORIZATION_ID"):
        raise SystemExit("explicit CAPTURE_AUTHORIZATION_ID is required")
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
