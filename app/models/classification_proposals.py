from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class ClassificationSequence(Base):
    """Database-backed counters used for immutable technical codes."""

    __tablename__ = "classification_sequences"

    scope: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ClassificationProposal(TimestampMixin, Base):
    __tablename__ = "classification_proposals"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('category', 'subcategory')", name="ck_classification_proposals_kind"
        ),
        CheckConstraint(
            "status IN ('pending', 'observation', 'approved', 'linked', 'merged', "
            "'rejected', 'archived')",
            name="ck_classification_proposals_status",
        ),
        CheckConstraint(
            "(kind = 'category' AND department_id IS NOT NULL AND category_id IS NULL) OR "
            "(kind = 'subcategory' AND department_id IS NOT NULL AND "
            "(category_id IS NOT NULL OR parent_proposal_id IS NOT NULL))",
            name="ck_classification_proposals_hierarchy",
        ),
        Index(
            "uq_classification_proposals_open_normalized_hierarchy",
            "kind",
            "hierarchy_key",
            "normalized_name",
            unique=True,
            postgresql_where=text("active"),
            sqlite_where=text("active = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provisional_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    proposed_name: Mapped[str] = mapped_column(String(160), index=True)
    normalized_name: Mapped[str] = mapped_column(String(160), index=True)
    hierarchy_key: Mapped[str] = mapped_column(String(80), index=True)
    reason: Mapped[str] = mapped_column(Text)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("work_departments.id", ondelete="RESTRICT"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="RESTRICT"), index=True
    )
    parent_proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_proposals.id", ondelete="RESTRICT"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    proposed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    origin_module: Mapped[str] = mapped_column(String(80), index=True)
    origin_url: Mapped[str | None] = mapped_column(String(500))
    origin_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    evolution_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("evolution_records.id", ondelete="SET NULL"), unique=True, index=True
    )
    usage_count: Mapped[int] = mapped_column(Integer, default=0, index=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    decision_notes: Mapped[str | None] = mapped_column(Text)
    definitive_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="RESTRICT"), index=True
    )
    definitive_subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_subcategories.id", ondelete="RESTRICT"), index=True
    )
    merged_into_proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("classification_proposals.id", ondelete="RESTRICT"), index=True
    )


class ClassificationProposalUsage(TimestampMixin, Base):
    __tablename__ = "classification_proposal_usages"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('task', 'email_thread')",
            name="ck_classification_proposal_usages_entity_type",
        ),
        UniqueConstraint(
            "proposal_id",
            "entity_type",
            "entity_id",
            name="uq_classification_proposal_usage",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("classification_proposals.id", ondelete="RESTRICT"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), index=True)
    entity_id: Mapped[int] = mapped_column(Integer, index=True)
    module: Mapped[str] = mapped_column(String(80), index=True)
    origin_url: Mapped[str | None] = mapped_column(String(500))
    first_used_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    last_used_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    resolved_action: Mapped[str | None] = mapped_column(String(40), index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)


class ClassificationProposalAudit(Base):
    __tablename__ = "classification_proposal_audits"

    id: Mapped[int] = mapped_column(primary_key=True)
    proposal_id: Mapped[int] = mapped_column(
        ForeignKey("classification_proposals.id", ondelete="RESTRICT"), index=True
    )
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    action: Mapped[str] = mapped_column(String(60), index=True)
    before_json: Mapped[dict | None] = mapped_column(JSON)
    after_json: Mapped[dict | None] = mapped_column(JSON)
    details: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
