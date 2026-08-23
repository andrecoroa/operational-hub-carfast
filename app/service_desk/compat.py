"""Compatibility aliases over unchanged Service Desk storage."""

from app.models.email import EmailAuditEvent, EmailMessage, EmailThread
from app.models.management_center import ManagementHistory, ManagementProcess
from app.models.tasks import Task, TaskEmailOrigin, TaskHistory, TaskSlaEvent

TaskRecord = Task
TaskAuditRecord = TaskHistory
TaskSlaRecord = TaskSlaEvent
TaskEmailOriginRecord = TaskEmailOrigin
ProcessRecord = ManagementProcess
ProcessAuditRecord = ManagementHistory
EmailThreadRecord = EmailThread
EmailMessageRecord = EmailMessage
EmailAuditRecord = EmailAuditEvent

__all__ = [
    "EmailAuditRecord",
    "EmailMessageRecord",
    "EmailThreadRecord",
    "ProcessAuditRecord",
    "ProcessRecord",
    "TaskAuditRecord",
    "TaskEmailOriginRecord",
    "TaskRecord",
    "TaskSlaRecord",
]
