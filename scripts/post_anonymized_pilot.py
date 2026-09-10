"""Source-side one-off: anonymize in READ ONLY transaction, then stream privately."""

from __future__ import annotations

import http.client
import json
import os
import socket
from urllib.parse import urlsplit

import psycopg

from app.platform.capture_authorization import verify_and_consume
from scripts.export_anonymized_dataset import export_chunks

TABLES = tuple(("public", name) for name in (
    "users", "stock_suppliers", "vehicles", "tasks", "management_processes",
    "email_messages", "documents", "audit_log",
))


def validate_read_only(connection: object) -> None:
    row = connection.execute(
        "SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    if row is None or any(row):
        raise RuntimeError("source role is privileged")
    for schema, table in TABLES:
        writable = connection.execute(
            "SELECT has_table_privilege(current_user, %s, "
            "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
            (f"{schema}.{table}",),
        ).fetchone()[0]
        if writable:
            raise RuntimeError("source role has write privilege")


def main() -> int:
    token = os.environ["CAPTURE_AUTHORIZATION_ID"]
    key = os.environ["CAPTURE_AUTHORIZATION_KEY"].encode()
    source = os.environ["CAPTURE_SOURCE_SERVICE"]
    destination = os.environ["CAPTURE_DESTINATION_SERVICE"]
    verify_and_consume(token, key, expected_source=source, expected_destination=destination)
    url = urlsplit(os.environ["CAPTURE_DESTINATION_URL"])
    if url.scheme != "http" or url.path not in ("", "/") or not url.hostname:
        raise RuntimeError("destination must be an exact private HTTP origin")
    allowed = (url.hostname, url.port or 80)
    original = socket.create_connection

    def restricted(address: tuple[str, int], *args: object, **kwargs: object):
        if address != allowed:
            raise OSError("source egress denied")
        return original(address, *args, **kwargs)

    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        with connection.transaction():
            connection.execute("SET TRANSACTION READ ONLY")
            connection.execute("SET LOCAL statement_timeout = '30s'")
            connection.execute("SET LOCAL lock_timeout = '2s'")
            validate_read_only(connection)
            # Install only after the approved DB session exists. From this point the
            # process can open a new socket solely to the exact private destination.
            socket.create_connection = restricted
            client = http.client.HTTPConnection(*allowed, timeout=60)
            client.request(
                "POST",
                "/internal/anonymized-pilot/v1",
                body=export_chunks(connection, 250, os.urandom(32)),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/jsonl"},
                encode_chunked=True,
            )
            response = client.getresponse()
            body = response.read(64 * 1024)
            if response.status != 200:
                raise RuntimeError("destination rejected anonymized stream")
            aggregate = json.loads(body)
            print(json.dumps(aggregate, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
