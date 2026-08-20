"""add service desk and email operational controls

Revision ID: ffbe1e2f3a4c
Revises: ffad1e2f3a4b
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffbe1e2f3a4c"
down_revision: str | Sequence[str] | None = "ffad1e2f3a4b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PERMISSIONS = {
    "service_desk.read": "Consultar tickets do Service Desk",
    "service_desk.create": "Criar tickets do Service Desk",
    "service_desk.assume": "Assumir tickets elegíveis",
    "service_desk.assign": "Atribuir executores elegíveis",
    "service_desk.update": "Alterar tickets do Service Desk",
    "service_desk.respond": "Responder em tickets do Service Desk",
    "service_desk.complete": "Concluir tickets do Service Desk",
    "service_desk.sla.manage": "Gerir SLA do Service Desk",
    "service_desk.classifications.manage": "Administrar classificações do Service Desk",
    "email.assume": "Assumir conversas de email elegíveis",
    "email.assign": "Atribuir conversas de email",
    "email.sla.manage": "Gerir SLA de email",
}

ROLE_PERMISSIONS = {
    "admin": set(PERMISSIONS),
    "functional_admin": set(PERMISSIONS),
    "manager": {
        "service_desk.read",
        "service_desk.create",
        "service_desk.assume",
        "service_desk.assign",
        "service_desk.update",
        "service_desk.respond",
        "service_desk.complete",
        "service_desk.sla.manage",
    },
    "operator": {
        "service_desk.read",
        "service_desk.create",
        "service_desk.assume",
        "service_desk.update",
        "service_desk.respond",
        "service_desk.complete",
    },
    "viewer": {"service_desk.read"},
}


def _quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_list(values: set[str] | dict[str, str]) -> str:
    return ", ".join(_quoted(value) for value in sorted(values))


def _seed_permissions() -> None:
    for code, name in PERMISSIONS.items():
        op.execute(
            "INSERT INTO permissions (code, name, description) "
            f"VALUES ({_quoted(code)}, {_quoted(name)}, NULL) "
            "ON CONFLICT (code) DO NOTHING"
        )
    for role_code, permission_codes in ROLE_PERMISSIONS.items():
        op.execute(
            "INSERT INTO role_permissions (role_id, permission_id) "
            "SELECT roles.id, permissions.id FROM roles CROSS JOIN permissions "
            f"WHERE roles.code = {_quoted(role_code)} "
            f"AND permissions.code IN ({_sql_list(permission_codes)}) "
            "ON CONFLICT (role_id, permission_id) DO NOTHING"
        )


def _remove_permissions() -> None:
    permission_codes = _sql_list(PERMISSIONS)
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        f"(SELECT id FROM permissions WHERE code IN ({permission_codes}))"
    )
    op.execute(f"DELETE FROM permissions WHERE code IN ({permission_codes})")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def _indexed_columns(table: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    op.create_table(
        "service_desk_ticket_types",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(80), nullable=False, unique=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("form_schema_json", sa.JSON()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        *_timestamps(),
    )
    _indexed_columns("service_desk_ticket_types", ("code", "active"))

    op.create_table(
        "service_desk_category_policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("work_categories.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("assignment_mode", sa.String(40), nullable=False, server_default="manual"),
        sa.Column(
            "default_executor_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "default_executor_team_id",
            sa.Integer(),
            sa.ForeignKey("teams.id", ondelete="SET NULL"),
        ),
        sa.Column("first_response_minutes", sa.Integer()),
        sa.Column("resolution_minutes", sa.Integer()),
        sa.Column("warning_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("pause_on_waiting", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("timezone", sa.String(80), nullable=False, server_default="Europe/Lisbon"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.CheckConstraint(
            "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
            name="ck_service_desk_category_policy_assignment_mode",
        ),
        sa.CheckConstraint(
            "(first_response_minutes IS NULL OR first_response_minutes >= 0) AND "
            "(resolution_minutes IS NULL OR resolution_minutes >= 0) AND "
            "warning_minutes >= 0",
            name="ck_service_desk_category_policy_sla_minutes",
        ),
    )
    _indexed_columns(
        "service_desk_category_policies",
        (
            "category_id",
            "assignment_mode",
            "default_executor_user_id",
            "default_executor_team_id",
            "active",
        ),
    )

    op.create_table(
        "service_desk_category_supervisors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("work_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint("category_id", "user_id", name="uq_service_desk_category_supervisor"),
    )
    _indexed_columns("service_desk_category_supervisors", ("category_id", "user_id", "active"))

    op.create_table(
        "service_desk_category_executors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("work_categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="CASCADE")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint(
            "category_id", "user_id", "team_id", name="uq_service_desk_category_executor"
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND team_id IS NULL) OR "
            "(user_id IS NULL AND team_id IS NOT NULL)",
            name="ck_service_desk_category_executor_target",
        ),
    )
    _indexed_columns(
        "service_desk_category_executors", ("category_id", "user_id", "team_id", "active")
    )
    # A composite UNIQUE with one deliberately NULL target does not reject duplicates on
    # PostgreSQL. These partial indexes enforce one active/inactive row per concrete target.
    op.create_index(
        "uq_service_desk_category_executor_user",
        "service_desk_category_executors",
        ["category_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_service_desk_category_executor_team",
        "service_desk_category_executors",
        ["category_id", "team_id"],
        unique=True,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )

    for name, column in (
        (
            "can_assume",
            sa.Column("can_assume", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        (
            "can_respond",
            sa.Column("can_respond", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        (
            "can_complete",
            sa.Column("can_complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        (
            "can_manage_sla",
            sa.Column("can_manage_sla", sa.Boolean(), nullable=False, server_default=sa.false()),
        ),
        (
            "can_administer_classifications",
            sa.Column(
                "can_administer_classifications",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        ),
        (
            "visibility_mode",
            sa.Column("visibility_mode", sa.String(40), nullable=False, server_default="scope_all"),
        ),
    ):
        op.add_column("role_work_scopes", column)
        if name == "visibility_mode":
            op.create_index("ix_role_work_scopes_visibility_mode", "role_work_scopes", [name])
    op.execute(
        "UPDATE role_work_scopes SET can_assume = can_update, can_respond = can_update, "
        "can_complete = can_close, can_manage_sla = can_manage, "
        "can_administer_classifications = can_manage"
    )
    op.create_check_constraint(
        "ck_role_work_scopes_visibility_mode",
        "role_work_scopes",
        "visibility_mode IN ('scope_all', 'direct_only', 'consult')",
    )

    task_columns = (
        sa.Column(
            "ticket_type_id",
            sa.Integer(),
            sa.ForeignKey("service_desk_ticket_types.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "supervisor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("assignment_mode", sa.String(40), nullable=False, server_default="manual"),
        sa.Column(
            "assignment_state", sa.String(40), nullable=False, server_default="waiting_assignment"
        ),
        sa.Column("assigned_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("first_response_due_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_due_at", sa.DateTime(timezone=True)),
        sa.Column("sla_first_response_minutes", sa.Integer()),
        sa.Column("sla_resolution_minutes", sa.Integer()),
        sa.Column("sla_warning_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("sla_pause_on_waiting", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sla_timezone", sa.String(80), nullable=False, server_default="Europe/Lisbon"),
        sa.Column("sla_paused_at", sa.DateTime(timezone=True)),
        sa.Column("sla_total_paused_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in task_columns:
        op.add_column("tasks", column)
    _indexed_columns(
        "tasks",
        (
            "ticket_type_id",
            "supervisor_user_id",
            "assignment_mode",
            "assignment_state",
            "first_response_due_at",
            "resolution_due_at",
        ),
    )
    op.execute(
        "UPDATE tasks SET assignment_state = CASE "
        "WHEN assigned_to_id IS NOT NULL THEN 'assigned_user' "
        "WHEN team_id IS NOT NULL THEN 'assigned_team' ELSE 'waiting_assignment' END"
    )
    op.create_check_constraint(
        "ck_tasks_assignment_mode",
        "tasks",
        "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
    )
    op.create_check_constraint(
        "ck_tasks_assignment_state",
        "tasks",
        "assignment_state IN "
        "('assigned_user', 'assigned_team', 'team_unclaimed', 'waiting_assignment')",
    )
    op.create_check_constraint(
        "ck_tasks_sla_minutes",
        "tasks",
        "(sla_first_response_minutes IS NULL OR sla_first_response_minutes >= 0) AND "
        "(sla_resolution_minutes IS NULL OR sla_resolution_minutes >= 0) AND "
        "sla_warning_minutes >= 0 AND sla_total_paused_seconds >= 0",
    )

    op.create_table(
        "task_assignment_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("from_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("to_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("from_team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column("to_team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column("details_json", sa.JSON()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    _indexed_columns("task_assignment_events", ("task_id", "actor_user_id", "action"))

    op.create_table(
        "task_sla_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("actor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("details_json", sa.JSON()),
    )
    _indexed_columns("task_sla_events", ("task_id", "actor_user_id", "action", "occurred_at"))

    email_channel_columns = (
        sa.Column("inbound_forward_address", sa.String(255)),
        sa.Column("default_team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column(
            "supervisor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("assignment_mode", sa.String(40), nullable=False, server_default="manual"),
        sa.Column("first_response_minutes", sa.Integer()),
        sa.Column("resolution_minutes", sa.Integer()),
        sa.Column("warning_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("pause_on_waiting", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    for column in email_channel_columns:
        op.add_column("email_channels", column)
    _indexed_columns(
        "email_channels",
        ("inbound_forward_address", "default_team_id", "supervisor_user_id", "assignment_mode"),
    )
    op.create_index(
        "ux_email_channels_inbound_forward_address",
        "email_channels",
        ["inbound_forward_address"],
        unique=True,
    )
    op.execute(
        "UPDATE email_channels SET assignment_mode = CASE WHEN default_assignee_id IS NOT NULL "
        "THEN 'auto_user' ELSE 'manual' END, "
        "resolution_minutes = CASE WHEN default_due_days >= 0 "
        "THEN default_due_days * 1440 ELSE NULL END"
    )
    op.create_check_constraint(
        "ck_email_channels_assignment_mode",
        "email_channels",
        "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
    )
    op.create_check_constraint(
        "ck_email_channels_sla_minutes",
        "email_channels",
        "(first_response_minutes IS NULL OR first_response_minutes >= 0) AND "
        "(resolution_minutes IS NULL OR resolution_minutes >= 0) AND warning_minutes >= 0",
    )

    email_rule_columns = (
        sa.Column("default_team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column(
            "supervisor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("assignment_mode", sa.String(40)),
        sa.Column("first_response_minutes", sa.Integer()),
        sa.Column("resolution_minutes", sa.Integer()),
        sa.Column("warning_minutes", sa.Integer()),
        sa.Column("pause_on_waiting", sa.Boolean()),
    )
    for column in email_rule_columns:
        op.add_column("email_inbox_rules", column)
    _indexed_columns(
        "email_inbox_rules",
        ("default_team_id", "supervisor_user_id", "assignment_mode"),
    )
    op.execute(
        "UPDATE email_inbox_rules SET assignment_mode = CASE "
        "WHEN default_assignee_id IS NOT NULL THEN 'auto_user' ELSE NULL END, "
        "resolution_minutes = CASE WHEN default_due_days >= 0 "
        "THEN default_due_days * 1440 ELSE NULL END"
    )
    op.create_check_constraint(
        "ck_email_inbox_rules_assignment_mode",
        "email_inbox_rules",
        "assignment_mode IS NULL OR "
        "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
    )
    op.create_check_constraint(
        "ck_email_inbox_rules_sla_minutes",
        "email_inbox_rules",
        "(first_response_minutes IS NULL OR first_response_minutes >= 0) AND "
        "(resolution_minutes IS NULL OR resolution_minutes >= 0) AND "
        "(warning_minutes IS NULL OR warning_minutes >= 0)",
    )

    email_thread_columns = (
        sa.Column("executor_team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="SET NULL")),
        sa.Column(
            "supervisor_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assignment_mode", sa.String(40), nullable=False, server_default="manual"),
        sa.Column(
            "assignment_state", sa.String(40), nullable=False, server_default="waiting_assignment"
        ),
        sa.Column("assigned_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("assigned_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("first_response_due_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_due_at", sa.DateTime(timezone=True)),
        sa.Column("first_response_at", sa.DateTime(timezone=True)),
        sa.Column("sla_first_response_minutes", sa.Integer()),
        sa.Column("sla_resolution_minutes", sa.Integer()),
        sa.Column("sla_warning_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("sla_pause_on_waiting", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sla_timezone", sa.String(80), nullable=False, server_default="Europe/Lisbon"),
        sa.Column("sla_paused_at", sa.DateTime(timezone=True)),
        sa.Column("sla_total_paused_seconds", sa.Integer(), nullable=False, server_default="0"),
    )
    for column in email_thread_columns:
        op.add_column("email_threads", column)
    _indexed_columns(
        "email_threads",
        (
            "executor_team_id",
            "supervisor_user_id",
            "created_by_id",
            "assignment_mode",
            "assignment_state",
            "first_response_due_at",
            "resolution_due_at",
        ),
    )
    op.execute(
        "UPDATE email_threads SET assignment_state = CASE WHEN assigned_to_id IS NOT NULL "
        "THEN 'assigned_user' ELSE 'waiting_assignment' END, resolution_due_at = due_at"
    )
    op.create_check_constraint(
        "ck_email_threads_assignment_mode",
        "email_threads",
        "assignment_mode IN ('auto_user', 'auto_team', 'team_claim', 'manual')",
    )
    op.create_check_constraint(
        "ck_email_threads_assignment_state",
        "email_threads",
        "assignment_state IN "
        "('assigned_user', 'assigned_team', 'team_unclaimed', 'waiting_assignment')",
    )
    op.create_check_constraint(
        "ck_email_threads_sla_minutes",
        "email_threads",
        "(sla_first_response_minutes IS NULL OR sla_first_response_minutes >= 0) AND "
        "(sla_resolution_minutes IS NULL OR sla_resolution_minutes >= 0) AND "
        "sla_warning_minutes >= 0 AND sla_total_paused_seconds >= 0",
    )

    for table in ("email_channel_users", "email_channel_roles"):
        for name in ("can_assume", "can_assign", "can_manage_sla"):
            op.add_column(
                table,
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.false()),
            )
        op.add_column(
            table,
            sa.Column("visibility_mode", sa.String(40), nullable=False, server_default="scope_all"),
        )
        legacy_manage_field = "can_manage" if table == "email_channel_roles" else "can_approve"
        op.execute(
            f"UPDATE {table} SET can_assume = can_reply, "
            f"can_assign = {legacy_manage_field}, can_manage_sla = {legacy_manage_field}"
        )
        op.create_check_constraint(
            f"ck_{table}_visibility_mode",
            table,
            "visibility_mode IN ('scope_all', 'direct_only', 'consult')",
        )

    op.create_table(
        "email_executor_eligibilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "channel_id",
            sa.Integer(),
            sa.ForeignKey("email_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "category_id", sa.Integer(), sa.ForeignKey("work_categories.id", ondelete="CASCADE")
        ),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("team_id", sa.Integer(), sa.ForeignKey("teams.id", ondelete="CASCADE")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.UniqueConstraint(
            "channel_id",
            "category_id",
            "user_id",
            "team_id",
            name="uq_email_executor_eligibility",
        ),
        sa.CheckConstraint(
            "(user_id IS NOT NULL AND team_id IS NULL) OR "
            "(user_id IS NULL AND team_id IS NOT NULL)",
            name="ck_email_executor_eligibility_target",
        ),
    )
    _indexed_columns(
        "email_executor_eligibilities",
        ("channel_id", "category_id", "user_id", "team_id", "active"),
    )
    # category_id may be NULL for channel-wide eligibility, so use a sentinel expression
    # to make NULL categories participate in uniqueness on every supported PostgreSQL version.
    for target in ("user", "team"):
        target_column = f"{target}_id"
        op.create_index(
            f"uq_email_executor_eligibility_{target}",
            "email_executor_eligibilities",
            ["channel_id", sa.text("COALESCE(category_id, -1)"), target_column],
            unique=True,
            postgresql_where=sa.text(f"{target_column} IS NOT NULL"),
        )
    op.execute(
        "INSERT INTO email_executor_eligibilities (channel_id, user_id, active) "
        "SELECT id, default_assignee_id, TRUE FROM email_channels "
        "WHERE default_assignee_id IS NOT NULL"
    )

    ticket_types = sa.table(
        "service_desk_ticket_types",
        sa.column("code", sa.String(80)),
        sa.column("name", sa.String(160)),
        sa.column("description", sa.Text()),
        sa.column("sort_order", sa.Integer()),
    )
    op.bulk_insert(
        ticket_types,
        [
            {
                "code": "task",
                "name": "Tarefa",
                "description": "Trabalho a executar.",
                "sort_order": 10,
            },
            {
                "code": "request",
                "name": "Pedido",
                "description": "Pedido de serviço ou informação.",
                "sort_order": 20,
            },
            {
                "code": "communication",
                "name": "Comunicação",
                "description": "Comunicação a acompanhar.",
                "sort_order": 30,
            },
            {
                "code": "internal_help",
                "name": "Ajuda interna",
                "description": "Pedido de apoio interno.",
                "sort_order": 40,
            },
            {
                "code": "incident",
                "name": "Incidente",
                "description": "Interrupção ou anomalia operacional.",
                "sort_order": 50,
            },
            {
                "code": "approval",
                "name": "Aprovação",
                "description": "Decisão ou aprovação formal.",
                "sort_order": 60,
            },
        ],
    )
    _seed_permissions()


def downgrade() -> None:
    _remove_permissions()
    for target in ("team", "user"):
        op.drop_index(
            f"uq_email_executor_eligibility_{target}",
            table_name="email_executor_eligibilities",
        )
    op.drop_table("email_executor_eligibilities")
    for table in ("email_channel_roles", "email_channel_users"):
        op.drop_constraint(f"ck_{table}_visibility_mode", table, type_="check")
        for name in ("visibility_mode", "can_manage_sla", "can_assign", "can_assume"):
            op.drop_column(table, name)
    for name in (
        "ck_email_threads_sla_minutes",
        "ck_email_threads_assignment_state",
        "ck_email_threads_assignment_mode",
    ):
        op.drop_constraint(name, "email_threads", type_="check")
    for name in (
        "resolution_due_at",
        "first_response_due_at",
        "assignment_state",
        "assignment_mode",
        "created_by_id",
        "supervisor_user_id",
        "executor_team_id",
    ):
        op.drop_index(f"ix_email_threads_{name}", table_name="email_threads")
    for name in (
        "sla_total_paused_seconds",
        "sla_paused_at",
        "sla_timezone",
        "sla_pause_on_waiting",
        "sla_warning_minutes",
        "sla_resolution_minutes",
        "sla_first_response_minutes",
        "first_response_at",
        "resolution_due_at",
        "first_response_due_at",
        "claimed_at",
        "claimed_by_id",
        "assigned_at",
        "assigned_by_id",
        "assignment_state",
        "assignment_mode",
        "created_by_id",
        "supervisor_user_id",
        "executor_team_id",
    ):
        op.drop_column("email_threads", name)
    for name in ("assignment_mode", "supervisor_user_id", "default_team_id"):
        op.drop_index(f"ix_email_inbox_rules_{name}", table_name="email_inbox_rules")
    for name in (
        "ck_email_inbox_rules_sla_minutes",
        "ck_email_inbox_rules_assignment_mode",
    ):
        op.drop_constraint(name, "email_inbox_rules", type_="check")
    for name in (
        "pause_on_waiting",
        "warning_minutes",
        "resolution_minutes",
        "first_response_minutes",
        "assignment_mode",
        "supervisor_user_id",
        "default_team_id",
    ):
        op.drop_column("email_inbox_rules", name)
    for name in (
        "assignment_mode",
        "supervisor_user_id",
        "default_team_id",
        "inbound_forward_address",
    ):
        op.drop_index(f"ix_email_channels_{name}", table_name="email_channels")
    op.drop_index("ux_email_channels_inbound_forward_address", table_name="email_channels")
    for name in (
        "ck_email_channels_sla_minutes",
        "ck_email_channels_assignment_mode",
    ):
        op.drop_constraint(name, "email_channels", type_="check")
    for name in (
        "pause_on_waiting",
        "warning_minutes",
        "resolution_minutes",
        "first_response_minutes",
        "assignment_mode",
        "supervisor_user_id",
        "default_team_id",
        "inbound_forward_address",
    ):
        op.drop_column("email_channels", name)
    op.drop_table("task_sla_events")
    op.drop_table("task_assignment_events")
    for name in (
        "ck_tasks_sla_minutes",
        "ck_tasks_assignment_state",
        "ck_tasks_assignment_mode",
    ):
        op.drop_constraint(name, "tasks", type_="check")
    for name in (
        "resolution_due_at",
        "first_response_due_at",
        "assignment_state",
        "assignment_mode",
        "supervisor_user_id",
        "ticket_type_id",
    ):
        op.drop_index(f"ix_tasks_{name}", table_name="tasks")
    for name in (
        "sla_total_paused_seconds",
        "sla_paused_at",
        "sla_timezone",
        "sla_pause_on_waiting",
        "sla_warning_minutes",
        "sla_resolution_minutes",
        "sla_first_response_minutes",
        "resolution_due_at",
        "first_response_due_at",
        "claimed_at",
        "claimed_by_id",
        "assigned_at",
        "assigned_by_id",
        "assignment_state",
        "assignment_mode",
        "supervisor_user_id",
        "ticket_type_id",
    ):
        op.drop_column("tasks", name)
    op.drop_index("ix_role_work_scopes_visibility_mode", table_name="role_work_scopes")
    op.drop_constraint("ck_role_work_scopes_visibility_mode", "role_work_scopes", type_="check")
    for name in (
        "visibility_mode",
        "can_administer_classifications",
        "can_manage_sla",
        "can_complete",
        "can_respond",
        "can_assume",
    ):
        op.drop_column("role_work_scopes", name)
    for target in ("team", "user"):
        op.drop_index(
            f"uq_service_desk_category_executor_{target}",
            table_name="service_desk_category_executors",
        )
    op.drop_table("service_desk_category_executors")
    op.drop_table("service_desk_category_supervisors")
    op.drop_table("service_desk_category_policies")
    op.drop_table("service_desk_ticket_types")
