from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.compat import DocumentAssociation, DocumentRecord
from app.documents.contracts import SourceReference
from app.documents.facade import DocumentManagementFacade


def upsert_external_link_document(
    db: Session,
    *,
    source_reference: SourceReference,
    link: str,
    title: str,
    document_type: str,
    classification: str,
    entry_channel: str,
    folder_path: str | None,
    vehicle_id: int | None,
    plate: str | None,
    user_id: int | None,
    existing_document_id: int | None = None,
    source_subject: str | None = None,
) -> int:
    """Compatibility adapter for source modules that currently store link objects."""

    document = db.get(DocumentRecord, existing_document_id) if existing_document_id else None
    if document is None:
        document = db.scalar(
            select(DocumentRecord)
            .join(DocumentAssociation, DocumentAssociation.document_id == DocumentRecord.id)
            .where(
                DocumentRecord.classification == classification,
                DocumentRecord.vehicle_id == vehicle_id,
                DocumentRecord.storage_path == link,
                DocumentAssociation.entity_type == source_reference.entity_type,
                DocumentAssociation.entity_id == source_reference.entity_id,
            )
        )
    created = document is None
    if created:
        document = DocumentRecord(
            title=title[:200],
            original_name=title[:255],
            file_name=title[:255],
            storage_provider="link",
            storage_path=link,
            uploaded_by_id=user_id,
        )
        db.add(document)

    document.title = title[:200]
    document.document_type = document_type
    document.classification = classification
    document.status = "associated"
    document.source = source_reference.module
    document.entry_channel = entry_channel
    document.source_subject = source_subject or title
    document.storage_provider = "link"
    document.storage_path = link
    document.storage_key = link
    document.external_url = link
    document.folder_path = folder_path
    document.vehicle_id = vehicle_id
    if source_reference.module == "workshop":
        document.workshop_process_id = None
    document.plate = plate
    document.uploaded_by_id = document.uploaded_by_id or user_id
    db.flush()

    facade = DocumentManagementFacade(db)
    facade.link(document.id, source_reference, category=document_type)
    if created:
        facade.record_event(
            document.id,
            action="document.associated",
            detail=link,
            user_id=user_id,
        )
    else:
        facade.record_event(
            document.id,
            action=f"document.updated_from_{source_reference.module}",
            detail=link,
            user_id=user_id,
        )
    return document.id
