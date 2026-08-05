"""Generate due task occurrences once; safe to call from a scheduler."""

from app.core.database import SessionLocal
from app.services.task_recurrence import generate_due_recurring_tasks


def main() -> None:
    with SessionLocal() as db:
        created = generate_due_recurring_tasks(db, max_occurrences=100, commit=True)
        print(f"Created {len(created)} recurring task occurrence(s).")


if __name__ == "__main__":
    main()
