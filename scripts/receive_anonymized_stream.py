"""Validate stdin and insert only anonymized envelopes into local PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import parse_qs, urlsplit

import psycopg

from app.platform.anonymized_receive import validated_envelopes


def require_local_socket(dsn: str) -> None:
    parsed = urlsplit(dsn)
    socket_dir = parse_qs(parsed.query).get("host", [""])[0]
    if parsed.hostname not in {None, "", "localhost", "127.0.0.1"}:
        raise ValueError("destination PostgreSQL must not use a network host")
    if parsed.hostname in {None, ""} and not socket_dir.startswith("/"):
        raise ValueError("destination PostgreSQL must use an absolute Unix socket directory")
    if not parsed.path.lstrip("/").endswith("_test"):
        raise ValueError("destination database name must end in _test")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()
    require_local_socket(args.dsn)
    with psycopg.connect(args.dsn) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout = '30s'")
            connection.execute("SET LOCAL lock_timeout = '3s'")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rehearsal_anonymized_payloads ("
                "sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                "table_name text NOT NULL, payload jsonb NOT NULL)"
            )
            count = 0
            for envelope in validated_envelopes(sys.stdin.buffer):
                connection.execute(
                    "INSERT INTO rehearsal_anonymized_payloads(table_name, payload) "
                    "VALUES (%s, %s)",
                    (envelope["table"], json.dumps(envelope["data"])),
                )
                count += 1
    print(json.dumps({"accepted_records": count, "reconciled": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
