from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_PATH = (
    ROOT
    / "migrations"
    / "versions"
    / "ffd03b4c5d6e_reorganize_admin_evolution_entry.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("admin_reorganization_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render_postgresql_sql(operation: str) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    module = _load_migration()
    module.op = Operations(context)
    getattr(module, operation)()
    return output.getvalue()


def test_admin_reorganization_upgrade_is_additive() -> None:
    sql = _render_postgresql_sql("upgrade")

    assert "admin.evolution.create" in sql
    assert "future_implementation" in sql
    assert "decision" in sql
    assert "error" in sql
    assert "DROP TABLE" not in sql


def test_admin_reorganization_downgrade_protects_new_history() -> None:
    sql = _render_postgresql_sql("downgrade")

    assert "Cannot safely remove evolution types" in sql
    assert "DELETE FROM evolution_records" not in sql
