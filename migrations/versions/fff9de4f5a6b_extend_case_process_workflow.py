"""Extend canonical cases and processes with workflow execution.

Revision ID: fff9de4f5a6b
Revises: fff8cd3e4f5a
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff9de4f5a6b"
down_revision: str | Sequence[str] | None = "fff8cd3e4f5a"
branch_labels = None
depends_on = None

PERMISSIONS = {
    "cases.close_override": "Fechar casos com processos ativos",
    "cases.reopen": "Reabrir casos operacionais",
    "process.instances.delegate": "Delegar fases para tarefas",
    "process.instances.validate": "Validar fases sensíveis",
    "process.instances.reopen": "Reabrir processos e fases",
}


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    with op.batch_alter_table("task_cases") as batch_op:
        batch_op.drop_constraint("ck_task_cases_workspace", type_="check")
        batch_op.add_column(sa.Column("public_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("human_code", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("organizational_unit_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("status", sa.String(24), nullable=False, server_default="open")
        )
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_check_constraint(
            "ck_task_cases_workspace",
            "workspace IN ('tasks_support', 'administration', 'processes')",
        )
        batch_op.create_check_constraint(
            "ck_task_cases_status", "status IN ('open','suspended','closed')"
        )
        batch_op.create_foreign_key(
            "fk_task_cases_organizational_unit_id",
            "organizational_units",
            ["organizational_unit_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    if dialect == "postgresql":
        op.execute(
            "UPDATE task_cases SET public_id = "
            "substr(md5(id::text || clock_timestamp()::text || random()::text), 1, 8) || '-' || "
            "substr(md5(id::text || random()::text), 1, 4) || '-4' || "
            "substr(md5(random()::text), 1, 3) || '-a' || "
            "substr(md5(random()::text), 1, 3) || '-' || substr(md5(random()::text), 1, 12) "
            "WHERE public_id IS NULL"
        )
    else:
        rows = bind.execute(sa.text("SELECT id FROM task_cases WHERE public_id IS NULL")).all()
        for row in rows:
            bind.execute(
                sa.text("UPDATE task_cases SET public_id = :value WHERE id = :id"),
                {"id": row.id, "value": f"legacy-task-case-{row.id:020d}"[:36]},
            )
    with op.batch_alter_table("task_cases") as batch_op:
        batch_op.alter_column("public_id", existing_type=sa.String(36), nullable=False)
        batch_op.create_unique_constraint("uq_task_cases_public_id", ["public_id"])
        batch_op.create_unique_constraint("uq_task_cases_human_code", ["human_code"])
        batch_op.create_index("ix_task_cases_organizational_unit_id", ["organizational_unit_id"])
        batch_op.create_index("ix_task_cases_status", ["status"])
        batch_op.create_index("ix_task_cases_deleted_at", ["deleted_at"])

    with op.batch_alter_table("process_instances") as batch_op:
        batch_op.add_column(sa.Column("case_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("vehicle_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("process_kind", sa.String(80), nullable=False, server_default="generic")
        )
        batch_op.add_column(sa.Column("proposal_logical_id", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("accepted_proposal_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("operation_key", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("revision", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_process_instances_case_id", "task_cases", ["case_id"], ["id"], ondelete="RESTRICT"
        )
        batch_op.create_foreign_key(
            "fk_process_instances_vehicle_id",
            "vehicles",
            ["vehicle_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_unique_constraint("uq_process_instances_operation_key", ["operation_key"])
        for column in (
            "case_id",
            "vehicle_id",
            "process_kind",
            "proposal_logical_id",
            "deleted_at",
        ):
            batch_op.create_index(f"ix_process_instances_{column}", [column])
    op.create_index(
        "uq_process_instances_active_sale",
        "process_instances",
        ["proposal_logical_id", "vehicle_id", "process_kind"],
        unique=True,
        postgresql_where=sa.text(
            "deleted_at IS NULL AND proposal_logical_id IS NOT NULL "
            "AND status IN ('active','blocked')"
        ),
        sqlite_where=sa.text(
            "deleted_at IS NULL AND proposal_logical_id IS NOT NULL "
            "AND status IN ('active','blocked')"
        ),
    )

    op.create_table(
        "process_phase_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "process_instance_id",
            sa.Integer(),
            sa.ForeignKey("process_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("phase_key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("definition_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("execution_mode", sa.String(24), nullable=False, server_default="direct"),
        sa.Column("sensitive_validation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("validated_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("completed_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.CheckConstraint(
            "status IN ('pending','active','blocked','awaiting_validation','completed','skipped')",
            name="ck_process_phase_instances_status",
        ),
        sa.CheckConstraint(
            "execution_mode IN ('direct','task')",
            name="ck_process_phase_instances_execution_mode",
        ),
        sa.UniqueConstraint("process_instance_id", "phase_key", name="uq_process_phase_key"),
    )
    for column in ("process_instance_id", "phase_key", "status", "execution_mode", "deleted_at"):
        op.create_index(f"ix_process_phase_instances_{column}", "process_phase_instances", [column])

    op.create_table(
        "process_phase_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "phase_instance_id",
            sa.Integer(),
            sa.ForeignKey("process_phase_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="SET NULL")),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        *timestamps(),
        sa.CheckConstraint("kind IN ('direct','task')", name="ck_process_phase_execution_kind"),
        sa.CheckConstraint(
            "status IN ('pending','active','completed','cancelled')",
            name="ck_process_phase_execution_status",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_process_phase_execution_idempotency"),
    )
    for column in ("phase_instance_id", "kind", "status", "active", "task_id"):
        op.create_index(
            f"ix_process_phase_executions_{column}", "process_phase_executions", [column]
        )
    op.create_index(
        "uq_process_phase_active_execution",
        "process_phase_executions",
        ["phase_instance_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
        sqlite_where=sa.text("active = 1"),
    )

    op.create_table(
        "process_proposal_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "process_instance_id",
            sa.Integer(),
            sa.ForeignKey("process_instances.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("accepted_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("source_reference", sa.String(255)),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "process_instance_id", "proposal_version", name="uq_process_proposal_acceptance"
        ),
    )
    op.create_index(
        "ix_process_proposal_acceptances_process_instance_id",
        "process_proposal_acceptances",
        ["process_instance_id"],
    )

    op.create_table(
        "workflow_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revision", sa.Integer()),
        sa.Column("reason", sa.Text()),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("aggregate_type", "aggregate_id", "action"):
        op.create_index(f"ix_workflow_audit_events_{column}", "workflow_audit_events", [column])

    op.create_table(
        "workflow_outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(160), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key", name="uq_workflow_outbox_idempotency"),
    )
    for column in ("event_type", "aggregate_type", "aggregate_id", "status"):
        op.create_index(f"ix_workflow_outbox_events_{column}", "workflow_outbox_events", [column])

    _typed_link("case_vehicle_links", "vehicle_id", "vehicles")
    _typed_link("case_document_links", "document_id", "documents")
    _typed_link("case_email_links", "email_intake_id", "email_intakes")
    _typed_link("case_workshop_links", "workshop_process_id", "workshop_processes")

    for code, name in PERMISSIONS.items():
        exists = bind.execute(
            sa.text("SELECT 1 FROM permissions WHERE code = :code"), {"code": code}
        ).scalar_one_or_none()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (code, name, description) VALUES (:code, :name, NULL)"
                ),
                {"code": code, "name": name},
            )

    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_published_process_model_version()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP = 'DELETE' AND OLD.status <> 'draft' THEN
                RAISE EXCEPTION 'published or retired process model versions are immutable';
              END IF;
              IF TG_OP = 'UPDATE' AND OLD.status <> 'draft' THEN
                IF NOT (
                  OLD.status = 'published' AND NEW.status = 'retired'
                  AND (to_jsonb(NEW) - 'status' - 'updated_at')
                    = (to_jsonb(OLD) - 'status' - 'updated_at')
                ) THEN
                  RAISE EXCEPTION 'published or retired process model versions are immutable';
                END IF;
              END IF;
              RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END $$;
            CREATE TRIGGER trg_process_model_version_snapshot
            BEFORE UPDATE OR DELETE ON process_model_versions
            FOR EACH ROW EXECUTE FUNCTION protect_published_process_model_version();
            """
        )


def _typed_link(table: str, target_column: str, target_table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("task_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            target_column,
            sa.Integer(),
            sa.ForeignKey(f"{target_table}.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        *timestamps(),
        sa.UniqueConstraint("case_id", target_column, name=f"uq_{table[:-1]}"),
    )
    op.create_index(f"ix_{table}_case_id", table, ["case_id"])
    op.create_index(f"ix_{table}_{target_column}", table, [target_column])
    op.create_index(f"ix_{table}_ended_at", table, ["ended_at"])


def downgrade() -> None:
    bind = op.get_bind()
    populated = {}
    for table in (
        "process_phase_instances",
        "process_phase_executions",
        "process_proposal_acceptances",
        "workflow_audit_events",
        "workflow_outbox_events",
        "case_vehicle_links",
        "case_document_links",
        "case_email_links",
        "case_workshop_links",
    ):
        count = bind.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
        if count:
            populated[table] = count
    enriched = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM process_instances WHERE case_id IS NOT NULL "
            "OR vehicle_id IS NOT NULL "
            "OR proposal_logical_id IS NOT NULL OR operation_key IS NOT NULL"
        )
    ).scalar_one()
    if populated or enriched:
        raise RuntimeError(
            "Case workflow downgrade blocked to preserve data: "
            f"tables={populated}, processes={enriched}"
        )
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_process_model_version_snapshot ON process_model_versions"
        )
        op.execute("DROP FUNCTION IF EXISTS protect_published_process_model_version()")
    for table in (
        "case_workshop_links",
        "case_email_links",
        "case_document_links",
        "case_vehicle_links",
        "workflow_outbox_events",
        "workflow_audit_events",
        "process_proposal_acceptances",
        "process_phase_executions",
        "process_phase_instances",
    ):
        op.drop_table(table)
    op.drop_index("uq_process_instances_active_sale", table_name="process_instances")
    with op.batch_alter_table("process_instances") as batch_op:
        for column in (
            "case_id",
            "vehicle_id",
            "process_kind",
            "proposal_logical_id",
            "deleted_at",
        ):
            batch_op.drop_index(f"ix_process_instances_{column}")
        batch_op.drop_constraint("uq_process_instances_operation_key", type_="unique")
        batch_op.drop_constraint("fk_process_instances_vehicle_id", type_="foreignkey")
        batch_op.drop_constraint("fk_process_instances_case_id", type_="foreignkey")
        for column in (
            "deleted_at",
            "completed_at",
            "revision",
            "operation_key",
            "accepted_proposal_version",
            "proposal_logical_id",
            "process_kind",
            "vehicle_id",
            "case_id",
        ):
            batch_op.drop_column(column)
    with op.batch_alter_table("task_cases") as batch_op:
        batch_op.drop_index("ix_task_cases_deleted_at")
        batch_op.drop_index("ix_task_cases_status")
        batch_op.drop_index("ix_task_cases_organizational_unit_id")
        batch_op.drop_constraint("uq_task_cases_human_code", type_="unique")
        batch_op.drop_constraint("uq_task_cases_public_id", type_="unique")
        batch_op.drop_constraint("fk_task_cases_organizational_unit_id", type_="foreignkey")
        batch_op.drop_constraint("ck_task_cases_status", type_="check")
        batch_op.drop_constraint("ck_task_cases_workspace", type_="check")
        for column in (
            "deleted_at",
            "closed_at",
            "revision",
            "status",
            "organizational_unit_id",
            "human_code",
            "public_id",
        ):
            batch_op.drop_column(column)
        batch_op.create_check_constraint(
            "ck_task_cases_workspace", "workspace IN ('tasks_support', 'administration')"
        )
