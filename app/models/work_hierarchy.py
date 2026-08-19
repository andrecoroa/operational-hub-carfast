from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class WorkQueue(TimestampMixin, Base):
    __tablename__ = "work_queues"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkDepartment(TimestampMixin, Base):
    __tablename__ = "work_departments"
    __table_args__ = (
        UniqueConstraint("queue_id", "code", name="uq_work_department_queue_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    queue_id: Mapped[int] = mapped_column(
        ForeignKey("work_queues.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(80), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    requires_description: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkCategory(TimestampMixin, Base):
    __tablename__ = "work_categories"
    __table_args__ = (
        UniqueConstraint("department_id", "code", name="uq_work_category_department_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(
        ForeignKey("work_departments.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(100), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    requires_description: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class WorkSubcategory(TimestampMixin, Base):
    __tablename__ = "work_subcategories"
    __table_args__ = (
        UniqueConstraint("category_id", "code", name="uq_work_subcategory_category_code"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("work_categories.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    requires_description: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class RoleWorkScope(TimestampMixin, Base):
    __tablename__ = "role_work_scopes"
    __table_args__ = (
        UniqueConstraint(
            "role_id",
            "queue_id",
            "department_id",
            "category_id",
            "subcategory_id",
            name="uq_role_work_scope_hierarchy",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), index=True
    )
    queue_id: Mapped[int] = mapped_column(
        ForeignKey("work_queues.id", ondelete="CASCADE"), index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_departments.id", ondelete="CASCADE"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="CASCADE"), index=True
    )
    subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_subcategories.id", ondelete="CASCADE"), index=True
    )
    can_read: Mapped[bool] = mapped_column(Boolean, default=True)
    can_create: Mapped[bool] = mapped_column(Boolean, default=False)
    can_update: Mapped[bool] = mapped_column(Boolean, default=False)
    can_assign: Mapped[bool] = mapped_column(Boolean, default=False)
    can_close: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)


class WorkSourceDefault(TimestampMixin, Base):
    __tablename__ = "work_source_defaults"
    __table_args__ = (
        UniqueConstraint("source_type", "source_key", name="uq_work_source_default"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(60), index=True)
    source_key: Mapped[str] = mapped_column(String(120), index=True)
    queue_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_queues.id", ondelete="SET NULL"), index=True
    )
    department_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_departments.id", ondelete="SET NULL"), index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_categories.id", ondelete="SET NULL"), index=True
    )
    subcategory_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_subcategories.id", ondelete="SET NULL"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
