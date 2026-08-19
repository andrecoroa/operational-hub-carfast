"""add shared task and email work hierarchy

Revision ID: ec0c1d2e3f4b
Revises: eb0c1d2e3f4a
"""

import sqlalchemy as sa
from alembic import op

revision = "ec0c1d2e3f4b"
down_revision = "eb0c1d2e3f4a"
branch_labels = None
depends_on = None


def _hierarchy_foreign_keys(table: str, prefix: str = "work") -> None:
    for column, target in (
        (f"{prefix}_queue_id", "work_queues"),
        (f"{prefix}_department_id", "work_departments"),
        (f"{prefix}_category_id", "work_categories"),
        (f"{prefix}_subcategory_id", "work_subcategories"),
    ):
        op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
        op.create_index(f"ix_{table}_{column}", table, [column])
        op.create_foreign_key(
            f"fk_{table}_{column}", table, target, [column], ["id"], ondelete="SET NULL"
        )


def upgrade() -> None:
    op.create_table(
        "work_queues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_work_queues_code"),
    )
    op.create_index("ix_work_queues_code", "work_queues", ["code"], unique=True)
    op.create_index("ix_work_queues_active", "work_queues", ["active"])

    op.create_table(
        "work_departments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "queue_id",
            sa.Integer(),
            sa.ForeignKey("work_queues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("requires_description", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("queue_id", "code", name="uq_work_department_queue_code"),
    )
    op.create_index("ix_work_departments_queue_id", "work_departments", ["queue_id"])
    op.create_index("ix_work_departments_code", "work_departments", ["code"])
    op.create_index("ix_work_departments_active", "work_departments", ["active"])

    op.create_table(
        "work_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "department_id",
            sa.Integer(),
            sa.ForeignKey("work_departments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("requires_description", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("department_id", "code", name="uq_work_category_department_code"),
    )
    op.create_index("ix_work_categories_department_id", "work_categories", ["department_id"])
    op.create_index("ix_work_categories_code", "work_categories", ["code"])
    op.create_index("ix_work_categories_active", "work_categories", ["active"])

    op.create_table(
        "work_subcategories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("work_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.String(120), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("requires_description", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("category_id", "code", name="uq_work_subcategory_category_code"),
    )
    op.create_index("ix_work_subcategories_category_id", "work_subcategories", ["category_id"])
    op.create_index("ix_work_subcategories_code", "work_subcategories", ["code"])
    op.create_index("ix_work_subcategories_active", "work_subcategories", ["active"])

    op.create_table(
        "role_work_scopes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "queue_id",
            sa.Integer(),
            sa.ForeignKey("work_queues.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "department_id", sa.Integer(), sa.ForeignKey("work_departments.id", ondelete="CASCADE")
        ),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("work_categories.id", ondelete="CASCADE")
        ),
        sa.Column(
            "subcategory_id",
            sa.Integer(),
            sa.ForeignKey("work_subcategories.id", ondelete="CASCADE"),
        ),
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_create", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_update", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_assign", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_close", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_manage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "role_id",
            "queue_id",
            "department_id",
            "category_id",
            "subcategory_id",
            name="uq_role_work_scope_hierarchy",
        ),
    )
    for column in ("role_id", "queue_id", "department_id", "category_id", "subcategory_id"):
        op.create_index(f"ix_role_work_scopes_{column}", "role_work_scopes", [column])

    op.create_table(
        "work_source_defaults",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", sa.String(60), nullable=False),
        sa.Column("source_key", sa.String(120), nullable=False),
        sa.Column("queue_id", sa.Integer(), sa.ForeignKey("work_queues.id", ondelete="SET NULL")),
        sa.Column(
            "department_id", sa.Integer(), sa.ForeignKey("work_departments.id", ondelete="SET NULL")
        ),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("work_categories.id", ondelete="SET NULL")
        ),
        sa.Column(
            "subcategory_id",
            sa.Integer(),
            sa.ForeignKey("work_subcategories.id", ondelete="SET NULL"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("source_type", "source_key", name="uq_work_source_default"),
    )
    for column in (
        "source_type",
        "source_key",
        "queue_id",
        "department_id",
        "category_id",
        "subcategory_id",
        "active",
    ):
        op.create_index(f"ix_work_source_defaults_{column}", "work_source_defaults", [column])

    _hierarchy_foreign_keys("tasks")
    op.add_column(
        "tasks",
        sa.Column(
            "classification_status", sa.String(40), nullable=False, server_default="unclassified"
        ),
    )
    op.create_index("ix_tasks_classification_status", "tasks", ["classification_status"])
    op.add_column("tasks", sa.Column("classification_other_text", sa.Text()))
    op.add_column("tasks", sa.Column("legacy_classification", sa.Text()))
    op.add_column(
        "tasks", sa.Column("classification_updated_by_id", sa.Integer(), sa.ForeignKey("users.id"))
    )
    op.add_column("tasks", sa.Column("classification_updated_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE tasks SET legacy_classification = COALESCE(category, '') || "
        "CASE WHEN subcategory IS NOT NULL AND subcategory <> '' "
        "THEN ' / ' || subcategory ELSE '' END"
    )

    _hierarchy_foreign_keys("task_recurrence_templates")

    for column, target in (
        ("default_queue_id", "work_queues"),
        ("default_department_id", "work_departments"),
        ("default_category_id", "work_categories"),
        ("default_subcategory_id", "work_subcategories"),
    ):
        op.add_column("email_channels", sa.Column(column, sa.Integer(), nullable=True))
        op.create_index(f"ix_email_channels_{column}", "email_channels", [column])
        op.create_foreign_key(
            f"fk_email_channels_{column}",
            "email_channels",
            target,
            [column],
            ["id"],
            ondelete="SET NULL",
        )
    op.add_column(
        "email_channels",
        sa.Column("auto_task_mode", sa.String(40), nullable=False, server_default="none"),
    )
    op.create_index("ix_email_channels_auto_task_mode", "email_channels", ["auto_task_mode"])
    op.add_column("email_channels", sa.Column("default_document_type", sa.String(80)))
    op.create_index(
        "ix_email_channels_default_document_type", "email_channels", ["default_document_type"]
    )
    op.add_column(
        "email_channels",
        sa.Column(
            "default_assignee_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
    )
    op.create_index(
        "ix_email_channels_default_assignee_id", "email_channels", ["default_assignee_id"]
    )
    op.add_column("email_channels", sa.Column("default_due_days", sa.Integer()))
    op.add_column("email_channels", sa.Column("default_wait_days", sa.Integer()))

    _hierarchy_foreign_keys("email_threads")
    op.add_column(
        "email_threads",
        sa.Column(
            "classification_status", sa.String(40), nullable=False, server_default="unclassified"
        ),
    )
    op.create_index(
        "ix_email_threads_classification_status", "email_threads", ["classification_status"]
    )
    op.add_column("email_threads", sa.Column("classification_other_text", sa.Text()))
    op.add_column("email_threads", sa.Column("due_at", sa.DateTime(timezone=True)))
    op.create_index("ix_email_threads_due_at", "email_threads", ["due_at"])
    op.add_column("email_threads", sa.Column("waiting_until", sa.DateTime(timezone=True)))
    op.create_index("ix_email_threads_waiting_until", "email_threads", ["waiting_until"])

    op.create_table(
        "email_channel_roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("email_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("can_read", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("can_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_send_direct", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_approve", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_manage", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("channel_id", "role_id", name="uq_email_channel_role"),
    )
    op.create_index("ix_email_channel_roles_channel_id", "email_channel_roles", ["channel_id"])
    op.create_index("ix_email_channel_roles_role_id", "email_channel_roles", ["role_id"])

    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("subject_template", sa.String(500)),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column(
            "channel_id", sa.Integer(), sa.ForeignKey("email_channels.id", ondelete="SET NULL")
        ),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("work_categories.id", ondelete="SET NULL")
        ),
        sa.Column(
            "subcategory_id",
            sa.Integer(),
            sa.ForeignKey("work_subcategories.id", ondelete="SET NULL"),
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("code", name="uq_email_template_code"),
    )
    for column in ("code", "channel_id", "category_id", "subcategory_id", "active"):
        op.create_index(f"ix_email_templates_{column}", "email_templates", [column])

    queues = sa.table(
        "work_queues",
        sa.column("code", sa.String(80)),
        sa.column("name", sa.String(160)),
        sa.column("description", sa.Text()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        queues,
        [
            {
                "code": "tasks_support",
                "name": "Tarefas e Suporte",
                "description": "Trabalho operacional, apoio e acompanhamento.",
                "sort_order": 10,
            },
            {
                "code": "administration",
                "name": "Administração",
                "description": "Auditoria e trabalho administrativo reservado.",
                "sort_order": 20,
            },
        ],
    )
    department_definitions = (
        ("tasks_support", "operations", "Operações", False, 10),
        ("tasks_support", "fleet", "Frota", False, 20),
        ("tasks_support", "hr", "RH", False, 30),
        ("tasks_support", "management_planning", "Gestão e Planeamento", False, 40),
        ("tasks_support", "other", "Outro", True, 90),
        ("administration", "audit", "Auditoria", False, 10),
        ("administration", "other", "Outro", True, 90),
    )
    for queue_code, code, name, requires_description, sort_order in department_definitions:
        op.execute(
            sa.text(
                """
                INSERT INTO work_departments
                    (queue_id, code, name, requires_description, sort_order)
                SELECT id, :code, :name, :requires_description, :sort_order
                FROM work_queues
                WHERE code = :queue_code
                """
            ).bindparams(
                queue_code=queue_code,
                code=code,
                name=name,
                requires_description=requires_description,
                sort_order=sort_order,
            )
        )


def downgrade() -> None:
    op.drop_table("email_templates")
    op.drop_table("email_channel_roles")
    for column in ("waiting_until", "due_at"):
        op.drop_index(f"ix_email_threads_{column}", table_name="email_threads")
        op.drop_column("email_threads", column)
    op.drop_column("email_threads", "classification_other_text")
    op.drop_index("ix_email_threads_classification_status", table_name="email_threads")
    op.drop_column("email_threads", "classification_status")
    for column in (
        "work_subcategory_id",
        "work_category_id",
        "work_department_id",
        "work_queue_id",
    ):
        op.drop_constraint(f"fk_email_threads_{column}", "email_threads", type_="foreignkey")
        op.drop_index(f"ix_email_threads_{column}", table_name="email_threads")
        op.drop_column("email_threads", column)

    for column in ("default_wait_days", "default_due_days"):
        op.drop_column("email_channels", column)
    op.drop_index("ix_email_channels_default_assignee_id", table_name="email_channels")
    op.drop_column("email_channels", "default_assignee_id")
    op.drop_index("ix_email_channels_default_document_type", table_name="email_channels")
    op.drop_column("email_channels", "default_document_type")
    op.drop_index("ix_email_channels_auto_task_mode", table_name="email_channels")
    op.drop_column("email_channels", "auto_task_mode")
    for column in (
        "default_subcategory_id",
        "default_category_id",
        "default_department_id",
        "default_queue_id",
    ):
        op.drop_constraint(f"fk_email_channels_{column}", "email_channels", type_="foreignkey")
        op.drop_index(f"ix_email_channels_{column}", table_name="email_channels")
        op.drop_column("email_channels", column)

    for table in ("task_recurrence_templates", "tasks"):
        for column in (
            "work_subcategory_id",
            "work_category_id",
            "work_department_id",
            "work_queue_id",
        ):
            op.drop_constraint(f"fk_{table}_{column}", table, type_="foreignkey")
            op.drop_index(f"ix_{table}_{column}", table_name=table)
            op.drop_column(table, column)
    for column in (
        "classification_updated_at",
        "classification_updated_by_id",
        "legacy_classification",
        "classification_other_text",
    ):
        op.drop_column("tasks", column)
    op.drop_index("ix_tasks_classification_status", table_name="tasks")
    op.drop_column("tasks", "classification_status")

    op.drop_table("work_source_defaults")
    op.drop_table("role_work_scopes")
    op.drop_table("work_subcategories")
    op.drop_table("work_categories")
    op.drop_table("work_departments")
    op.drop_table("work_queues")
