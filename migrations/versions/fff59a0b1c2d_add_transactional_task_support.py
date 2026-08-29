"""Add transactional task support lifecycle.

Revision ID: fff59a0b1c2d
Revises: fff48a9b0c1e
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fff59a0b1c2d"
down_revision: str | Sequence[str] | None = "fff48a9b0c1e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    invalid_targets = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM task_help_requests WHERE "
            "(requested_user_id IS NULL AND requested_team_id IS NULL) OR "
            "(requested_user_id IS NOT NULL AND requested_team_id IS NOT NULL)"
        )
    ).scalar_one()
    duplicate_active_tasks = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM (SELECT task_id FROM task_help_requests "
            "WHERE status IN ('pending', 'accepted') GROUP BY task_id "
            "HAVING COUNT(*) > 1) AS duplicate_support_tasks"
        )
    ).scalar_one()
    if invalid_targets or duplicate_active_tasks:
        raise RuntimeError(
            "Task support migration preflight failed: "
            f"invalid_targets={invalid_targets}, "
            f"duplicate_active_tasks={duplicate_active_tasks}. "
            "No automatic data reconciliation is permitted; export and resolve "
            "these synthetic/legacy records before retrying."
        )

    with op.batch_alter_table("task_help_requests") as batch_op:
        batch_op.add_column(sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("previous_task_status", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index("ix_task_help_requests_due_at", ["due_at"])

    # Preserve existing rows before constraints become authoritative.
    op.execute("UPDATE task_help_requests SET previous_task_status = 'new' WHERE previous_task_status IS NULL")
    op.execute("UPDATE task_help_requests SET status = 'completed', completed_at = responded_at WHERE status = 'responded'")
    with op.batch_alter_table("task_help_requests") as batch_op:
        batch_op.alter_column("previous_task_status", existing_type=sa.String(80), nullable=False)
        batch_op.create_check_constraint(
            "ck_task_help_requests_single_target",
            "(requested_user_id IS NOT NULL AND requested_team_id IS NULL) OR "
            "(requested_user_id IS NULL AND requested_team_id IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "ck_task_help_requests_status",
            "status IN ('pending', 'accepted', 'completed', 'cancelled')",
        )

    active = sa.text("status IN ('pending', 'accepted')")
    op.create_index(
        "uq_task_help_active_user", "task_help_requests",
        ["task_id", "requested_user_id"], unique=True, postgresql_where=active, sqlite_where=active,
    )
    op.create_index(
        "uq_task_help_active_team", "task_help_requests",
        ["task_id", "requested_team_id"], unique=True, postgresql_where=active, sqlite_where=active,
    )
    op.create_index(
        "uq_task_help_active_task", "task_help_requests",
        ["task_id"], unique=True, postgresql_where=active, sqlite_where=active,
    )


def downgrade() -> None:
    # Restore task state before removing the only deterministic record of it.
    op.execute(
        "UPDATE tasks SET status = COALESCE((SELECT previous_task_status "
        "FROM task_help_requests WHERE task_help_requests.task_id = tasks.id "
        "AND status IN ('pending', 'accepted') ORDER BY id DESC LIMIT 1), 'new') "
        "WHERE status = 'support_requested'"
    )
    op.drop_index("uq_task_help_active_task", table_name="task_help_requests")
    op.drop_index("uq_task_help_active_team", table_name="task_help_requests")
    op.drop_index("uq_task_help_active_user", table_name="task_help_requests")
    with op.batch_alter_table("task_help_requests") as batch_op:
        batch_op.drop_constraint("ck_task_help_requests_status", type_="check")
        batch_op.drop_constraint("ck_task_help_requests_single_target", type_="check")
    op.execute("UPDATE task_help_requests SET status = 'responded', responded_at = COALESCE(completed_at, accepted_at, responded_at) WHERE status IN ('accepted', 'completed')")
    with op.batch_alter_table("task_help_requests") as batch_op:
        batch_op.drop_index("ix_task_help_requests_due_at")
        batch_op.drop_column("cancelled_at")
        batch_op.drop_column("completed_at")
        batch_op.drop_column("accepted_at")
        batch_op.drop_column("previous_task_status")
        batch_op.drop_column("due_at")
