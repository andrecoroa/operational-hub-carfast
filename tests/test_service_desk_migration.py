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
MIGRATION_REVISION = "ffbe1e2f3a4c"
PREVIOUS_REVISION = "ffad1e2f3a4b"
CURRENT_HEAD_REVISION = "fff7bc2d3e4f"
MIGRATION_PATH = (
    ROOT / "migrations" / "versions" / "ffbe1e2f3a4c_add_service_desk_email_operations.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("service_desk_migration", MIGRATION_PATH)
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


def test_service_desk_migration_remains_on_the_single_head_chain() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == [CURRENT_HEAD_REVISION]
    assert scripts.get_revision(MIGRATION_REVISION).down_revision == PREVIOUS_REVISION


def test_service_desk_migration_upgrade_compiles_for_postgresql(monkeypatch) -> None:
    sql = _render_postgresql_sql(monkeypatch, "upgrade")

    assert "CREATE TABLE service_desk_ticket_types" in sql
    assert "CREATE TABLE task_assignment_events" in sql
    assert "CREATE TABLE task_sla_events" in sql
    assert "CREATE TABLE email_executor_eligibilities" in sql
    assert "default_due_days >= 0" in sql
    assert "assigned_to_id IS NOT NULL" in sql
    assert "WHERE user_id IS NOT NULL" in sql
    assert "WHERE team_id IS NOT NULL" in sql
    assert "COALESCE(category_id, -1)" in sql
    assert "visibility_mode IN ('scope_all', 'direct_only', 'consult')" in sql
    assert "('task', 'Tarefa', 'Trabalho a executar.', 10)" in sql
    assert "ON CONFLICT (code) DO NOTHING" in sql
    assert "ON CONFLICT (role_id, permission_id) DO NOTHING" in sql
    assert "'service_desk.classifications.manage'" in sql
    assert "'email.sla.manage'" in sql


def test_service_desk_migration_downgrade_compiles_for_postgresql(monkeypatch) -> None:
    sql = _render_postgresql_sql(monkeypatch, "downgrade")

    assert "DROP TABLE email_executor_eligibilities" in sql
    assert "DROP TABLE task_sla_events" in sql
    assert "DROP TABLE task_assignment_events" in sql
    assert "DROP TABLE service_desk_ticket_types" in sql
    assert "DROP COLUMN inbound_forward_address" in sql
    assert "DROP COLUMN visibility_mode" in sql
    assert "DELETE FROM role_permissions WHERE permission_id IN" in sql
    assert "DELETE FROM permissions WHERE code IN" in sql
