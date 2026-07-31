"""Add the Clean vehicle sales process, media, publications and leads."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "vehicle_sale_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("market_trade_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("market_retail_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("selling_price", sa.Numeric(14, 2), nullable=True),
        sa.Column("market_value_source", sa.String(length=200), nullable=True),
        sa.Column("market_valued_on", sa.Date(), nullable=True),
        sa.Column("price_base", sa.String(length=40), nullable=True),
        sa.Column("margin_mode", sa.String(length=40), nullable=True),
        sa.Column("margin_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("rounding_mode", sa.String(length=40), nullable=True),
        sa.Column("rounding_increment", sa.Numeric(14, 2), nullable=True),
        sa.Column("sale_notes", sa.Text(), nullable=True),
        sa.Column("public_notes", sa.Text(), nullable=True),
        sa.Column("status_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status_changed_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["status_changed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("vehicle_id"),
    )
    op.create_index("ix_vehicle_sale_profiles_status", "vehicle_sale_profiles", ["status"])
    op.create_index("ix_vehicle_sale_profiles_vehicle_id", "vehicle_sale_profiles", ["vehicle_id"])

    op.create_table(
        "vehicle_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("caption", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vehicle_images_active", "vehicle_images", ["active"])
    op.create_index("ix_vehicle_images_category", "vehicle_images", ["category"])
    op.create_index("ix_vehicle_images_sha256", "vehicle_images", ["sha256"])
    op.create_index("ix_vehicle_images_vehicle_id", "vehicle_images", ["vehicle_id"])

    op.create_table(
        "vehicle_sale_publications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=80), nullable=False),
        sa.Column("audience", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("selected_image_ids_json", sa.JSON(), nullable=False),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("expires_on", sa.Date(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=False),
        sa.Column("first_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vehicle_sale_publications_audience", "vehicle_sale_publications", ["audience"]
    )
    op.create_index(
        "ix_vehicle_sale_publications_expires_on", "vehicle_sale_publications", ["expires_on"]
    )
    op.create_index("ix_vehicle_sale_publications_status", "vehicle_sale_publications", ["status"])
    op.create_index(
        "ix_vehicle_sale_publications_token", "vehicle_sale_publications", ["token"], unique=True
    )
    op.create_index(
        "ix_vehicle_sale_publications_vehicle_id", "vehicle_sale_publications", ["vehicle_id"]
    )

    op.create_table(
        "vehicle_sale_leads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("publication_id", sa.Integer(), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("offer_value", sa.Numeric(14, 2), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "consent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["publication_id"], ["vehicle_sale_publications.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["vehicle_id"], ["vehicles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_vehicle_sale_leads_kind", "vehicle_sale_leads", ["kind"])
    op.create_index(
        "ix_vehicle_sale_leads_publication_id", "vehicle_sale_leads", ["publication_id"]
    )
    op.create_index(
        "ix_vehicle_sale_leads_source_fingerprint", "vehicle_sale_leads", ["source_fingerprint"]
    )
    op.create_index("ix_vehicle_sale_leads_status", "vehicle_sale_leads", ["status"])
    op.create_index("ix_vehicle_sale_leads_vehicle_id", "vehicle_sale_leads", ["vehicle_id"])

    op.execute(
        """
        INSERT INTO vehicle_sale_profiles (vehicle_id, status, created_at, updated_at)
        SELECT id,
               CASE WHEN lifecycle_status = 'sold' OR operational_status = 'sold'
                    THEN 'sold' ELSE 'for_sale' END,
               CURRENT_TIMESTAMP,
               CURRENT_TIMESTAMP
        FROM vehicles
        WHERE lifecycle_status IN ('for_sale', 'sold') OR operational_status = 'sold'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_vehicle_sale_leads_vehicle_id", table_name="vehicle_sale_leads")
    op.drop_index("ix_vehicle_sale_leads_status", table_name="vehicle_sale_leads")
    op.drop_index("ix_vehicle_sale_leads_source_fingerprint", table_name="vehicle_sale_leads")
    op.drop_index("ix_vehicle_sale_leads_publication_id", table_name="vehicle_sale_leads")
    op.drop_index("ix_vehicle_sale_leads_kind", table_name="vehicle_sale_leads")
    op.drop_table("vehicle_sale_leads")
    op.drop_index("ix_vehicle_sale_publications_vehicle_id", table_name="vehicle_sale_publications")
    op.drop_index("ix_vehicle_sale_publications_token", table_name="vehicle_sale_publications")
    op.drop_index("ix_vehicle_sale_publications_status", table_name="vehicle_sale_publications")
    op.drop_index("ix_vehicle_sale_publications_expires_on", table_name="vehicle_sale_publications")
    op.drop_index("ix_vehicle_sale_publications_audience", table_name="vehicle_sale_publications")
    op.drop_table("vehicle_sale_publications")
    op.drop_index("ix_vehicle_images_vehicle_id", table_name="vehicle_images")
    op.drop_index("ix_vehicle_images_sha256", table_name="vehicle_images")
    op.drop_index("ix_vehicle_images_category", table_name="vehicle_images")
    op.drop_index("ix_vehicle_images_active", table_name="vehicle_images")
    op.drop_table("vehicle_images")
    op.drop_index("ix_vehicle_sale_profiles_vehicle_id", table_name="vehicle_sale_profiles")
    op.drop_index("ix_vehicle_sale_profiles_status", table_name="vehicle_sale_profiles")
    op.drop_table("vehicle_sale_profiles")
