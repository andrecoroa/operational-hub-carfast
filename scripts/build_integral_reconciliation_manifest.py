"""Build aggregate-only evidence for an isolated integral rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import create_engine, inspect, text

import app.models  # noqa: F401
from app.models.base import Base
from app.platform.integral_reconciliation import (
    IntegralManifest,
    build_database_evidence,
    build_storage_evidence,
    write_manifest,
)
from scripts.run_phase10_rehearsal import validate_isolated_target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--release-sha", required=True)
    parser.add_argument("--database-label", choices=("source", "target"), required=True)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--gated-remote", action="store_true")
    return parser.parse_args()


def validate_gated_remote(args: argparse.Namespace, database_url: str) -> str:
    if os.environ.get("INTEGRAL_GREEN_REHEARSAL", "").lower() != "true":
        raise SystemExit("gated remote manifest requires INTEGRAL_GREEN_REHEARSAL=true")
    if os.environ.get("APP_ENV") != "rehearsal":
        raise SystemExit("gated remote manifest requires APP_ENV=rehearsal")
    parsed = urlsplit(database_url.replace("postgresql+psycopg", "postgresql", 1))
    expected_host = os.environ.get("INTEGRAL_EXPECTED_DATABASE_HOST", "")
    expected_database = os.environ.get("INTEGRAL_EXPECTED_DATABASE_NAME", "")
    if not expected_host.startswith("dpg-") or parsed.hostname != expected_host:
        raise SystemExit("gated remote manifest database host mismatch")
    database = parsed.path.lstrip("/")
    if not expected_database or database != expected_database:
        raise SystemExit("gated remote manifest database name mismatch")
    if parse_qs(parsed.query).get("sslmode") == ["disable"]:
        raise SystemExit("gated remote manifest cannot disable TLS")
    for name in ("INTEGRAL_SOURCE_SERVICE", "INTEGRAL_DESTINATION_SERVICE"):
        if not os.environ.get(name, "").startswith("srv-"):
            raise SystemExit(f"gated remote manifest requires {name}")
    if os.environ["INTEGRAL_SOURCE_SERVICE"] == os.environ["INTEGRAL_DESTINATION_SERVICE"]:
        raise SystemExit("gated remote source and destination must differ")
    return database


def validate_source_role(connection: object) -> None:
    expected_role = os.environ.get("INTEGRAL_EXPECTED_DATABASE_ROLE", "")
    current_role = connection.execute(text("SELECT current_user")).scalar_one()
    if not expected_role or current_role != expected_role:
        raise SystemExit("integral source database role mismatch")
    for table in sorted(Base.metadata.tables):
        writable = connection.execute(
            text(
                "SELECT has_table_privilege(current_user, :relation, "
                "'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
            ),
            {"relation": f"public.{table}"},
        ).scalar_one()
        if writable:
            raise SystemExit(f"integral source role has write privilege on {table}")
    for sequence in inspect(connection).get_sequence_names(schema="public"):
        if connection.execute(
            text("SELECT has_sequence_privilege(current_user, :sequence, 'USAGE,UPDATE')"),
            {"sequence": f"public.{sequence}"},
        ).scalar_one():
            raise SystemExit(f"integral source role has sequence privilege on {sequence}")


def evidence_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    args = parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    database = (
        validate_gated_remote(args, database_url)
        if args.gated_remote
        else validate_isolated_target(os.environ.get("APP_ENV", ""), database_url)
    )
    if args.batch_size < 1 or args.batch_size > 5_000:
        raise SystemExit("batch size must be between 1 and 5000")
    engine = create_engine(database_url)
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        if args.gated_remote and args.database_label == "source":
            validate_source_role(connection)
        relations = build_database_evidence(connection, Base.metadata, batch_size=args.batch_size)
    storage = build_storage_evidence(args.storage_root)
    manifest = IntegralManifest(
        release_sha=args.release_sha,
        database_label=f"{args.database_label}:{database}",
        relations=relations,
        storage=storage,
    )
    write_manifest(args.output, manifest)
    print(
        f"manifest={args.output} relations={len(relations)} "
        f"objects={len(storage)} rows={sum(item.row_count for item in relations)} "
        f"storage_bytes={sum(item.size for item in storage)} "
        f"relations_sha256={evidence_digest([asdict(item) for item in relations])} "
        f"storage_sha256={evidence_digest([asdict(item) for item in storage])} "
        "reconciled_input=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
