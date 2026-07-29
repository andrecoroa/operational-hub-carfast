import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import select

from app.models.documents import Document, DocumentEvent, DocumentWorkflowState
from app.services.document_workflow import (
    classify_invoice_nature,
    confident_destination,
    get_or_create_workflow_state,
    transition_document_workflow,
)


def _document(**overrides) -> Document:
    values = {
        "title": "Documento de teste",
        "document_type": "workshop_supplier_invoice",
        "classification": "invoice",
        "source": "v2_clean_manual",
        "entry_channel": "document_inbox",
        "original_name": "fatura.pdf",
        "file_name": "fatura.pdf",
        "storage_provider": "local",
        "storage_path": "Frota/_POR_ASSOCIAR/fatura.pdf",
        "status": "received",
    }
    values.update(overrides)
    return Document(**values)


def test_workflow_dimensions_change_independently_and_reject_invalid_state(db_session):
    document = _document(document_type="unknown_document", status="pending_triage")
    db_session.add(document)
    db_session.flush()

    state = get_or_create_workflow_state(db_session, document)
    initial = (
        state.ingestion_status,
        state.association_status,
        state.validation_status,
        state.destination_status,
    )
    transition_document_workflow(
        db_session,
        document=document,
        user_id=None,
        reason="Extração pedida",
        extraction_status="queued",
    )

    assert state.extraction_status == "queued"
    assert (
        state.ingestion_status,
        state.association_status,
        state.validation_status,
        state.destination_status,
    ) == initial
    with pytest.raises(ValueError):
        transition_document_workflow(
            db_session,
            document=document,
            user_id=None,
            reason="Inválido",
            validation_status="mixed",
        )


def test_invoice_reclassification_recalculates_projection_and_preserves_history(db_session):
    document = _document()
    db_session.add(document)
    db_session.flush()

    classify_invoice_nature(
        db_session,
        document=document,
        nature="operacional",
        user_id=None,
        suggested_nature="operacional",
        suggestion_confidence=0.94,
        decision_reason="Confirmada pela operação",
    )
    assert document.document_type == "workshop_supplier_invoice"
    assert document.classification == "workshop"
    assert document.status == "classified"

    classify_invoice_nature(
        db_session,
        document=document,
        nature="financeira",
        user_id=None,
        suggested_nature="financeira",
        suggestion_confidence=0.88,
        decision_reason="Entidade financeira confirmada",
    )
    db_session.flush()

    state = db_session.scalar(
        select(DocumentWorkflowState).where(
            DocumentWorkflowState.document_id == document.id
        )
    )
    actions = db_session.scalars(
        select(DocumentEvent.action)
        .where(DocumentEvent.document_id == document.id)
        .order_by(DocumentEvent.id)
    ).all()
    assert state.invoice_nature == "financeira"
    assert state.human_confirmed is True
    assert state.destination_status == "archive"
    assert document.document_type == "finance_supplier_invoice"
    assert document.archived is True
    assert actions == [
        "invoice.nature.classified",
        "invoice.derivatives.recalculated",
        "invoice.nature.reclassified",
        "invoice.derivatives.recalculated",
    ]


@pytest.mark.parametrize(
    ("suggestion", "confidence", "expected"),
    [
        ("invoices", 0.90, "invoices"),
        ("diagnostics", 0.99, "diagnostics"),
        ("archive", 0.89, "triage"),
        ("unknown", 1.0, "triage"),
        (None, None, "triage"),
    ],
)
def test_automatic_destination_requires_known_high_confidence(
    suggestion,
    confidence,
    expected,
):
    assert confident_destination(suggestion, confidence) == expected


def test_alembic_document_workflow_revision_is_the_only_head():
    script = ScriptDirectory.from_config(Config("alembic.ini"))

    assert script.get_heads() == ["9f0a1b2c3d4e"]
