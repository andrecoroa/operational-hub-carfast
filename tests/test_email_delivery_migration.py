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
MIGRATION_PATH = (
    ROOT
    / "migrations"
    / "versions"
    / "ffe04c5d6e7f_preserve_email_message_deliveries.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("email_delivery_migration", MIGRATION_PATH)
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


def test_email_delivery_migration_is_the_single_additive_head() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    scripts = ScriptDirectory.from_config(config)

    assert scripts.get_heads() == ["fff8cd3e4f5a"]
    assert scripts.get_revision("ffd02a3b4c5e").down_revision == "ffe04c5d6e7f"
    assert scripts.get_revision("ffe04c5d6e7f").down_revision == "ffd03b4c5d6e"


def test_email_delivery_upgrade_preserves_events_and_messages() -> None:
    sql = _render_postgresql_sql("upgrade")

    assert "CREATE TABLE email_message_deliveries" in sql
    assert "uq_email_message_delivery_canonical" in sql
    assert "uq_email_message_delivery_event" in sql
    assert "DROP TABLE" not in sql
    assert "DELETE FROM" not in sql


def test_email_delivery_downgrade_protects_preserved_history() -> None:
    sql = _render_postgresql_sql("downgrade")

    assert "Cannot safely remove preserved email delivery history" in sql
    assert "DROP TABLE email_message_deliveries" in sql
    assert "email_messages" not in sql.replace("email_message_deliveries", "")
    assert "email_webhook_events" not in sql
