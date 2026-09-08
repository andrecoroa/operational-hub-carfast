"""Add encrypted email secret references.

Revision ID: fffd028c9e10
Revises: fffd128c9e0f
"""

import sqlalchemy as sa
from alembic import op

revision = "fffd028c9e10"
down_revision = "fffd128c9e0f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_secret_references",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reference", sa.String(length=255), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("reference", name="uq_email_secret_references_reference"),
    )
    op.create_index(
        "ix_email_secret_references_reference",
        "email_secret_references",
        ["reference"],
        unique=True,
    )
    op.create_index(
        "ix_email_secret_references_expires_at",
        "email_secret_references",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_email_secret_references_expires_at", table_name="email_secret_references")
    op.drop_index("ix_email_secret_references_reference", table_name="email_secret_references")
    op.drop_table("email_secret_references")
