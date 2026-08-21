from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
from types import ModuleType

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_REVISION = "ffcf2a3b4c5d"
CURRENT_HEAD = "ffe04c5d6e7f"
ADMIN_REORGANIZATION_REVISION = "ffd03b4c5d6e"
PREVIOUS_REVISION = "ffbe1e2f3a4c"
MIGRATION_PATH = (
    ROOT
    / "migrations"
    / "versions"
    / "ffcf2a3b4c5d_add_admin_evolution_register.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("admin_evolution_migration", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _render_postgresql_sql(monkeypatch, operation: str) -> str:
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    module = _load_migration()
    monkeypatch.setattr(module, "op", Operations(context))
    getattr(module, operation)()
    return output.getvalue()


def test_admin_evolution_migration_is_the_single_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == [CURRENT_HEAD]
    assert scripts.get_revision(CURRENT_HEAD).down_revision == ADMIN_REORGANIZATION_REVISION
    assert (
        scripts.get_revision(ADMIN_REORGANIZATION_REVISION).down_revision
        == MIGRATION_REVISION
    )
    assert scripts.get_revision(MIGRATION_REVISION).down_revision == PREVIOUS_REVISION


def test_admin_evolution_migration_upgrade_compiles_for_postgresql(monkeypatch) -> None:
    sql = _render_postgresql_sql(monkeypatch, "upgrade")

    assert "CREATE TABLE evolution_records" in sql
    assert "CREATE TABLE evolution_record_history" in sql
    assert "CREATE TABLE evolution_record_comments" in sql
    assert "CREATE TABLE evolution_record_documents" in sql
    assert "admin.evolution.read" in sql
    assert "admin.evolution.manage" in sql
    assert "ON CONFLICT (role_id, permission_id) DO NOTHING" in sql


def test_admin_evolution_migration_downgrade_compiles_for_postgresql(monkeypatch) -> None:
    sql = _render_postgresql_sql(monkeypatch, "downgrade")

    assert "DROP TABLE evolution_record_documents" in sql
    assert "DROP TABLE evolution_record_history" in sql
    assert "DROP TABLE evolution_record_comments" in sql
    assert "DROP TABLE evolution_records" in sql
