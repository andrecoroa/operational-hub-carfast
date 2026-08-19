from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class VehicleSaleProfile(TimestampMixin, Base):
    __tablename__ = "vehicle_sale_profiles"
    __table_args__ = (UniqueConstraint("vehicle_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="candidate", index=True)
    status_reference: Mapped[str | None] = mapped_column(String(120), index=True)
    market_trade_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    market_retail_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    selling_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    market_value_source: Mapped[str | None] = mapped_column(String(200))
    market_valued_on: Mapped[date | None] = mapped_column(Date)
    price_base: Mapped[str | None] = mapped_column(String(40))
    margin_mode: Mapped[str | None] = mapped_column(String(40))
    margin_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    rounding_mode: Mapped[str | None] = mapped_column(String(40))
    rounding_increment: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sale_notes: Mapped[str | None] = mapped_column(Text)
    public_notes: Mapped[str | None] = mapped_column(Text)
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class VehicleImage(TimestampMixin, Base):
    __tablename__ = "vehicle_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str] = mapped_column(String(1000))
    content_type: Mapped[str] = mapped_column(String(120))
    file_size: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    category: Mapped[str] = mapped_column(String(40), default="other", index=True)
    caption: Mapped[str | None] = mapped_column(String(500))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class VehicleSalePublication(TimestampMixin, Base):
    __tablename__ = "vehicle_sale_publications"

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    token: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    audience: Mapped[str] = mapped_column(String(40), default="retail", index=True)
    visibility: Mapped[str] = mapped_column(
        String(40), default="public_link", index=True
    )
    status: Mapped[str] = mapped_column(String(40), default="published", index=True)
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    selected_image_ids_json: Mapped[list] = mapped_column(JSON)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_on: Mapped[date | None] = mapped_column(Date, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    first_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VehicleSaleLead(TimestampMixin, Base):
    __tablename__ = "vehicle_sale_leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_sale_publications.id", ondelete="CASCADE"),
        index=True,
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(40), default="new", index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(80))
    company: Mapped[str | None] = mapped_column(String(200))
    offer_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    message: Mapped[str | None] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    source_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    portal_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("portal_users.id", ondelete="SET NULL"), index=True
    )
    portal_organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("portal_organizations.id", ondelete="SET NULL"), index=True
    )
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class VehicleSaleProposal(TimestampMixin, Base):
    __tablename__ = "vehicle_sale_proposals"

    id: Mapped[int] = mapped_column(primary_key=True)
    reference: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicle_sale_proposals.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    recipient: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(240), default="Proposta de viaturas")
    expires_on: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class VehicleSaleProposalLine(TimestampMixin, Base):
    __tablename__ = "vehicle_sale_proposal_lines"
    __table_args__ = (UniqueConstraint("proposal_id", "vehicle_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("vehicle_sale_proposals.id", ondelete="CASCADE"), index=True
    )
    vehicle_id: Mapped[int] = mapped_column(
        ForeignKey("vehicles.id", ondelete="RESTRICT"), index=True
    )
    snapshot_json: Mapped[dict] = mapped_column(JSON)
    base_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    proposed_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    customer_counteroffer: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    notes: Mapped[str | None] = mapped_column(Text)
    included: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
