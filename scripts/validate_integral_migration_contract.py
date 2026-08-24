"""Validate an exact database phase of the 162-to-166 rehearsal."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys

from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.platform.integral_migration_contract import (
    IntegralMigrationContractError,
    validate_database_phase,
)


def _failure_code(message: str) -> str:
    """Return a stable, non-sensitive contract stage for operator diagnostics."""
    prefixes = {
        "source relation inventory mismatch": "source_inventory",
        "staging relation inventory mismatch": "staging_inventory",
        "target relation inventory mismatch": "target_inventory",
        "source revision mismatch": "source_revision",
        "staging revision mismatch": "staging_revision",
        "target revision mismatch": "target_revision",
        "additive column contract mismatch": "additive_columns",
        "additive primary-key contract mismatch": "additive_primary_key",
        "additive unique contract mismatch": "additive_unique",
        "additive foreign-key contract mismatch": "additive_foreign_key",
        "additive seed count mismatch": "additive_seed_count",
        "additive index contract mismatch": "additive_index",
        "installation_modules check contract mismatch": "additive_check",
        "module_definitions seed contract mismatch": "module_seed",
        "installation_modules seed contract mismatch": "installation_seed",
    }
    for prefix, code in prefixes.items():
        if message.startswith(prefix):
            return code
    return "unclassified_contract"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("source", "staging", "target"))
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    try:
        with engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            validate_database_phase(connection, Base.metadata, args.phase)
    except IntegralMigrationContractError as exc:
        message = str(exc)
        print(
            f"migration_contract_phase={args.phase} valid=false "
            f"failure_code={_failure_code(message)} "
            f"detail_sha256={hashlib.sha256(message.encode()).hexdigest()}",
            file=sys.stderr,
        )
        return 1
    expected = 166 if args.phase == "target" else 162
    print(f"migration_contract_phase={args.phase} relations={expected} valid=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
