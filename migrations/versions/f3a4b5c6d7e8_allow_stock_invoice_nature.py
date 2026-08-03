"""Allow stock as an invoice workflow nature."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "e2f3a4b5c6d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE = "document_workflow_states"
INVOICE_CONSTRAINT = "ck_document_workflow_invoice_nature"
SUGGESTED_CONSTRAINT = "ck_document_workflow_suggested_invoice_nature"
LEGACY_VALUES = "'por_classificar','operacional','financeira'"
STOCK_VALUES = f"{LEGACY_VALUES},'stock'"


def _replace_constraints(values: str) -> None:
    with op.batch_alter_table(TABLE) as batch_op:
        batch_op.drop_constraint(INVOICE_CONSTRAINT, type_="check")
        batch_op.drop_constraint(SUGGESTED_CONSTRAINT, type_="check")
        batch_op.create_check_constraint(
            INVOICE_CONSTRAINT,
            f"invoice_nature IS NULL OR invoice_nature IN ({values})",
        )
        batch_op.create_check_constraint(
            SUGGESTED_CONSTRAINT,
            f"suggested_invoice_nature IS NULL OR suggested_invoice_nature IN ({values})",
        )


def upgrade() -> None:
    _replace_constraints(STOCK_VALUES)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"UPDATE {TABLE} SET invoice_nature = 'por_classificar' "
            "WHERE invoice_nature = 'stock'"
        )
    )
    bind.execute(
        sa.text(
            f"UPDATE {TABLE} SET suggested_invoice_nature = 'por_classificar' "
            "WHERE suggested_invoice_nature = 'stock'"
        )
    )
    _replace_constraints(LEGACY_VALUES)
