from app.documents.compat import (
    DocumentAssociation,
    DocumentAuditEvent,
    DocumentLifecycle,
    DocumentRecord,
)
from app.documents.contracts import (
    DocumentReference,
    DocumentSummary,
    LinkIngestionRequest,
    SourceReference,
)
from app.documents.facade import DocumentManagementFacade
from app.documents.manifest import DOCUMENTS_MANIFEST
from app.documents.permissions import DOCUMENT_PERMISSION_LEGACY_MAP, decide_document_permission

__all__ = [
    "DOCUMENTS_MANIFEST",
    "DOCUMENT_PERMISSION_LEGACY_MAP",
    "DocumentAssociation",
    "DocumentAuditEvent",
    "DocumentLifecycle",
    "DocumentManagementFacade",
    "DocumentRecord",
    "DocumentReference",
    "DocumentSummary",
    "LinkIngestionRequest",
    "SourceReference",
    "decide_document_permission",
]
