"""Validate stdin and insert only anonymized envelopes into local PostgreSQL."""

from __future__ import annotations

import argparse
import os
import socket
import sys
from urllib.parse import parse_qs, urlsplit

import psycopg
from psycopg import sql

from app.platform.anonymized_receive import validated_envelopes

STAGING_DDL = (
    "CREATE TABLE rehearsal_users (id text PRIMARY KEY, active boolean NOT NULL, email text, name text)",  # noqa: E501
    "CREATE TABLE rehearsal_stock_suppliers (id text PRIMARY KEY, active boolean NOT NULL, name text, tax_id text, email text, phone text, legal_name text, registration_number text, contact_name text, secondary_email text, secondary_phone text)",  # noqa: E501
    "CREATE TABLE rehearsal_vehicles (id text PRIMARY KEY, active boolean NOT NULL, lifecycle_status text, operational_status text, plate text, vin text)",  # noqa: E501
    "CREATE TABLE rehearsal_tasks (id text PRIMARY KEY, status text NOT NULL, assigned_to_id text REFERENCES rehearsal_users(id) DEFERRABLE INITIALLY DEFERRED, parent_task_id text REFERENCES rehearsal_tasks(id) DEFERRABLE INITIALLY DEFERRED, team_id text, created_by_id text REFERENCES rehearsal_users(id) DEFERRABLE INITIALLY DEFERRED, customer_name text, customer_contact text, customer_email text, customer_phone text, plate text)",  # noqa: E501
    "CREATE TABLE rehearsal_management_processes (id text PRIMARY KEY, status text NOT NULL, process_type_id text, phase text, priority text, internal_reference text, plate text, customer_name text, driver_name text)",  # noqa: E501
    "CREATE TABLE rehearsal_email_messages (id text PRIMARY KEY, thread_id text NOT NULL, sender text)",  # noqa: E501
    "CREATE TABLE rehearsal_documents (id text PRIMARY KEY, status text NOT NULL, document_type text, classification text, vehicle_id text REFERENCES rehearsal_vehicles(id) DEFERRABLE INITIALLY DEFERRED, task_id text REFERENCES rehearsal_tasks(id) DEFERRABLE INITIALLY DEFERRED, workshop_process_id text, incident_id text, source_sender text, plate text, customer_name text, supplier_name text, fixture_object_count integer NOT NULL, fixture_bytes integer NOT NULL, fixture_sha256 text)",  # noqa: E501
    "CREATE TABLE rehearsal_audit_log (id text PRIMARY KEY, user_id text REFERENCES rehearsal_users(id) DEFERRABLE INITIALLY DEFERRED, action text NOT NULL, entity_type text, entity_id text)",  # noqa: E501
)


def create_staging(connection: object) -> None:
    for table in (
        "audit_log",
        "documents",
        "email_messages",
        "management_processes",
        "tasks",
        "vehicles",
        "stock_suppliers",
        "users",
    ):
        connection.execute(
            sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(f"rehearsal_{table}"))
        )
    for statement in STAGING_DDL:
        connection.execute(statement)


def insert_typed(connection: object, table: str, data: dict[str, object]) -> None:
    columns = tuple(data)
    statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(f"rehearsal_{table}"),
        sql.SQL(",").join(map(sql.Identifier, columns)),
        sql.SQL(",").join(sql.Placeholder() for _ in columns),
    )
    connection.execute(statement, tuple(data[column] for column in columns))


def reconcile_relations(connection: object, counts: dict[str, int]) -> dict[str, object]:
    persisted = {
        table: connection.execute(
            sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(f"rehearsal_{table}"))
        ).fetchone()[0]
        for table in counts
    }
    if persisted != counts:
        raise RuntimeError("typed staging count reconciliation failed")
    orphan_checks = {
        "task_users": "SELECT COUNT(*) FROM rehearsal_tasks t LEFT JOIN rehearsal_users u ON u.id=t.assigned_to_id WHERE t.assigned_to_id IS NOT NULL AND u.id IS NULL",  # noqa: E501
        "document_tasks": "SELECT COUNT(*) FROM rehearsal_documents d LEFT JOIN rehearsal_tasks t ON t.id=d.task_id WHERE d.task_id IS NOT NULL AND t.id IS NULL",  # noqa: E501
        "document_vehicles": "SELECT COUNT(*) FROM rehearsal_documents d LEFT JOIN rehearsal_vehicles v ON v.id=d.vehicle_id WHERE d.vehicle_id IS NOT NULL AND v.id IS NULL",  # noqa: E501
        "audit_typed_tasks": "SELECT COUNT(*) FROM rehearsal_audit_log a LEFT JOIN rehearsal_tasks t ON t.id=a.entity_id WHERE a.entity_type='task' AND a.entity_id IS NOT NULL AND t.id IS NULL",  # noqa: E501
    }
    orphans = {
        name: connection.execute(query).fetchone()[0] for name, query in orphan_checks.items()
    }
    if any(orphans.values()):
        raise RuntimeError("typed staging referential reconciliation failed")
    return {"counts": persisted, "orphans": orphans, "reconciled": True}


def require_approved_destination(dsn: str, approved_private_host: str = "") -> bool:
    """Validate a Unix socket or the exact pinned private Render PostgreSQL host."""
    parsed = urlsplit(dsn)
    query = parse_qs(parsed.query)
    socket_dir = query.get("host", [""])[0]
    if not parsed.path.lstrip("/").endswith("_test"):
        raise ValueError("destination database name must end in _test")
    if parsed.hostname in {None, ""} and socket_dir.startswith("/"):
        return False
    if (
        not approved_private_host
        or parsed.hostname != approved_private_host
        or parsed.port not in {None, 5432}
        or socket_dir
        or parsed.scheme not in {"postgresql", "postgres"}
        or query.get("sslmode", [""])[0] == "disable"
    ):
        raise ValueError("destination PostgreSQL must use the exact approved private host")
    return True


def require_local_socket(dsn: str) -> None:
    """Backward-compatible strict validator for the socket-only topology."""
    if require_approved_destination(dsn):
        raise ValueError("destination PostgreSQL must use an absolute Unix socket directory")


def install_ip_socket_blocker() -> None:
    """Fail closed before stdin: this process may create AF_UNIX sockets only."""
    original_socket = socket.socket
    unix_family = getattr(socket, "AF_UNIX", 1)

    def unix_only(family: int = socket.AF_INET, *args: object, **kwargs: object):
        if family != unix_family:
            raise PermissionError("IP sockets are disabled for anonymized ingestion")
        return original_socket(family, *args, **kwargs)

    socket.socket = unix_only  # type: ignore[assignment]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", required=True)
    args = parser.parse_args()
    managed_private = require_approved_destination(
        args.dsn,
        os.environ.get("REHEARSAL_DATABASE_HOST", ""),
    )
    if not managed_private:
        install_ip_socket_blocker()
    with psycopg.connect(args.dsn) as connection:
        if managed_private:
            # Only the pinned private DB connection exists. From this point the
            # process cannot open DNS, proxy, redirect, or any other IP socket
            # while it validates and ingests already-anonymized stdin.
            install_ip_socket_blocker()
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout = '30s'")
            connection.execute("SET LOCAL lock_timeout = '3s'")
            create_staging(connection)
            counts: dict[str, int] = {}
            for envelope in validated_envelopes(sys.stdin.buffer):
                insert_typed(connection, envelope["table"], envelope["data"])
                counts[envelope["table"]] = counts.get(envelope["table"], 0) + 1
            report = reconcile_relations(connection, counts)
    # stdout is aggregate-only; stderr remains unused so rejected data cannot leak.
    import json

    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
