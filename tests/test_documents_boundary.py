from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import func, select

from app.api.routes.integrations import EmailIntakePayload, create_document
from app.core.config import settings
from app.documents import (
    DOCUMENTS_MANIFEST,
    DocumentManagementFacade,
    DocumentRecord,
    DocumentReference,
    LinkIngestionRequest,
    SourceReference,
    decide_document_permission,
)
from app.models import Base
from app.models.documents import Document as LegacyDocument
from app.models.integrations import EmailIntake
from app.platform.composer import CompositionResult, compose
from app.platform.manifest import ModuleState
from app.platform.registry import ManifestRegistry


def test_document_reference_is_stable_and_versioned() -> None:
    reference = DocumentReference(17)
    assert reference.value == "document:v1:17"
    assert DocumentReference.parse(reference.value) == reference


def test_compatibility_storage_keeps_same_mapper_and_table() -> None:
    assert DocumentRecord is LegacyDocument
    assert DocumentRecord.__tablename__ == "documents"


def test_ingestion_and_link_contract_preserve_metadata_and_audit(db_session) -> None:
    request = LinkIngestionRequest(
        title="Documento sintético",
        storage_path="https://sandbox.invalid/document/1",
        storage_provider="link",
        source="service_desk",
        entry_channel="email",
        document_type="general",
        classification="general",
    )
    source = SourceReference("service_desk", "email_intake", "synthetic-1", "Email sintético")
    document = DocumentManagementFacade(db_session).ingest_link(
        request, source_reference=source, event_action="created_from_test", event_detail="synthetic"
    )
    db_session.commit()
    assert db_session.get(LegacyDocument, document.id) is document
    assert (
        db_session.scalar(select(func.count()).select_from(Base.metadata.tables["document_links"]))
        == 1
    )
    assert (
        db_session.scalar(select(func.count()).select_from(Base.metadata.tables["document_events"]))
        == 1
    )


def test_local_object_hash_size_and_accessibility_are_reconciled(db_session, tmp_path) -> None:
    payload = b"synthetic document bytes\n"
    object_path = tmp_path / "document.bin"
    object_path.write_bytes(payload)
    document = DocumentRecord(
        title="Objeto sintético",
        original_name="document.bin",
        file_name="document.bin",
        storage_provider="local",
        storage_path=str(object_path),
        file_size=len(payload),
        file_hash=hashlib.sha256(payload).hexdigest(),
    )
    db_session.add(document)
    db_session.commit()
    accessible, size, digest = DocumentManagementFacade.verify_local_object(document)
    assert accessible is True
    assert size == document.file_size
    assert digest == document.file_hash


def test_historical_snapshot_is_permission_safe(db_session) -> None:
    document = DocumentRecord(
        title="Histórico sintético",
        original_name="history.txt",
        file_name="history.txt",
        storage_provider="link",
        storage_path="https://sandbox.invalid/history",
    )
    db_session.add(document)
    db_session.commit()
    facade = DocumentManagementFacade(db_session)
    snapshot = facade.summary(document).snapshot()
    assert facade.historical_summary(snapshot, can_read_documents=False) is None
    restored = facade.historical_summary(snapshot, can_read_documents=True)
    assert restored is not None
    assert restored.reference.id == document.id
    assert restored.storage_path == ""


def test_documents_manifest_is_standalone_and_composer_remains_gated() -> None:
    DOCUMENTS_MANIFEST.validate()
    registry = ManifestRegistry([DOCUMENTS_MANIFEST])
    legacy = CompositionResult((), (), (), (), source="legacy")
    states = {"documents": ModuleState.ACTIVE}
    permissions = {"documents.records.read"}
    assert (
        compose(
            legacy=legacy, registry=registry, module_states=states, permission_codes=permissions
        )
        is legacy
    )
    active = compose(
        legacy=legacy,
        registry=registry,
        module_states=states,
        permission_codes=permissions,
        enabled=True,
    )
    assert [item.code for item in active.navigation] == ["documents.records"]
    assert DOCUMENTS_MANIFEST.dependencies == ("core",)


def test_canonical_permissions_exactly_map_legacy_access() -> None:
    assert decide_document_permission("documents.records.read", {"documents.read"}).allowed
    assert decide_document_permission("documents.records.update", {"documents.write"}).allowed
    assert not decide_document_permission("documents.records.update", {"documents.read"}).allowed
    assert not decide_document_permission("documents.records.unknown", {"admin.manage"}).allowed


def test_all_document_foreign_keys_remain_reconcilable() -> None:
    targets: set[tuple[str, str]] = set()
    for table in Base.metadata.tables.values():
        for column in table.columns:
            for foreign_key in column.foreign_keys:
                if foreign_key.target_fullname == "documents.id":
                    targets.add((table.name, column.name))
    assert len(targets) >= 12
    assert ("document_links", "document_id") in targets
    assert ("task_documents", "document_id") in targets
    assert ("stock_invoice_imports", "document_id") in targets


def test_priority_writers_use_document_application_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    integrations = (root / "app/api/routes/integrations.py").read_text(encoding="utf-8")
    workshop = (root / "app/api/routes/workshop.py").read_text(encoding="utf-8")
    assert "DocumentManagementFacade(db).ingest_link" in integrations
    assert "upsert_external_link_document(" in workshop


def test_email_adapter_ingests_through_document_contract(db_session) -> None:
    intake = EmailIntake(source_mailbox="sandbox@example.invalid", subject="Fatura sintética")
    db_session.add(intake)
    db_session.flush()
    payload = EmailIntakePayload(
        source_mailbox="sandbox@example.invalid",
        subject="Fatura sintética",
        attachments_url="https://sandbox.invalid/attachments/1",
    )
    document = create_document(db_session, intake, payload, "finance")
    db_session.commit()

    assert document.storage_provider == "sharepoint"
    assert document.classification == "finance"
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(Base.metadata.tables["document_links"])
            .where(Base.metadata.tables["document_links"].c.entity_type == "email_intake")
        )
        == 1
    )


def test_touched_document_surfaces_use_gated_visual_primitives(
    authenticated_client, db_session, monkeypatch
) -> None:
    document = DocumentRecord(
        title="Documento visual sintético",
        original_name="visual.pdf",
        file_name="visual.pdf",
        storage_provider="link",
        storage_path="https://sandbox.invalid/visual.pdf",
    )
    db_session.add(document)
    db_session.commit()
    monkeypatch.setattr(settings, "visual_foundation_enabled", True)

    center = authenticated_client.get("/v2-clean/documentation")
    detail = authenticated_client.get(f"/v2-clean/documents/{document.id}")
    assert center.status_code == detail.status_code == 200
    assert "ui-table-container" in center.text
    assert "ui-page-shell" in detail.text
