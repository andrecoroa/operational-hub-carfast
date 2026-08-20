"""add administration evolution register

Revision ID: ffcf2a3b4c5d
Revises: ffbe1e2f3a4c
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffcf2a3b4c5d"
down_revision: str | Sequence[str] | None = "ffbe1e2f3a4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


def upgrade() -> None:
    op.create_table(
        "evolution_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_type", sa.String(40), nullable=False),
        sa.Column("module", sa.String(80), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(160)),
        sa.Column("priority", sa.String(40), nullable=False, server_default="normal"),
        sa.Column("status", sa.String(40), nullable=False, server_default="registered"),
        sa.Column("decision", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("analysis_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("analysis_team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column(
            "reference_task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")
        ),
        sa.Column("reference_chat", sa.String(255)),
        sa.Column("reference_branch", sa.String(255)),
        sa.Column("reference_commit", sa.String(80)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("updated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *_timestamps(),
        sa.CheckConstraint(
            "record_type IN ('improvement', 'question', 'problem', 'feature')",
            name="ck_evolution_records_type",
        ),
        sa.CheckConstraint(
            "status IN ('registered', 'analysis', 'approved', 'deferred', 'rejected', "
            "'implementation', 'completed')",
            name="ck_evolution_records_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'normal', 'high', 'urgent')",
            name="ck_evolution_records_priority",
        ),
        sa.CheckConstraint(
            "NOT (analysis_user_id IS NOT NULL AND analysis_team_id IS NOT NULL)",
            name="ck_evolution_records_single_responsible",
        ),
    )
    for column in (
        "record_type",
        "module",
        "title",
        "origin",
        "priority",
        "status",
        "analysis_user_id",
        "analysis_team_id",
        "reference_task_id",
        "created_by_id",
        "updated_by_id",
    ):
        op.create_index(f"ix_evolution_records_{column}", "evolution_records", [column])

    op.create_table(
        "evolution_record_comments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "record_id",
            sa.Integer(),
            sa.ForeignKey("evolution_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_evolution_record_comments_record_id", "evolution_record_comments", ["record_id"]
    )
    op.create_index(
        "ix_evolution_record_comments_user_id", "evolution_record_comments", ["user_id"]
    )

    op.create_table(
        "evolution_record_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "record_id",
            sa.Integer(),
            sa.ForeignKey("evolution_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("field_name", sa.String(80), nullable=False),
        sa.Column("old_value", sa.Text()),
        sa.Column("new_value", sa.Text()),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_evolution_record_history_record_id", "evolution_record_history", ["record_id"]
    )
    op.create_index("ix_evolution_record_history_user_id", "evolution_record_history", ["user_id"])
    op.create_index(
        "ix_evolution_record_history_field_name", "evolution_record_history", ["field_name"]
    )

    op.create_table(
        "evolution_record_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "record_id",
            sa.Integer(),
            sa.ForeignKey("evolution_records.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            sa.Integer(),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("linked_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("record_id", "document_id", name="uq_evolution_record_document"),
    )
    op.create_index(
        "ix_evolution_record_documents_record_id", "evolution_record_documents", ["record_id"]
    )
    op.create_index(
        "ix_evolution_record_documents_document_id", "evolution_record_documents", ["document_id"]
    )
    op.create_index(
        "ix_evolution_record_documents_linked_by_id", "evolution_record_documents", ["linked_by_id"]
    )

    permissions = {
        "admin.evolution.read": "Consultar Registo de Evolução",
        "admin.evolution.manage": "Gerir Registo de Evolução",
    }
    for code, name in permissions.items():
        escaped_code = code.replace("'", "''")
        escaped_name = name.replace("'", "''")
        op.execute(
            "INSERT INTO permissions (code, name, description) "
            f"VALUES ('{escaped_code}', '{escaped_name}', NULL) ON CONFLICT (code) DO NOTHING"
        )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.code IN ('admin', 'functional_admin') "
        "AND permissions.code IN ('admin.evolution.read', 'admin.evolution.manage') "
        "ON CONFLICT (role_id, permission_id) DO NOTHING"
    )
    op.execute(
        "INSERT INTO role_permissions (role_id, permission_id) "
        "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
        "WHERE roles.code = 'auditor' AND permissions.code = 'admin.evolution.read' "
        "ON CONFLICT (role_id, permission_id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE code IN "
        "('admin.evolution.read', 'admin.evolution.manage'))"
    )
    op.execute(
        "DELETE FROM permissions WHERE code IN ('admin.evolution.read', 'admin.evolution.manage')"
    )
    op.drop_table("evolution_record_documents")
    op.drop_table("evolution_record_history")
    op.drop_table("evolution_record_comments")
    op.drop_table("evolution_records")
