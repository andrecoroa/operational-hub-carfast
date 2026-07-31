"""Add external portal organizations, users, invitations and publication access."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "b0c1d2e3f4a5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "portal_organizations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("tax_number", sa.String(length=40), nullable=True),
        sa.Column("organization_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tax_number"),
    )
    op.create_index(
        "ix_portal_organizations_name", "portal_organizations", ["name"]
    )
    op.create_index(
        "ix_portal_organizations_organization_type",
        "portal_organizations",
        ["organization_type"],
    )
    op.create_index(
        "ix_portal_organizations_status", "portal_organizations", ["status"]
    )
    op.create_index(
        "ix_portal_organizations_tax_number",
        "portal_organizations",
        ["tax_number"],
        unique=True,
    )

    op.create_table(
        "portal_users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("invited_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["portal_organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["invited_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portal_users_active", "portal_users", ["active"])
    op.create_index("ix_portal_users_email", "portal_users", ["email"], unique=True)
    op.create_index(
        "ix_portal_users_organization_id", "portal_users", ["organization_id"]
    )

    op.create_table(
        "portal_invitations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("permissions_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["accepted_by_user_id"], ["portal_users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["portal_organizations.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_portal_invitations_email", "portal_invitations", ["email"]
    )
    op.create_index(
        "ix_portal_invitations_expires_at", "portal_invitations", ["expires_at"]
    )
    op.create_index(
        "ix_portal_invitations_organization_id",
        "portal_invitations",
        ["organization_id"],
    )
    op.create_index(
        "ix_portal_invitations_status", "portal_invitations", ["status"]
    )
    op.create_index(
        "ix_portal_invitations_token_hash",
        "portal_invitations",
        ["token_hash"],
        unique=True,
    )

    op.add_column(
        "vehicle_sale_publications",
        sa.Column(
            "visibility",
            sa.String(length=40),
            server_default="public_link",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_vehicle_sale_publications_visibility",
        "vehicle_sale_publications",
        ["visibility"],
    )

    op.create_table(
        "portal_publication_access",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"], ["portal_organizations.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"],
            ["vehicle_sale_publications.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("publication_id", "organization_id"),
    )
    op.create_index(
        "ix_portal_publication_access_organization_id",
        "portal_publication_access",
        ["organization_id"],
    )
    op.create_index(
        "ix_portal_publication_access_publication_id",
        "portal_publication_access",
        ["publication_id"],
    )

    with op.batch_alter_table("vehicle_sale_leads") as batch_op:
        batch_op.add_column(
            sa.Column(
                "portal_user_id",
                sa.Integer(),
                sa.ForeignKey("portal_users.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "portal_organization_id",
                sa.Integer(),
                sa.ForeignKey("portal_organizations.id", ondelete="SET NULL"),
                nullable=True,
            )
        )
    op.create_index(
        "ix_vehicle_sale_leads_portal_user_id",
        "vehicle_sale_leads",
        ["portal_user_id"],
    )
    op.create_index(
        "ix_vehicle_sale_leads_portal_organization_id",
        "vehicle_sale_leads",
        ["portal_organization_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_vehicle_sale_leads_portal_organization_id",
        table_name="vehicle_sale_leads",
    )
    op.drop_index(
        "ix_vehicle_sale_leads_portal_user_id", table_name="vehicle_sale_leads"
    )
    with op.batch_alter_table("vehicle_sale_leads") as batch_op:
        batch_op.drop_column("portal_organization_id")
        batch_op.drop_column("portal_user_id")
    op.drop_index(
        "ix_portal_publication_access_publication_id",
        table_name="portal_publication_access",
    )
    op.drop_index(
        "ix_portal_publication_access_organization_id",
        table_name="portal_publication_access",
    )
    op.drop_table("portal_publication_access")
    op.drop_index(
        "ix_vehicle_sale_publications_visibility",
        table_name="vehicle_sale_publications",
    )
    op.drop_column("vehicle_sale_publications", "visibility")
    op.drop_index(
        "ix_portal_invitations_token_hash", table_name="portal_invitations"
    )
    op.drop_index("ix_portal_invitations_status", table_name="portal_invitations")
    op.drop_index(
        "ix_portal_invitations_organization_id", table_name="portal_invitations"
    )
    op.drop_index(
        "ix_portal_invitations_expires_at", table_name="portal_invitations"
    )
    op.drop_index("ix_portal_invitations_email", table_name="portal_invitations")
    op.drop_table("portal_invitations")
    op.drop_index(
        "ix_portal_users_organization_id", table_name="portal_users"
    )
    op.drop_index("ix_portal_users_email", table_name="portal_users")
    op.drop_index("ix_portal_users_active", table_name="portal_users")
    op.drop_table("portal_users")
    op.drop_index(
        "ix_portal_organizations_tax_number", table_name="portal_organizations"
    )
    op.drop_index(
        "ix_portal_organizations_status", table_name="portal_organizations"
    )
    op.drop_index(
        "ix_portal_organizations_organization_type",
        table_name="portal_organizations",
    )
    op.drop_index(
        "ix_portal_organizations_name", table_name="portal_organizations"
    )
    op.drop_table("portal_organizations")
