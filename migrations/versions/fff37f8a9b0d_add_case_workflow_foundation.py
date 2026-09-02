"""Add the feature-flagged case workflow foundation (expand only)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff37f8a9b0d"
down_revision: str | Sequence[str] | None = "ffae1f2a3b4c"
branch_labels = None
depends_on = None


def ts() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "process_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("active", sa.Boolean(), nullable=False),
        *ts(),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "process_definition_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "definition_id",
            sa.Integer(),
            sa.ForeignKey("process_definitions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("change_note", sa.Text()),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        *ts(),
        sa.UniqueConstraint("definition_id", "version", name="uq_process_definition_version"),
        sa.CheckConstraint(
            "status IN ('draft','published','retired')",
            name="ck_process_definition_versions_definition_version_status",
        ),
    )
    op.create_table(
        "phase_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "definition_version_id",
            sa.Integer(),
            sa.ForeignKey("process_definition_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(80), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(80), nullable=False),
        sa.Column("instructions", sa.Text()),
        sa.Column("execution_policy", sa.String(40), nullable=False),
        sa.Column("sensitive_validation", sa.Boolean(), nullable=False),
        *ts(),
        sa.UniqueConstraint("definition_version_id", "key", name="uq_phase_definition_version_key"),
        sa.UniqueConstraint(
            "definition_version_id", "sort_order", name="uq_phase_definition_version_order"
        ),
        sa.UniqueConstraint("id", "definition_version_id", name="uq_phase_definition_id_version"),
    )
    op.create_table(
        "operational_cases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("human_code", sa.String(80)),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("organizational_unit_id", sa.Integer(), sa.ForeignKey("organizational_units.id")),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *ts(),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("human_code"),
        sa.CheckConstraint(
            "status IN ('open','suspended','closed')",
            name="ck_operational_cases_operational_case_status",
        ),
    )
    op.create_table(
        "process_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("operational_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "definition_version_id",
            sa.Integer(),
            sa.ForeignKey("process_definition_versions.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(220), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("vehicle_id", sa.Integer(), sa.ForeignKey("vehicles.id")),
        sa.Column("proposal_logical_id", sa.String(160)),
        sa.Column("process_kind", sa.String(80), nullable=False),
        sa.Column("accepted_proposal_version", sa.Integer()),
        sa.Column("operation_key", sa.String(320), nullable=False),
        sa.Column("owner_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("blocked_reason", sa.Text()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *ts(),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint("operation_key", name="uq_process_instance_operation_key"),
        sa.UniqueConstraint("id", "definition_version_id", name="uq_process_instance_id_version"),
        sa.CheckConstraint(
            "status IN ('draft','active','blocked','completed','cancelled')",
            name="ck_process_instances_process_instance_status",
        ),
    )
    op.create_index(
        "uq_process_instance_active_sale",
        "process_instances",
        ["proposal_logical_id", "vehicle_id", "process_kind"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND status IN ('draft','active','blocked')"),
        sqlite_where=sa.text("deleted_at IS NULL AND status IN ('draft','active','blocked')"),
    )
    op.create_table(
        "process_proposal_acceptances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "process_id",
            sa.Integer(),
            sa.ForeignKey("process_instances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("source_reference", sa.String(240)),
        sa.Column("accepted_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        *ts(),
        sa.UniqueConstraint("process_id", "proposal_version", name="uq_process_proposal_version"),
    )
    op.create_table(
        "phase_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("process_id", sa.Integer(), nullable=False),
        sa.Column("definition_phase_id", sa.Integer(), nullable=False),
        sa.Column("definition_version_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("execution_mode", sa.String(40)),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("completed_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("submitted_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("validated_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        *ts(),
        sa.UniqueConstraint("public_id"),
        sa.UniqueConstraint(
            "process_id", "definition_phase_id", name="uq_phase_instance_definition"
        ),
        sa.ForeignKeyConstraint(
            ["process_id", "definition_version_id"],
            ["process_instances.id", "process_instances.definition_version_id"],
            name="fk_phase_instance_process_version",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["definition_phase_id", "definition_version_id"],
            ["phase_definitions.id", "phase_definitions.definition_version_id"],
            name="fk_phase_instance_definition_version",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending','active','delegated','awaiting_validation',"
            "'blocked','completed','skipped')",
            name="ck_phase_instances_phase_instance_status",
        ),
    )
    op.create_table(
        "phase_executions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "phase_id",
            sa.Integer(),
            sa.ForeignKey("phase_instances.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="RESTRICT")),
        sa.Column("idempotency_key", sa.String(320), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        *ts(),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint(
            "kind IN ('direct','task','subprocess')",
            name="ck_phase_executions_phase_execution_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending','active','completed','terminated')",
            name="ck_phase_executions_phase_execution_status",
        ),
        sa.CheckConstraint(
            "(kind = 'task' AND (status = 'pending' OR task_id IS NOT NULL)) OR kind <> 'task'",
            name="ck_phase_executions_task_execution_has_task",
        ),
        sa.CheckConstraint(
            "(active AND status IN ('pending','active')) OR "
            "(NOT active AND status IN ('completed','terminated'))",
            name="ck_phase_executions_execution_active_status",
        ),
    )
    op.create_index(
        "uq_phase_executions_one_active",
        "phase_executions",
        ["phase_id"],
        unique=True,
        postgresql_where=sa.text("active IS TRUE"),
        sqlite_where=sa.text("active = 1"),
    )
    _typed_link("case_vehicle_links", "vehicle_id", "vehicles")
    _typed_link("case_document_links", "document_id", "documents")
    _typed_link("case_task_links", "task_id", "tasks")
    _typed_link("case_email_links", "email_intake_id", "email_intakes")
    _typed_link("case_workshop_links", "workshop_process_id", "workshop_processes")
    op.create_table(
        "workflow_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(120), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("before_json", sa.JSON()),
        sa.Column("after_json", sa.JSON()),
        sa.Column("idempotency_key", sa.String(320), unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workflow_outbox_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("event_key", sa.String(320), nullable=False, unique=True),
        sa.Column("event_type", sa.String(120), nullable=False),
        sa.Column("aggregate_type", sa.String(80), nullable=False),
        sa.Column("aggregate_id", sa.String(120), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for table, columns in {
        "process_definitions": ["active"],
        "process_definition_versions": ["definition_id", "status"],
        "phase_definitions": ["definition_version_id", "key", "block_type"],
        "operational_cases": ["status", "organizational_unit_id", "deleted_at"],
        "process_instances": [
            "case_id",
            "definition_version_id",
            "status",
            "vehicle_id",
            "proposal_logical_id",
            "process_kind",
            "deleted_at",
        ],
        "process_proposal_acceptances": ["process_id"],
        "phase_instances": [
            "process_id",
            "definition_phase_id",
            "definition_version_id",
            "status",
            "execution_mode",
            "deleted_at",
        ],
        "phase_executions": ["phase_id", "kind", "status", "active", "task_id"],
        "case_vehicle_links": ["case_id", "vehicle_id", "ended_at"],
        "case_document_links": ["case_id", "document_id", "ended_at"],
        "case_task_links": ["case_id", "task_id", "ended_at"],
        "case_email_links": ["case_id", "email_intake_id", "ended_at"],
        "case_workshop_links": ["case_id", "workshop_process_id", "ended_at"],
        "workflow_audit_events": ["aggregate_type", "aggregate_id", "action"],
        "workflow_outbox_events": ["event_type", "aggregate_type", "aggregate_id", "status"],
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE FUNCTION protect_process_definition_version_snapshot()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF TG_OP = 'DELETE' AND OLD.status <> 'draft' THEN
                RAISE EXCEPTION 'published or retired process versions are immutable';
              END IF;
              IF TG_OP = 'UPDATE' AND OLD.status <> 'draft' THEN
                IF NOT (
                  OLD.status = 'published' AND NEW.status = 'retired'
                  AND (to_jsonb(NEW) - 'status' - 'retired_at' - 'updated_at')
                    = (to_jsonb(OLD) - 'status' - 'retired_at' - 'updated_at')
                ) THEN
                  RAISE EXCEPTION 'published or retired process versions are immutable';
                END IF;
              END IF;
              RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END $$;
            CREATE TRIGGER trg_process_definition_version_snapshot
            BEFORE UPDATE OR DELETE ON process_definition_versions
            FOR EACH ROW EXECUTE FUNCTION protect_process_definition_version_snapshot();

            CREATE FUNCTION protect_phase_definition_snapshot()
            RETURNS trigger LANGUAGE plpgsql AS $$
            DECLARE old_snapshot_status varchar(40);
            DECLARE new_snapshot_status varchar(40);
            BEGIN
              IF TG_OP <> 'INSERT' THEN
                SELECT status INTO old_snapshot_status
                FROM process_definition_versions
                WHERE id = OLD.definition_version_id;
              END IF;
              IF TG_OP <> 'DELETE' THEN
                SELECT status INTO new_snapshot_status
                FROM process_definition_versions
                WHERE id = NEW.definition_version_id;
              END IF;
              IF (TG_OP <> 'INSERT' AND old_snapshot_status <> 'draft')
                OR (TG_OP <> 'DELETE' AND new_snapshot_status <> 'draft') THEN
                RAISE EXCEPTION 'phases of published or retired versions are immutable';
              END IF;
              RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
            END $$;
            CREATE TRIGGER trg_phase_definition_snapshot
            BEFORE INSERT OR UPDATE OR DELETE ON phase_definitions
            FOR EACH ROW EXECUTE FUNCTION protect_phase_definition_snapshot();
            """
        )


def _typed_link(table: str, target_column: str, target_table: str) -> None:
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey("operational_cases.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            target_column,
            sa.Integer(),
            sa.ForeignKey(f"{target_table}.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        *ts(),
        sa.UniqueConstraint("case_id", target_column, name=f"uq_{table[:-1]}"),
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            DROP TRIGGER IF EXISTS trg_phase_definition_snapshot ON phase_definitions;
            DROP FUNCTION IF EXISTS protect_phase_definition_snapshot();
            DROP TRIGGER IF EXISTS trg_process_definition_version_snapshot
              ON process_definition_versions;
            DROP FUNCTION IF EXISTS protect_process_definition_version_snapshot();
            """
        )
    for table in [
        "workflow_outbox_events",
        "workflow_audit_events",
        "case_workshop_links",
        "case_email_links",
        "case_task_links",
        "case_document_links",
        "case_vehicle_links",
        "phase_executions",
        "phase_instances",
        "process_proposal_acceptances",
        "process_instances",
        "operational_cases",
        "phase_definitions",
        "process_definition_versions",
        "process_definitions",
    ]:
        op.drop_table(table)
