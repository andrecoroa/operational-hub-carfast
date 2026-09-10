"""Add the minimal module catalogue and installation state.

Revision ID: fff37f8a9b0d
Revises: ffae1f2a3b4c
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff37f8a9b0d"
down_revision: str | Sequence[str] | None = "ffae1f2a3b4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "module_definitions",
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("version", sa.String(40), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "module_capabilities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module_code", sa.String(80), nullable=False),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column(
            "independently_switchable", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.ForeignKeyConstraint(["module_code"], ["module_definitions.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module_code", "code"),
    )
    op.create_index("ix_module_capabilities_module_code", "module_capabilities", ["module_code"])
    op.create_table(
        "module_dependencies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("module_code", sa.String(80), nullable=False),
        sa.Column("dependency_code", sa.String(80), nullable=False),
        sa.Column("minimum_version", sa.String(40), nullable=True),
        sa.ForeignKeyConstraint(
            ["dependency_code"], ["module_definitions.code"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["module_code"], ["module_definitions.code"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("module_code", "dependency_code"),
    )
    op.create_index("ix_module_dependencies_module_code", "module_dependencies", ["module_code"])
    op.create_index(
        "ix_module_dependencies_dependency_code", "module_dependencies", ["dependency_code"]
    )
    op.create_table(
        "installation_modules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("installation_key", sa.String(80), server_default="default", nullable=False),
        sa.Column("module_code", sa.String(80), nullable=False),
        sa.Column("state", sa.String(20), server_default="available", nullable=False),
        sa.Column("configured_version", sa.String(40), nullable=False),
        sa.Column("configuration", sa.JSON(), server_default=sa.text("'{}'::json"), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.CheckConstraint(
            "state IN ('available','active','disabled','retiring')",
            name="ck_installation_modules_installation_module_state",
        ),
        sa.ForeignKeyConstraint(["module_code"], ["module_definitions.code"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("installation_key", "module_code"),
    )
    op.create_index("ix_installation_modules_module_code", "installation_modules", ["module_code"])

    op.execute(
        sa.text(
            "INSERT INTO module_definitions (code, version, name, required) "
            "VALUES ('core', '1', 'Core', true)"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO installation_modules "
            "(installation_key, module_code, state, configured_version, configuration) "
            "VALUES ('default', 'core', 'active', '1', '{}'::json)"
        )
    )


def downgrade() -> None:
    op.drop_table("installation_modules")
    op.drop_table("module_dependencies")
    op.drop_table("module_capabilities")
    op.drop_table("module_definitions")
