"""Prepare or roll back the exact empty Green database for a data-only restore."""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy import create_engine, text

import app.models  # noqa: F401
from app.models.base import Base
from app.platform.integral_migration_contract import (
    TARGET_RELEASE_SHA,
    contracted_inventories,
    validate_database_phase,
)

MARKER = Path("/tmp/carfast-integral-target-prepared.json")


def validate_exact_target(database_url: str) -> None:
    if os.environ.get("INTEGRAL_GREEN_REHEARSAL") != "true":
        raise SystemExit("Green rehearsal gate is not enabled")
    if os.environ.get("INTEGRAL_TARGET_SERVICE") != "srv-da5dk9bm8hqs73camds0":
        raise SystemExit("permanent Green service mismatch")
    parsed = urlsplit(database_url.replace("postgresql+psycopg", "postgresql", 1))
    if parsed.hostname != "dpg-da5dj0e417fc73f3uakg-a" or parsed.path != "/carfast_green":
        raise SystemExit("permanent Green database mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.apply == args.rollback:
        raise SystemExit("choose exactly one of --apply or --rollback")
    database_url = os.environ["DATABASE_URL"]
    validate_exact_target(database_url)
    source, target = contracted_inventories(Base.metadata)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        validate_database_phase(
            connection, Base.metadata, "target", validate_additive=args.apply
        )
        quoted = ", ".join(f'"{name}"' for name in sorted(target))
        connection.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    if args.apply:
        MARKER.write_text(
            json.dumps(
                {
                    "database": "carfast_green",
                    "release_sha": TARGET_RELEASE_SHA,
                    "relations": len(target),
                    "service": "srv-da5dk9bm8hqs73camds0",
                    "source_relations": len(source),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print("green_target_prepared=true relations=166 rollback=migrations-plus-seeds")
    else:
        MARKER.unlink(missing_ok=True)
        print("green_target_rollback_truncated=true bootstrap_required=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
