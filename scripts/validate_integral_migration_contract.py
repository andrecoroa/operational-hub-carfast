"""Validate an exact database phase of the 162-to-166 rehearsal."""

from __future__ import annotations

import argparse
import os

from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.platform.integral_migration_contract import validate_database_phase


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("source", "staging", "target"))
    args = parser.parse_args()
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as connection, connection.begin():
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        validate_database_phase(connection, Base.metadata, args.phase)
    expected = 166 if args.phase == "target" else 162
    print(f"migration_contract_phase={args.phase} relations={expected} valid=true")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
