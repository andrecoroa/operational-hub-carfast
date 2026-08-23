"""Read-only verification of an isolated, clean Phase 10 installation.

Run only after Alembic and ``bootstrap_installation`` against a disposable local
PostgreSQL database. The guard deliberately rejects remote and non-test targets.
"""

from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

from sqlalchemy import text

from app.core.database import engine
from app.platform.reconciliation import ReconciliationMetric, RehearsalReport
from scripts.check_clean_install import OPERATIONAL_TABLES


def validate_isolated_target(app_env: str, database_url: str) -> str:
    if app_env != "test":
        raise ValueError("Phase 10 rehearsal requires APP_ENV=test")
    parsed = urlsplit(database_url.replace("postgresql+psycopg", "postgresql", 1))
    database = parsed.path.lstrip("/")
    if parsed.hostname not in {"localhost", "127.0.0.1", "postgres"}:
        raise ValueError("Phase 10 rehearsal requires isolated local PostgreSQL")
    if not database.endswith("_test"):
        raise ValueError("Phase 10 rehearsal database name must end in _test")
    return database


def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    database = validate_isolated_target(os.environ.get("APP_ENV", ""), database_url)
    metrics: list[ReconciliationMetric] = []
    with engine.connect() as connection:
        for table in OPERATIONAL_TABLES:
            count = connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
            metrics.append(ReconciliationMetric(f"clean.{table}", 0, count))
        module_count = connection.execute(
            text("SELECT COUNT(*) FROM module_definitions")
        ).scalar_one()
        metrics.append(
            ReconciliationMetric(
                "reference.module_catalogue",
                module_count,
                module_count,
            )
        )
    report = RehearsalReport("clean_installation", database, tuple(metrics))
    print(json.dumps(report.payload(), ensure_ascii=False, indent=2))
    if not report.reconciled:
        raise SystemExit("Phase 10 clean-install reconciliation failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
