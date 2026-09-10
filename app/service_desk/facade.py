from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.service_desk.compat import (
    EmailThreadRecord,
    ProcessRecord,
    TaskEmailOriginRecord,
    TaskRecord,
)
from app.service_desk.contracts import EmailOriginCommand, ServiceDeskReference, WorkSummary
from app.services.service_desk import initialize_task_service_desk


class ServiceDeskFacade:
    """Application boundary for Tasks, Processes and Email compatibility records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def task(self, reference: ServiceDeskReference | int) -> TaskRecord | None:
        task_id = reference.id if isinstance(reference, ServiceDeskReference) else reference
        return self.db.get(TaskRecord, task_id)

    def process(self, reference: ServiceDeskReference | int) -> ProcessRecord | None:
        process_id = reference.id if isinstance(reference, ServiceDeskReference) else reference
        return self.db.get(ProcessRecord, process_id)

    def email(self, reference: ServiceDeskReference | int) -> EmailThreadRecord | None:
        thread_id = reference.id if isinstance(reference, ServiceDeskReference) else reference
        return self.db.get(EmailThreadRecord, thread_id)

    def create_task(
        self,
        task: TaskRecord,
        *,
        actor_user_id: int | None = None,
        requested_user_id: int | None = None,
        requested_team_id: int | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        self.persist_task(task)
        return self.initialize_task(
            task,
            actor_user_id=actor_user_id,
            requested_user_id=requested_user_id,
            requested_team_id=requested_team_id,
            now=now,
        )

    def persist_task(self, task: TaskRecord) -> TaskRecord:
        self.db.add(task)
        self.db.flush()
        return task

    def initialize_task(
        self,
        task: TaskRecord,
        *,
        actor_user_id: int | None = None,
        requested_user_id: int | None = None,
        requested_team_id: int | None = None,
        now: datetime | None = None,
    ) -> TaskRecord:
        initialize_task_service_desk(
            self.db,
            task,
            actor_user_id=actor_user_id,
            requested_user_id=requested_user_id,
            requested_team_id=requested_team_id,
            now=now,
        )
        return task

    def link_email_origin(self, task_id: int, command: EmailOriginCommand) -> TaskEmailOriginRecord:
        origin = TaskEmailOriginRecord(
            task_id=task_id,
            message_id=command.message_id,
            sender=command.sender,
            recipients_json=command.recipients,
            subject=command.subject,
            received_at=command.received_at,
            mailbox=command.mailbox,
            source_url=command.source_url,
            rule_code=command.rule_code,
        )
        self.db.add(origin)
        return origin

    @staticmethod
    def task_summary(task: TaskRecord) -> WorkSummary:
        return WorkSummary(
            reference=ServiceDeskReference("task", task.id),
            title=task.title,
            status=task.status,
            assigned_user_id=task.assigned_to_id,
            assigned_team_id=task.team_id,
            due_at=task.resolution_due_at,
        )

    @staticmethod
    def process_summary(process: ProcessRecord) -> WorkSummary:
        return WorkSummary(
            reference=ServiceDeskReference("process", process.id),
            title=process.title,
            status=process.status,
        )

    @staticmethod
    def email_summary(thread: EmailThreadRecord) -> WorkSummary:
        return WorkSummary(
            reference=ServiceDeskReference("email", thread.id),
            title=thread.subject,
            status=thread.status,
            assigned_user_id=thread.assigned_to_id,
            assigned_team_id=thread.executor_team_id,
            due_at=thread.resolution_due_at,
        )

    @staticmethod
    def historical_summary(
        snapshot: dict[str, object] | None, *, can_read: bool
    ) -> WorkSummary | None:
        if not can_read or not snapshot:
            return None
        try:
            return WorkSummary(
                reference=ServiceDeskReference.parse(str(snapshot["reference"])),
                title=str(snapshot["title"]),
                status=str(snapshot["status"]),
                assigned_user_id=_optional_int(snapshot.get("assigned_user_id")),
                assigned_team_id=_optional_int(snapshot.get("assigned_team_id")),
                due_at=datetime.fromisoformat(str(snapshot["due_at"]))
                if snapshot.get("due_at")
                else None,
            )
        except (KeyError, TypeError, ValueError):
            return None


def _optional_int(value: object) -> int | None:
    return int(value) if value not in (None, "") else None
