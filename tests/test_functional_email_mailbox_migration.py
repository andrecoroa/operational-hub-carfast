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
    / "ffd02a3b4c5e_add_functional_email_mailboxes.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "functional_email_mailbox_migration", MIGRATION_PATH
    )
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


def test_functional_mailbox_upgrade_is_additive_and_configurable() -> None:
    sql = _render_postgresql_sql("upgrade")

    assert "CREATE TABLE email_channel_aliases" in sql
    assert "CREATE TABLE email_thread_links" in sql
    assert "default_reply_address" in sql
    assert "can_change_sender" in sql
    assert "can_edit_recipients" in sql
    assert "can_use_cc_bcc" in sql
    assert "@inbound.postmarkapp.com" not in sql
    assert "DELETE FROM" not in sql
    assert "DROP TABLE" not in sql


def test_functional_mailbox_downgrade_compiles_for_postgresql() -> None:
    sql = _render_postgresql_sql("downgrade")

    assert "DROP TABLE email_thread_links" in sql
    assert "DROP TABLE email_channel_aliases" in sql
