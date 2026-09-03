from datetime import date, time

from sqlalchemy import select

from app.models.tasks import Task
from app.services.task_center import task_due_condition
from app.schemas.tasks import TaskCreate, TaskUpdate


def test_timed_deadline_crosses_risk_to_overdue_at_local_time(db_session) -> None:
    today = date(2026, 9, 3)
    before = Task(title="Antes", status="new", due_on=today, due_time=time(9, 59))
    after = Task(title="Depois", status="new", due_on=today, due_time=time(10, 1))
    date_only = Task(title="Só data", status="new", due_on=today)
    db_session.add_all([before, after, date_only])
    db_session.commit()

    overdue = set(
        db_session.scalars(
            select(Task.title).where(
                task_due_condition("overdue", today=today, local_time=time(10, 0))
            )
        )
    )
    risk = set(
        db_session.scalars(
            select(Task.title).where(
                task_due_condition("due_soon", today=today, local_time=time(10, 0))
            )
        )
    )

    assert "Antes" in overdue
    assert "Depois" not in overdue
    assert "Só data" not in overdue
    assert {"Depois", "Só data"}.issubset(risk)
    assert "Antes" not in risk


def test_api_contract_accepts_optional_time_without_changing_date_only_payloads() -> None:
    date_only = TaskCreate(title="Só data", due_on=date(2026, 9, 3))
    timed = TaskCreate(title="Com hora", due_on=date(2026, 9, 3), due_time=time(17, 15))
    partial = TaskUpdate(title="Sem tocar no prazo")

    assert date_only.due_time is None
    assert timed.due_time == time(17, 15)
    assert "due_time" not in partial.model_dump(exclude_unset=True)


def test_due_time_migration_is_additive_and_has_explicit_rollback() -> None:
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "migrations/versions/fff9de4f5a6b_add_task_due_time.py"
    ).read_text(encoding="utf-8")

    assert 'op.add_column("tasks", sa.Column("due_time", sa.Time(), nullable=True))' in source
    assert 'op.drop_column("tasks", "due_time")' in source
    assert "UPDATE tasks" not in source
