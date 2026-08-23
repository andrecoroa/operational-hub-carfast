"""Reset Green target sequences after an integral restore."""

from __future__ import annotations

import os

from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.models.base import Base
from app.platform.integral_sequences import reset_target_sequences
from scripts.build_integral_reconciliation_manifest import validate_gated_remote


class TargetArgs:
    gated_remote = True
    database_label = "target"


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    validate_gated_remote(TargetArgs(), database_url)  # type: ignore[arg-type]
    engine = create_engine(database_url)
    with engine.begin() as connection:
        reset = reset_target_sequences(connection, Base.metadata)
    print(f"target_sequences_reset={reset} source_sequence_access=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
