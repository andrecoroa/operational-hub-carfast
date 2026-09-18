"""Reopen emails linked to tasks completed before event-based synchronization."""

from app.core.database import SessionLocal
from app.services.email_task_events import reconcile_completed_email_tasks


def main() -> None:
    with SessionLocal() as db:
        count = reconcile_completed_email_tasks(db)
        db.commit()
    print(f"Reopened {count} email conversation(s) after linked task completion.")


if __name__ == "__main__":
    main()
