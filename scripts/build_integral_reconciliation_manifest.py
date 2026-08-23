"""Build aggregate-only evidence for an isolated integral rehearsal."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine

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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database_url = os.environ.get("DATABASE_URL", "")
    database = validate_isolated_target(os.environ.get("APP_ENV", ""), database_url)
    if args.batch_size < 1 or args.batch_size > 5_000:
        raise SystemExit("batch size must be between 1 and 5000")
    engine = create_engine(database_url)
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        relations = build_database_evidence(connection, Base.metadata, batch_size=args.batch_size)
    manifest = IntegralManifest(
        release_sha=args.release_sha,
        database_label=f"{args.database_label}:{database}",
        relations=relations,
        storage=build_storage_evidence(args.storage_root),
    )
    write_manifest(args.output, manifest)
    print(
        f"manifest={args.output} relations={len(relations)} "
        f"objects={len(manifest.storage)} reconciled_input=true"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
