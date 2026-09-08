import pytest
from sqlalchemy import select

from app.models.documents import Document
from app.models.invoice_service_history import InvoiceServiceEvent, InvoiceServiceEventRevision
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.services.invoice_service_history import (
    InvoiceServiceImportError,
    apply_invoice_service_import,
    link_event_to_work_order,
    preview_invoice_service_import,
    rollback_invoice_service_batch,
    vehicle_service_history,
)


def _document(db_session, suffix="1"):
    vehicle = Vehicle(plate=f"TEST-{suffix}")
    db_session.add(vehicle)
    db_session.flush()
    document = Document(
        title="Fatura teste",
        original_name="invoice.pdf",
        file_name="invoice.pdf",
        storage_path="tests/invoice.pdf",
        vehicle_id=vehicle.id,
        classification="invoice",
        document_type="workshop_supplier_invoice",
        supplier_name="Fornecedor teste",
    )
    db_session.add(document)
    db_session.commit()
    return vehicle, document


def _csv(document_id, service="Óleo motor e filtro de óleo", status="por validar"):
    return (
        "document_id;stable_key;data_servico;km;servico;eixo;posicao;folha_obra;valor;estado\n"
        f"{document_id};invoice-1-line-1;2026-01-02;45000;{service};dianteiro;esquerda;FO-88;125,50;{status}\n"
    ).encode()


def test_dry_run_apply_and_reimport_are_idempotent(db_session):
    vehicle, document = _document(db_session)
    preview = preview_invoice_service_import(
        db_session, _csv(document.id), "lote.csv", version="1", source="audit-export"
    )
    assert preview["can_apply"] is True
    assert preview["counts"]["create"] == 1
    assert preview["rows"][0]["values"]["service_code"] == "MAINT.OIL_INTERIM"
    apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()
    repeated = preview_invoice_service_import(
        db_session, _csv(document.id), "lote.csv", version="1", source="audit-export"
    )
    assert repeated["counts"]["keep"] == 1
    repeated_batch = apply_invoice_service_import(db_session, repeated, actor_id=None)
    assert repeated_batch.file_hash == preview["file_hash"]
    assert len(list(db_session.scalars(select(InvoiceServiceEvent)))) == 1
    assert vehicle_service_history(db_session, vehicle.id)["confirmed"] == []


def test_changed_classification_is_audited_and_validated_conflict_is_explicit(db_session):
    _, document = _document(db_session, "2")
    first = preview_invoice_service_import(
        db_session, _csv(document.id), "one.csv", version="1", source="audit-export"
    )
    apply_invoice_service_import(db_session, first, actor_id=None)
    db_session.commit()
    changed = preview_invoice_service_import(
        db_session,
        _csv(document.id, "Revisão conforme plano", "validado"),
        "two.csv",
        version="2",
        source="audit-export",
    )
    assert changed["counts"]["update"] == 1
    apply_invoice_service_import(db_session, changed, actor_id=None)
    db_session.commit()
    event = db_session.scalar(select(InvoiceServiceEvent))
    assert event.service_code == "MAINT.PLAN"
    conflict = preview_invoice_service_import(
        db_session,
        _csv(document.id, "Pneu novo", "validado"),
        "three.csv",
        version="3",
        source="audit-export",
    )
    assert conflict["counts"]["conflict"] == 1
    with pytest.raises(InvoiceServiceImportError):
        apply_invoice_service_import(db_session, conflict, actor_id=None)
    apply_invoice_service_import(db_session, conflict, actor_id=None, allow_validated_updates=True)
    db_session.commit()
    assert len(list(db_session.scalars(select(InvoiceServiceEventRevision)))) == 3


def test_logical_rollback_preserves_event_and_evidence(db_session):
    _, document = _document(db_session, "3")
    preview = preview_invoice_service_import(
        db_session, _csv(document.id), "rollback.csv", version="1", source="audit-export"
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()
    rollback_invoice_service_batch(db_session, batch.id, actor_id=None)
    db_session.commit()
    event = db_session.scalar(select(InvoiceServiceEvent))
    assert event.active is False
    assert event.evidence_text
    assert batch.status == "rolled_back"


def test_work_order_link_rejects_other_vehicle(db_session):
    vehicle, document = _document(db_session, "4")
    preview = preview_invoice_service_import(
        db_session, _csv(document.id), "fo.csv", version="1", source="audit-export"
    )
    apply_invoice_service_import(db_session, preview, actor_id=None)
    other = Vehicle(plate="OTHER-4")
    db_session.add(other)
    db_session.flush()
    process = WorkshopProcess(vehicle_id=other.id, title="FO", status="opening")
    db_session.add(process)
    db_session.flush()
    event = db_session.scalar(
        select(InvoiceServiceEvent).where(InvoiceServiceEvent.vehicle_id == vehicle.id)
    )
    with pytest.raises(InvoiceServiceImportError):
        link_event_to_work_order(db_session, event, process, confidence=None, actor_id=None)


def test_clean_history_route_shows_confirmed_and_pending(authenticated_client, db_session):
    vehicle, document = _document(db_session, "5")
    preview = preview_invoice_service_import(
        db_session,
        _csv(document.id, "Revisão conforme plano", "validado"),
        "web.csv",
        version="1",
        source="audit-export",
    )
    apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()
    response = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/services")
    assert response.status_code == 200
    assert "Histórico de serviços" in response.text
    assert "Primeiro serviço confirmado" in response.text
    assert "MAINT.PLAN" in response.text
    assert f"/v2-clean/documents/{document.id}" in response.text


def test_clean_history_route_requires_authentication(client, db_session):
    vehicle, _ = _document(db_session, "6")
    response = client.get(f"/v2-clean/fleet/{vehicle.id}/services", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_import_vehicle_scope_rejects_document_from_another_vehicle(db_session):
    vehicle, document = _document(db_session, "7")
    other = Vehicle(plate="OTHER-7")
    db_session.add(other)
    db_session.commit()
    preview = preview_invoice_service_import(
        db_session,
        _csv(document.id),
        "scope.csv",
        version="1",
        source="audit-export",
        allowed_vehicle_id=other.id,
    )
    assert preview["can_apply"] is False
    assert preview["counts"]["error"] == 1
    assert "fora do âmbito" in preview["rows"][0]["errors"][0]


def test_import_and_print_surfaces_render(authenticated_client, db_session):
    vehicle, _ = _document(db_session, "8")
    import_page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/services/import")
    print_page = authenticated_client.get(f"/v2-clean/fleet/{vehicle.id}/services?print_view=1")
    assert import_page.status_code == 200
    assert "O dry-run é obrigatório" in import_page.text
    assert "@media print" in open("app/static/css/app.css", encoding="utf-8").read()
    assert "window.print()" in print_page.text
