"""Prepare canonical Workshop numbering and legacy-source mapping.

Revision ID: 10007b1c23cd
Revises: 10006a0f12bc
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10007b1c23cd"
down_revision: str | Sequence[str] | None = "10006a0f12bc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workshop_phased_processes",
        sa.Column("canonical_sequence", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_workshop_phased_processes_canonical_sequence",
        "workshop_phased_processes",
        ["canonical_sequence"],
        unique=True,
    )

    op.create_table(
        "workshop_unified_counters",
        sa.Column("series", sa.String(length=40), nullable=False),
        sa.Column("last_value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("series"),
    )

    op.create_table(
        "workshop_process_reference_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("reference", sa.String(length=120), nullable=False),
        sa.Column("normalized_reference", sa.String(length=120), nullable=False),
        sa.Column("reference_kind", sa.String(length=40), nullable=False, server_default="legacy"),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("source_entity_id", sa.String(length=120), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_phased_processes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "process_id",
            "normalized_reference",
            "source_system",
            name="uq_workshop_process_reference_alias",
        ),
    )
    for column in (
        "process_id",
        "normalized_reference",
        "reference_kind",
        "source_system",
        "source_entity_id",
    ):
        op.create_index(
            f"ix_workshop_process_reference_aliases_{column}",
            "workshop_process_reference_aliases",
            [column],
        )

    op.create_table(
        "workshop_process_source_links",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("source_system", sa.String(length=80), nullable=False),
        sa.Column("source_entity_type", sa.String(length=80), nullable=False),
        sa.Column("source_entity_id", sa.String(length=120), nullable=False),
        sa.Column("source_reference", sa.String(length=120), nullable=True),
        sa.Column("detail_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["process_id"],
            ["workshop_phased_processes.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_system",
            "source_entity_type",
            "source_entity_id",
            name="uq_workshop_process_source_link",
        ),
    )
    for column in (
        "process_id",
        "source_system",
        "source_entity_type",
        "source_entity_id",
        "source_reference",
    ):
        op.create_index(
            f"ix_workshop_process_source_links_{column}",
            "workshop_process_source_links",
            [column],
        )


def downgrade() -> None:
    op.drop_table("workshop_process_source_links")
    op.drop_table("workshop_process_reference_aliases")
    op.drop_table("workshop_unified_counters")
    op.drop_index(
        "ix_workshop_phased_processes_canonical_sequence",
        table_name="workshop_phased_processes",
    )
    op.drop_column("workshop_phased_processes", "canonical_sequence")
