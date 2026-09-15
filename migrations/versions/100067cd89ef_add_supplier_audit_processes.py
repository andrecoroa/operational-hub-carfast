"""Add supplier audit process extensions.

Revision ID: 100067cd89ef
Revises: 100056bc78de
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "100067cd89ef"
down_revision: str | Sequence[str] | None = "100056bc78de"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supplier_audit_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("process_id", sa.Integer(), sa.ForeignKey("management_processes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("problem_type", sa.String(80), nullable=False),
        sa.Column("suspicion_description", sa.Text(), nullable=False),
        sa.Column("assessment_grade", sa.String(40), nullable=False, server_default="suspicion"),
        sa.Column("detected_on", sa.Date(), nullable=True),
        sa.Column("immediate_risk", sa.Text(), nullable=True),
        sa.Column("potential_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("verification_data_json", sa.JSON(), nullable=True),
        sa.Column("missing_elements_json", sa.JSON(), nullable=True),
        sa.Column("conclusion", sa.String(40), nullable=True),
        sa.Column("cause", sa.Text(), nullable=True),
        sa.Column("probable_responsibility", sa.Text(), nullable=True),
        sa.Column("impact", sa.Text(), nullable=True),
        sa.Column("requested_outcome", sa.Text(), nullable=True),
        sa.Column("final_result", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("process_id", name="uq_supplier_audit_case_process"),
    )
    for column in ("process_id", "vehicle_id", "problem_type", "assessment_grade", "detected_on", "owner_id", "conclusion"):
        op.create_index(f"ix_supplier_audit_cases_{column}", "supplier_audit_cases", [column])

    op.create_table(
        "supplier_audit_parties",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audit_id", sa.Integer(), sa.ForeignKey("supplier_audit_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_of_id", sa.Integer(), sa.ForeignKey("supplier_audit_email_drafts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("stock_suppliers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_name", sa.String(200), nullable=False),
        sa.Column("role", sa.String(120), nullable=False),
        sa.Column("related_intervention", sa.Text(), nullable=True),
        sa.Column("request_text", sa.Text(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("response_status", sa.String(40), nullable=False, server_default="not_requested"),
        sa.Column("position_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("audit_id", "supplier_id", "due_on", "response_status"):
        op.create_index(f"ix_supplier_audit_parties_{column}", "supplier_audit_parties", [column])

    op.create_table(
        "supplier_audit_email_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("audit_id", sa.Integer(), sa.ForeignKey("supplier_audit_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("party_id", sa.Integer(), sa.ForeignKey("supplier_audit_parties.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recipient", sa.String(255), nullable=True),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("concrete_request", sa.Text(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("references_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(40), nullable=False, server_default="preparing"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column in ("audit_id", "revision_of_id", "party_id", "status"):
        op.create_index(f"ix_supplier_audit_email_drafts_{column}", "supplier_audit_email_drafts", [column])


def downgrade() -> None:
    op.drop_table("supplier_audit_email_drafts")
    op.drop_table("supplier_audit_parties")
    op.drop_table("supplier_audit_cases")
