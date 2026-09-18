"""Preserve unmatched plates and per-party audit findings.

Revision ID: 100069ef01ab
Revises: 100068de90ef
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "100069ef01ab"
down_revision: str | Sequence[str] | None = "100068de90ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "supplier_audit_cases",
        sa.Column("plate_unmatched", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_supplier_audit_cases_plate_unmatched", "supplier_audit_cases", ["plate_unmatched"]
    )
    op.add_column("supplier_audit_parties", sa.Column("evidence_notes", sa.Text(), nullable=True))
    op.add_column("supplier_audit_parties", sa.Column("conclusion", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("supplier_audit_parties", "conclusion")
    op.drop_column("supplier_audit_parties", "evidence_notes")
    op.drop_index("ix_supplier_audit_cases_plate_unmatched", table_name="supplier_audit_cases")
    op.drop_column("supplier_audit_cases", "plate_unmatched")
