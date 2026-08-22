from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.compat import DocumentAssociation, DocumentAuditEvent, DocumentRecord
from app.documents.contracts import (
    DocumentReference,
    DocumentSummary,
    LinkIngestionRequest,
    SourceReference,
)


class DocumentManagementFacade:
    """Application boundary over the existing document tables and object references."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, reference: DocumentReference | int) -> DocumentRecord | None:
        document_id = reference.id if isinstance(reference, DocumentReference) else reference
        return self.db.get(DocumentRecord, document_id)

    def ingest_link(
        self,
        request: LinkIngestionRequest,
        *,
        source_reference: SourceReference | None = None,
        event_action: str = "document.received",
        event_detail: str | None = None,
        user_id: int | None = None,
    ) -> DocumentRecord:
        if not request.storage_path.strip():
            raise ValueError("Document storage path is required")
        title = request.title.strip() or "Documento"
        document = DocumentRecord(
            title=title[:200],
            document_type=request.document_type,
            classification=request.classification,
            status=request.status,
            source=request.source,
            entry_channel=request.entry_channel,
            source_sender=request.source_sender,
            source_subject=request.source_subject,
            original_name=(request.original_name or title)[:255],
            file_name=(request.file_name or request.original_name or title)[:255],
            file_type=None,
            file_size=None,
            storage_provider=request.storage_provider,
            storage_path=request.storage_path,
            storage_key=request.storage_key,
            external_url=request.external_url,
            folder_path=request.folder_path,
            document_date=request.document_date,
            uploaded_by_id=request.uploaded_by_id,
            vehicle_id=request.vehicle_id,
            plate=request.plate,
            archived=False,
        )
        self.db.add(document)
        self.db.flush()
        if source_reference:
            self.link(document.id, source_reference, category=request.document_type)
        self.record_event(document.id, event_action, event_detail, user_id=user_id)
        return document

    def link(
        self,
        document: DocumentReference | int,
        source: SourceReference,
        *,
        category: str | None = None,
    ) -> DocumentAssociation:
        document_id = document.id if isinstance(document, DocumentReference) else document
        association = self.db.scalar(
            select(DocumentAssociation).where(
                DocumentAssociation.document_id == document_id,
                DocumentAssociation.entity_type == source.entity_type,
                DocumentAssociation.entity_id == source.entity_id,
            )
        )
        if association is None:
            association = DocumentAssociation(
                document_id=document_id,
                entity_type=source.entity_type,
                entity_id=source.entity_id,
                category=category,
            )
            self.db.add(association)
        else:
            association.category = category
        return association

    def record_event(
        self,
        document_id: int,
        action: str,
        detail: str | None,
        *,
        user_id: int | None = None,
    ) -> None:
        self.db.add(
            DocumentAuditEvent(
                document_id=document_id,
                action=action,
                old_value=None,
                new_value=detail,
                user_id=user_id,
            )
        )

    @staticmethod
    def summary(document: DocumentRecord) -> DocumentSummary:
        return DocumentSummary(
            reference=DocumentReference(document.id),
            title=document.title or document.original_name,
            status=document.status,
            classification=document.classification,
            document_type=document.document_type,
            storage_provider=document.storage_provider,
            storage_path=document.storage_path,
            file_hash=document.file_hash,
            archived=document.archived,
        )

    @staticmethod
    def verify_local_object(document: DocumentRecord) -> tuple[bool, int | None, str | None]:
        """Read-only object verification. Remote/link providers degrade without network access."""

        if document.storage_provider != "local":
            return False, document.file_size, document.file_hash
        path = Path(document.storage_path)
        if not path.is_file():
            return False, None, None
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        return True, size, digest.hexdigest()

    @staticmethod
    def historical_summary(
        snapshot: dict[str, object] | None, *, can_read_documents: bool
    ) -> DocumentSummary | None:
        if not can_read_documents or not snapshot:
            return None
        try:
            reference = DocumentReference.parse(str(snapshot["reference"]))
            return DocumentSummary(
                reference=reference,
                title=str(snapshot["title"]),
                status=str(snapshot["status"]),
                classification=_optional(snapshot.get("classification")),
                document_type=_optional(snapshot.get("document_type")),
                storage_provider=str(snapshot["storage_provider"]),
                storage_path="",
                file_hash=_optional(snapshot.get("file_hash")),
                archived=bool(snapshot.get("archived", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _optional(value: object) -> str | None:
    return str(value) if value not in (None, "") else None
