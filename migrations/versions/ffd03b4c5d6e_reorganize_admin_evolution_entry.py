"""Reorganize Administration and separate evolution creation.

Revision ID: ffd03b4c5d6e
Revises: ffcf2a3b4c5d
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "ffd03b4c5d6e"
down_revision: str | Sequence[str] | None = "ffcf2a3b4c5d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EVOLUTION_TYPES = (
    "'improvement', 'question', 'error', 'decision', 'future_implementation', "
    "'problem', 'feature'"
)


def upgrade() -> None:
    op.drop_constraint(
        "ck_evolution_records_type",
        "evolution_records",
        type_="check",
    )
    op.create_check_constraint(
        "ck_evolution_records_type",
        "evolution_records",
        f"record_type IN ({EVOLUTION_TYPES})",
    )
    op.execute(
        "INSERT INTO permissions (code, name, description) "
        "VALUES ('admin.evolution.create', 'Criar registos de evolução', NULL) "
        "ON CONFLICT (code) DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.code IN "
        "('admin', 'user_admin', 'functional_admin', 'auditor', 'manager', 'operator', 'viewer') "
        "AND permissions.code = 'admin.evolution.create' "
        "ON CONFLICT (role_id, permission_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM evolution_records WHERE record_type IN "
        "('error', 'decision', 'future_implementation')) THEN "
        "RAISE EXCEPTION 'Cannot safely remove evolution types while records use them'; "
        "END IF; END $$"
    )
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code = 'admin.evolution.create')"
    )
    op.execute("DELETE FROM permissions WHERE code = 'admin.evolution.create'")
    op.drop_constraint(
        "ck_evolution_records_type",
        "evolution_records",
        type_="check",
    )
    op.create_check_constraint(
        "ck_evolution_records_type",
        "evolution_records",
        "record_type IN ('improvement', 'question', 'problem', 'feature')",
    )
