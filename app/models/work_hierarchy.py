from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
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


class ServiceDeskTicketType(TimestampMixin, Base):
    __tablename__ = "service_desk_ticket_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text)
    form_schema_json: Mapped[dict | None] = mapped_column(JSON)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class ServiceDeskCategoryPolicy(TimestampMixin, Base):
    __tablename__ = "service_desk_category_policies"
    __table_args__ = (
        CheckConstraint(
            "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
            name="ck_service_desk_category_policy_assignment_mode",
        ),
        CheckConstraint(
            "(first_response_minutes IS NULL OR first_response_minutes >= 0) AND "
            "(resolution_minutes IS NULL OR resolution_minutes >= 0) AND "
            "warning_minutes >= 0",
            name="ck_service_desk_category_policy_sla_minutes",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("work_categories.id", ondelete="CASCADE"), unique=True, index=True
    )
    assignment_mode: Mapped[str] = mapped_column(String(40), default="manual", index=True)
    default_executor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    default_executor_team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="SET NULL"), index=True
    )
    first_response_minutes: Mapped[int | None] = mapped_column(Integer)
    resolution_minutes: Mapped[int | None] = mapped_column(Integer)
    warning_minutes: Mapped[int] = mapped_column(Integer, default=60)
    pause_on_waiting: Mapped[bool] = mapped_column(Boolean, default=True)
    timezone: Mapped[str] = mapped_column(String(80), default="Europe/Lisbon")
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ServiceDeskCategorySupervisor(TimestampMixin, Base):
    __tablename__ = "service_desk_category_supervisors"
    __table_args__ = (
        UniqueConstraint("category_id", "user_id", name="uq_service_desk_category_supervisor"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("work_categories.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ServiceDeskCategoryExecutor(TimestampMixin, Base):
    __tablename__ = "service_desk_category_executors"
    __table_args__ = (
        UniqueConstraint(
            "category_id", "user_id", "team_id", name="uq_service_desk_category_executor"
        ),
        CheckConstraint(
            "(user_id IS NOT NULL AND team_id IS NULL) OR "
            "(user_id IS NULL AND team_id IS NOT NULL)",
            name="ck_service_desk_category_executor_target",
        ),
        Index(
            "uq_service_desk_category_executor_user",
            "category_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
            sqlite_where=text("user_id IS NOT NULL"),
        ),
        Index(
            "uq_service_desk_category_executor_team",
            "category_id",
            "team_id",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
            sqlite_where=text("team_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("work_categories.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[int | None] = mapped_column(
        ForeignKey("teams.id", ondelete="CASCADE"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


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
        CheckConstraint(
            "visibility_mode IN ('scope_all', 'direct_only', 'consult')",
            name="ck_role_work_scopes_visibility_mode",
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
    can_assume: Mapped[bool] = mapped_column(Boolean, default=False)
    can_close: Mapped[bool] = mapped_column(Boolean, default=False)
    can_respond: Mapped[bool] = mapped_column(Boolean, default=False)
    can_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage_sla: Mapped[bool] = mapped_column(Boolean, default=False)
    can_administer_classifications: Mapped[bool] = mapped_column(Boolean, default=False)
    can_manage: Mapped[bool] = mapped_column(Boolean, default=False)
    visibility_mode: Mapped[str] = mapped_column(
        String(40), default="scope_all", index=True
    )


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
