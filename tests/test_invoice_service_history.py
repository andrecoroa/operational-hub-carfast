import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.documents import Document, VehicleDocumentRecordTag
from app.models.invoice_service_history import (
    InvoiceServiceEvent,
    InvoiceServiceEventRevision,
    InvoiceServiceImportBatch,
)
from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.services.invoice_service_history import (
    InvoiceServiceImportError,
    apply_invoice_service_import,
    decide_invoice_service_event,
    link_event_to_work_order,
    preview_invoice_service_import,
    rollback_invoice_service_batch,
    validate_document_invoice_service_events,
    vehicle_service_history,
)
from app.services.vehicle_document_history import vehicle_document_module_context


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
        source="v2_clean_manual",
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
    assert event.status == "rejected"
    assert event.evidence_text
    assert batch.status == "rolled_back"
    assert db_session.get(Document, document.id) is document
    revisions = list(db_session.scalars(select(InvoiceServiceEventRevision)))
    assert [revision.action for revision in revisions] == ["create", "rollback"]
    assert revisions[-1].reason == "logical_batch_rollback"
    assert list(db_session.scalars(select(VehicleDocumentRecordTag))) == []

    repeated = rollback_invoice_service_batch(db_session, batch.id, actor_id=None)
    db_session.commit()
    assert repeated.id == batch.id
    assert len(list(db_session.scalars(select(InvoiceServiceEventRevision)))) == 2


def test_apply_projects_service_to_document_and_both_views(db_session):
    vehicle, document = _document(db_session, "projection")
    content = (
        "document_id;stable_key;data_servico;km;servico;service_code;eixo;valor;estado;source_line_ids\n"
        f"{document.id};projection-1;2026-01-02;45000;Pastilhas frente;BRAKE.PAD;front;125,50;por validar;{document.id}:1|{document.id}:2\n"
    ).encode()
    preview = preview_invoice_service_import(
        db_session, content, "projection.csv", version="1", source="invoice_service_remediation"
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()

    tag = db_session.scalar(select(VehicleDocumentRecordTag))
    assert (tag.document_id, tag.vehicle_id, tag.category, tag.value) == (
        document.id,
        vehicle.id,
        "pads",
        "front",
    )
    event = db_session.scalar(select(InvoiceServiceEvent))
    assert event.evidence_json["import_metadata"]["source_line_ids"] == [
        f"{document.id}:1",
        f"{document.id}:2",
    ]
    module = vehicle_document_module_context(db_session, vehicle, materialize_sources=False)
    row = next(item for item in module["archive_rows"] if item["id"] == document.id)
    assert row["service_matrix_codes"]["pads"] == ["front"]
    assert row["invoice_service_events"][0]["type"] == "BRAKE.PAD"
    assert row["invoice_service_total"] == event.amount

    rollback_invoice_service_batch(db_session, batch.id, actor_id=None)
    db_session.commit()
    assert list(db_session.scalars(select(VehicleDocumentRecordTag))) == []
    assert event.active is False


def test_event_decision_keeps_document_projection_in_sync(db_session):
    _, document = _document(db_session, "decision-projection")
    preview = preview_invoice_service_import(
        db_session,
        _csv(document.id, "Pastilhas frente"),
        "decision-projection.csv",
        version="1",
        source="audit-export",
    )
    apply_invoice_service_import(db_session, preview, actor_id=None)
    event = db_session.scalar(select(InvoiceServiceEvent))

    decide_invoice_service_event(
        db_session,
        event,
        status="rejected",
        service_code=event.service_code,
        axle=event.axle,
        position=event.position,
        actor_id=None,
        reason="Proposta rejeitada na revisão.",
    )
    db_session.commit()

    assert list(db_session.scalars(select(VehicleDocumentRecordTag))) == []


def test_invoice_validation_decides_all_imported_events_atomically(db_session):
    vehicle, document = _document(db_session, "invoice-validation")
    content = (
        "document_id;stable_key;servico;service_code;estado\n"
        f"{document.id};validation-1;Maintenance;MAINT.PLAN;por validar\n"
        f"{document.id};validation-2;Oil;MAINT.OIL_INTERIM;por validar\n"
    ).encode()
    preview = preview_invoice_service_import(
        db_session, content, "validation.csv", version="1", source="audit-export"
    )
    apply_invoice_service_import(db_session, preview, actor_id=None)
    events = list(db_session.scalars(select(InvoiceServiceEvent).order_by(InvoiceServiceEvent.id)))

    with pytest.raises(InvoiceServiceImportError, match="Todos os serviços"):
        validate_document_invoice_service_events(
            db_session,
            document_id=document.id,
            vehicle_id=vehicle.id,
            decisions=[
                {"event_id": events[0].id, "decision": "accept", "reason": ""},
                {"event_id": events[1].id, "decision": "", "reason": ""},
            ],
            actor_id=None,
        )
    assert all(event.status == "pending_validation" for event in events)

    validate_document_invoice_service_events(
        db_session,
        document_id=document.id,
        vehicle_id=vehicle.id,
        decisions=[
            {"event_id": events[0].id, "decision": "accept", "reason": ""},
            {"event_id": events[1].id, "decision": "reject", "reason": "Duplicado"},
        ],
        actor_id=None,
    )
    db_session.commit()
    assert events[0].status == "validated"
    assert events[0].active is True
    assert events[1].status == "rejected"
    assert events[1].active is False


def test_remediation_dry_run_requires_source_line_link(db_session):
    _, document = _document(db_session, "missing-lines")
    preview = preview_invoice_service_import(
        db_session,
        _csv(document.id),
        "missing-lines.csv",
        version="1",
        source="invoice_service_remediation",
    )
    assert preview["can_apply"] is False
    assert preview["counts"]["error"] == 1
    assert "Linhas de origem em falta" in preview["rows"][0]["errors"][0]


def test_rollback_fails_closed_when_event_changed_after_batch(db_session):
    _, document = _document(db_session, "rollback-stale")
    preview = preview_invoice_service_import(
        db_session, _csv(document.id), "rollback-stale.csv", version="1", source="audit-export"
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()
    event = db_session.scalar(select(InvoiceServiceEvent))
    event.service_label = "Alteração posterior"
    db_session.commit()

    with pytest.raises(InvoiceServiceImportError, match="alterado após o lote"):
        rollback_invoice_service_batch(db_session, batch.id, actor_id=None)
    db_session.rollback()
    assert event.active is True
    assert batch.status == "applied"


def test_idempotent_rollback_fails_closed_on_inconsistent_rolled_back_state(db_session):
    _, document = _document(db_session, "rollback-inconsistent")
    preview = preview_invoice_service_import(
        db_session,
        _csv(document.id),
        "rollback-inconsistent.csv",
        version="1",
        source="audit-export",
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()
    rollback_invoice_service_batch(db_session, batch.id, actor_id=None)
    db_session.commit()
    event = db_session.scalar(select(InvoiceServiceEvent))
    event.active = True
    db_session.commit()

    with pytest.raises(InvoiceServiceImportError, match="Estado do rollback inconsistente"):
        rollback_invoice_service_batch(db_session, batch.id, actor_id=None)


def test_update_rollback_restores_explicit_null_fields(db_session):
    _, document = _document(db_session, "rollback-null")
    initial = preview_invoice_service_import(
        db_session,
        _csv(document.id),
        "rollback-null-initial.csv",
        version="1",
        source="audit-export",
    )
    first_batch = apply_invoice_service_import(db_session, initial, actor_id=None)
    db_session.commit()
    event = db_session.scalar(select(InvoiceServiceEvent))
    event.axle = None
    event.position = None
    event.evidence_json = None
    event.last_batch_id = None
    db_session.commit()

    changed_content = (
        "document_id;stable_key;data_servico;km;servico;eixo;posicao;valor;estado\n"
        f"{document.id};invoice-1-line-1;2026-01-02;45000;Pneu novo;front;left;99,50;por validar\n"
    ).encode()
    changed = preview_invoice_service_import(
        db_session,
        changed_content,
        "rollback-null-update.csv",
        version="2",
        source="audit-export",
    )
    update_batch = apply_invoice_service_import(db_session, changed, actor_id=None)
    db_session.commit()

    rollback_invoice_service_batch(db_session, update_batch.id, actor_id=None)
    db_session.commit()

    assert event.axle is None
    assert event.position is None
    assert event.evidence_json is None
    assert event.last_batch_id is None
    assert first_batch.status == "applied"


def test_rollback_preflights_every_event_before_mutation(db_session):
    _, first_document = _document(db_session, "preflight-a")
    _, second_document = _document(db_session, "preflight-b")
    content = (
        "document_id;stable_key;data_servico;km;servico;service_code;valor;estado\n"
        f"{first_document.id};preflight-1;2026-01-02;45000;Maintenance;MAINT.PLAN;10,00;por validar\n"
        f"{second_document.id};preflight-2;2026-01-03;46000;Oil;MAINT.OIL_INTERIM;20,00;por validar\n"
    ).encode()
    preview = preview_invoice_service_import(
        db_session, content, "preflight.csv", version="1", source="audit-export"
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()
    events = list(
        db_session.scalars(select(InvoiceServiceEvent).order_by(InvoiceServiceEvent.id))
    )
    events[1].service_label = "Alteração posterior"
    db_session.commit()

    with pytest.raises(InvoiceServiceImportError, match="alterado após o lote"):
        rollback_invoice_service_batch(db_session, batch.id, actor_id=None)

    assert events[0].active is True
    assert events[0].status == "pending_validation"
    assert not list(
        db_session.scalars(
            select(InvoiceServiceEventRevision).where(
                InvoiceServiceEventRevision.batch_id == batch.id,
                InvoiceServiceEventRevision.action == "rollback",
            )
        )
    )


def test_rollback_rejects_batch_from_another_vehicle(db_session):
    _, document = _document(db_session, "rollback-scope")
    preview = preview_invoice_service_import(
        db_session, _csv(document.id), "rollback-scope.csv", version="1", source="audit-export"
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    other = Vehicle(plate="OTHER-ROLLBACK")
    db_session.add(other)
    db_session.commit()

    with pytest.raises(InvoiceServiceImportError, match="fora do âmbito"):
        rollback_invoice_service_batch(
            db_session, batch.id, actor_id=None, expected_vehicle_id=other.id
        )
    db_session.rollback()
    assert batch.status == "applied"


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
    assert f"/v2-clean/fleet/{vehicle.id}/documents?main_group=invoices" in response.text
    assert f"open_item=document%3A{document.id}" in response.text
    assert "Mudança adicional de óleo" in response.text
    assert "Tratar na fatura" in response.text
    assert "Decisão do evento" not in response.text
    documents_response = authenticated_client.get(
        f"/v2-clean/fleet/{vehicle.id}/documents?main_group=invoices&open_item=document%3A{document.id}"
    )
    assert documents_response.status_code == 200
    assert "Serviços importados ligados à fatura" in documents_response.text
    assert "MAINT.PLAN" in documents_response.text
    assert "125.50 EUR" in documents_response.text
    assert "Reconciliação:" in documents_response.text

    treatment_response = authenticated_client.get(
        f"/v2-clean/fleet/{vehicle.id}/services/{db_session.scalar(select(InvoiceServiceEvent)).id}",
        follow_redirects=False,
    )
    assert treatment_response.status_code == 200
    assert "apenas para consulta" in treatment_response.text
    assert "Tratar na fatura" in treatment_response.text
    assert "Guardar decisão auditada" not in treatment_response.text


def test_clean_history_route_requires_authentication(client, db_session):
    vehicle, _ = _document(db_session, "6")
    response = client.get(f"/v2-clean/fleet/{vehicle.id}/services", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=")


def test_invoice_route_requires_event_decisions_before_validation(
    authenticated_client, db_session
):
    vehicle, document = _document(db_session, "route-validation")
    preview = preview_invoice_service_import(
        db_session,
        _csv(document.id, "Revisão conforme plano"),
        "route-validation.csv",
        version="1",
        source="audit-export",
    )
    apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()
    event = db_session.scalar(select(InvoiceServiceEvent))

    missing = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/classify-row",
        data={
            "document_id": str(document.id),
            "classification_action": "validate",
            "return_group": "invoices",
            "open_item": f"document:{document.id}",
        },
        follow_redirects=False,
    )
    assert missing.status_code == 303
    assert "error=invoice_service_decision" in missing.headers["location"]
    db_session.expire_all()
    assert db_session.get(Document, document.id).status != "classified"
    assert db_session.get(InvoiceServiceEvent, event.id).status == "pending_validation"

    accepted = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/documents/classify-row",
        data={
            "document_id": str(document.id),
            "classification_action": "validate",
            "return_group": "invoices",
            "open_item": f"document:{document.id}",
            "invoice_service_event_id": str(event.id),
            "invoice_service_event_decision": "accept",
            "invoice_service_event_reason": "",
        },
        follow_redirects=False,
    )
    assert accepted.status_code == 303
    db_session.expire_all()
    assert db_session.get(Document, document.id).status == "classified"
    assert db_session.get(InvoiceServiceEvent, event.id).status == "validated"


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


def test_rollback_route_is_audited_and_idempotent(authenticated_client, db_session):
    vehicle, document = _document(db_session, "rollback-web")
    preview = preview_invoice_service_import(
        db_session, _csv(document.id), "rollback-web.csv", version="1", source="audit-export"
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/services/import/{batch.id}/rollback",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == f"/v2-clean/fleet/{vehicle.id}/services/import"
    db_session.expire_all()
    assert db_session.get(InvoiceServiceImportBatch, batch.id).status == "rolled_back"
    event = db_session.scalar(select(InvoiceServiceEvent))
    assert event.active is False
    assert event.status == "rejected"
    assert db_session.get(Document, document.id) is not None
    assert [
        revision.action
        for revision in db_session.scalars(
            select(InvoiceServiceEventRevision).order_by(InvoiceServiceEventRevision.id)
        )
    ] == ["create", "rollback"]
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.action == "invoice_service_batch.rollback",
            AuditLog.entity_id == str(batch.id),
        )
    ) is not None

    repeated = authenticated_client.post(
        f"/v2-clean/fleet/{vehicle.id}/services/import/{batch.id}/rollback",
        follow_redirects=False,
    )
    assert repeated.status_code == 303
    db_session.expire_all()
    assert len(list(db_session.scalars(select(InvoiceServiceEventRevision)))) == 2


def test_rollback_route_requires_permission(client, db_session):
    vehicle, document = _document(db_session, "rollback-permission")
    preview = preview_invoice_service_import(
        db_session, _csv(document.id), "rollback-permission.csv", version="1", source="audit-export"
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    db_session.commit()

    response = client.post(
        f"/v2-clean/fleet/{vehicle.id}/services/import/{batch.id}/rollback",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")
    assert db_session.get(InvoiceServiceImportBatch, batch.id).status == "applied"


def test_rollback_route_surfaces_scope_failure_without_mutation(
    authenticated_client, db_session
):
    _, document = _document(db_session, "rollback-route-scope")
    preview = preview_invoice_service_import(
        db_session,
        _csv(document.id),
        "rollback-route-scope.csv",
        version="1",
        source="audit-export",
    )
    batch = apply_invoice_service_import(db_session, preview, actor_id=None)
    other = Vehicle(plate="OTHER-ROLLBACK-ROUTE")
    db_session.add(other)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/fleet/{other.id}/services/import/{batch.id}/rollback",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?error=rollback_failed")
    db_session.expire_all()
    assert db_session.get(InvoiceServiceImportBatch, batch.id).status == "applied"
    assert db_session.scalar(select(InvoiceServiceEvent)).active is True

    error_page = authenticated_client.get(response.headers["location"])
    assert error_page.status_code == 200
    assert "Rollback recusado; o lote não foi alterado." in error_page.text
