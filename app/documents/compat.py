"""Compatibility aliases over the unchanged document storage."""

from app.models.documents import Document, DocumentEvent, DocumentLink, DocumentWorkflowState

DocumentRecord = Document
DocumentAuditEvent = DocumentEvent
DocumentAssociation = DocumentLink
DocumentLifecycle = DocumentWorkflowState

__all__ = [
    "DocumentAssociation",
    "DocumentAuditEvent",
    "DocumentLifecycle",
    "DocumentRecord",
]
