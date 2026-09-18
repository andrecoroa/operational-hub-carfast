from sqlalchemy import select

import app.main as app_main
from app.web import router as web_router
from app.models.vehicles import Vehicle
from app.models.workshop_phased import (
    WorkshopMaterialNeed, WorkshopPhasedProcess, WorkshopPhasedProcessPhase,
    WorkshopPhasedTechnicalReport,
)
from app.web.router import (
    clean_workshop_find_vehicle,
    clean_workshop_v2_authorization_valid,
    clean_workshop_v2_proposal,
)


def test_entry_permission_only_opens_own_new_entry(authenticated_client, db_session, monkeypatch):
    granted = {"workshop.entry.create"}
    permission_codes = lambda _db, _user: set(granted)
    monkeypatch.setattr(app_main, "get_user_permission_codes", permission_codes)
    monkeypatch.setattr(web_router, "get_user_permission_codes", permission_codes)
    home = authenticated_client.get("/v2-clean", follow_redirects=False)
    assert home.status_code == 303
    assert home.headers["location"] == "/v2-clean/workshop-entry?flow=2"
    entry = authenticated_client.get("/v2-clean/workshop-entry?flow=2")
    assert entry.status_code == 200
    assert "Fotografias da entrada" in entry.text
    assert authenticated_client.get(
        "/v2-clean/workshop-entry/vehicle-search?q=SV",
        follow_redirects=False,
    ).status_code == 200
    dashboard = authenticated_client.get("/v2-clean/workshop", follow_redirects=False)
    assert dashboard.status_code == 403
    created = authenticated_client.post(
        "/v2-clean/workshop-entry", data={"workshop_flow_version": "2",
        "plate": "SV-26-RO", "action": "save"}, follow_redirects=False,
    )
    assert created.status_code == 303
    process = db_session.scalar(select(WorkshopPhasedProcess).where(
        WorkshopPhasedProcess.plate_snapshot == "SV-26-RO"
    ))
    assert process is not None
    assert authenticated_client.get(f"/v2-clean/workshop-entry?process_id={process.id}").status_code == 200
    assert authenticated_client.get(
        f"/v2-clean/workshop/validacao?process_id={process.id}", follow_redirects=False,
    ).status_code == 403
    assert authenticated_client.post(
        "/v2-clean/workshop/validacao/save",
        data={"process_id": process.id, "action": "save"}, follow_redirects=False,
    ).status_code == 403
    assert authenticated_client.get(
        f"/v2-clean/workshop/{process.id}/print/process-dossier", follow_redirects=False,
    ).status_code == 403
    legacy = authenticated_client.post(
        "/v2-clean/workshop-entry", data={"plate": "SV-26-OLD", "action": "save"},
        follow_redirects=False,
    )
    assert legacy.status_code == 403


def test_entry_vehicle_suggestions_use_clean_route(authenticated_client, db_session):
    vehicle = Vehicle(
        plate="RT-89-AB",
        vin="VINRT89AB123456789",
        brand="RENAULT",
        model="CLIO",
        active=True,
    )
    db_session.add(vehicle)
    db_session.commit()

    page = authenticated_client.get("/v2-clean/workshop-entry?flow=2")
    assert page.status_code == 200
    assert "/v2-clean/workshop-entry/vehicle-search" in page.text
    assert "/task-board/vehicle-search" not in page.text

    suggestions = authenticated_client.get(
        "/v2-clean/workshop-entry/vehicle-search?q=RT89AB",
        follow_redirects=False,
    )
    assert suggestions.status_code == 200
    assert suggestions.json()["items"][0]["plate"] == vehicle.plate
    assert set(suggestions.json()["items"][0]) == {"plate", "label"}
    assert authenticated_client.get(
        "/v2-clean/workshop-entry/vehicle-search?q=R"
    ).json() == {"items": []}


def test_unlinked_entry_dossier_shows_plate_without_fake_vehicle(authenticated_client, db_session):
    response = authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={"workshop_flow_version": "2", "plate": "ZZ-49-XF", "action": "save"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    process = db_session.scalar(
        select(WorkshopPhasedProcess).where(WorkshopPhasedProcess.plate_snapshot == "ZZ-49-XF")
    )
    assert process is not None
    assert process.vehicle_id is None

    dossier = authenticated_client.get(
        f"/v2-clean/workshop/{process.id}/print/process-dossier"
    )
    assert dossier.status_code == 200
    assert "ZZ-49-XF" in dossier.text
    assert "Viatura não associada" in dossier.text
    assert "Selecionar viatura" not in dossier.text


def test_unlinked_draft_can_link_on_explicit_save_after_vehicle_exists(authenticated_client, db_session):
    created = authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={"workshop_flow_version": "2", "plate": "RT89AB", "action": "save"},
        follow_redirects=False,
    )
    assert created.status_code == 303
    process = db_session.scalar(
        select(WorkshopPhasedProcess).where(WorkshopPhasedProcess.plate_snapshot == "RT89AB")
    )
    assert process is not None
    assert process.vehicle_id is None

    vehicle = Vehicle(plate="RT-89-AB", active=True)
    db_session.add(vehicle)
    db_session.commit()
    saved = authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={"process_id": str(process.id), "workshop_flow_version": "2", "plate": "RT89AB", "action": "save"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    db_session.refresh(process)
    assert process.vehicle_id == vehicle.id
    assert process.plate_snapshot == vehicle.plate


def test_normalized_plate_does_not_guess_between_two_vehicles(db_session):
    db_session.add_all([
        Vehicle(plate="RT-89-AB", active=True),
        Vehicle(plate="RT89-AB", active=True),
    ])
    db_session.commit()
    assert clean_workshop_find_vehicle(db_session, plate="R-T89-AB") is None


def test_v2_entry_can_advance_with_documented_missing_photos(authenticated_client, db_session):
    response = authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={
            "workshop_flow_version": "2", "plate": "SV-26-EN", "action": "advance",
            "entry_km": "12500", "entry_reasons": "Avaria",
            "breakdown_description": "Ruído ao travar", "reported_by": "Operador",
            "reported_by_detail": "Técnico de teste",
            **{f"absence_reason_{slot}": "Viatura indisponível para fotografia de teste"
               for slot in ("dashboard", "front", "rear", "left", "right")},
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "/v2-clean/workshop/validacao?process_id=" in response.headers["location"]
    process = db_session.scalar(select(WorkshopPhasedProcess).where(
        WorkshopPhasedProcess.plate_snapshot == "SV-26-EN"
    ))
    assert process is not None
    assert process.metadata_json["workshop_flow_version"] == 2
    assert process.current_phase_code == "validacao"


def test_v2_entry_conditional_photo_reasons_and_compact_physical_checks(authenticated_client, db_session):
    page = authenticated_client.get("/v2-clean/workshop-entry?flow=2")
    assert page.status_code == 200
    for slot in ("dashboard", "front", "rear", "left", "right"):
        assert f'data-photo-slot="{slot}"' in page.text
        assert f'name="upload_reason_{slot}"' in page.text
        assert f'name="absence_reason_{slot}"' in page.text
    assert 'data-selected-reason hidden' in page.text
    assert 'data-absence-reason hidden' in page.text
    assert 'data-no-photo' in page.text
    assert '<select name="visible_damage">' in page.text
    assert '<select name="damage_matches_rentway">' in page.text
    assert '<option value="not_checked" selected>Por verificar</option>' in page.text

    saved = authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={
            "workshop_flow_version": "2", "plate": "SV-26-UI", "action": "save",
            "visible_damage": "yes", "damage_matches_rentway": "no",
            "dua_copy": "not_applicable", "physical_check_note": "Risco no para-choques",
            "absence_reason_front": "Fotografia impedida pela posição da viatura",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    process = db_session.scalar(select(WorkshopPhasedProcess).where(
        WorkshopPhasedProcess.plate_snapshot == "SV-26-UI"
    ))
    entry = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "entrada",
    ))
    assert entry.data_json["physical_checks"]["visible_damage"] == "yes"
    assert entry.data_json["physical_checks"]["damage_matches_rentway"] == "no"
    assert entry.data_json["physical_checks"]["dua_copy"] == "not_applicable"
    assert entry.data_json["physical_check_note"] == "Risco no para-choques"
    assert entry.data_json["photo_absence_reasons"]["front"] == "Fotografia impedida pela posição da viatura"
    revisited = authenticated_client.get(f"/v2-clean/workshop-entry?process_id={process.id}")
    assert '<select name="visible_damage">' in revisited.text
    assert '<option value="yes" selected>Sim</option>' in revisited.text
    assert '<option value="no" selected>Não</option>' in revisited.text


def test_v2_analysis_late_diagnostic_needs_identified_authorization(authenticated_client, db_session):
    authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={
            "workshop_flow_version": "2", "plate": "SV-26-LT", "action": "advance",
            "entry_km": "20000", "entry_reasons": "Avaria",
            "breakdown_description": "Falha intermitente", "reported_by": "Operador",
            "reported_by_detail": "Técnico de teste",
            **{f"absence_reason_{slot}": "Fotografia ainda não disponível no teste"
               for slot in ("dashboard", "front", "rear", "left", "right")},
        }, follow_redirects=False,
    )
    process = db_session.scalar(select(WorkshopPhasedProcess).where(
        WorkshopPhasedProcess.plate_snapshot == "SV-26-LT"
    ))
    payload = {
        "process_id": process.id, "action": "advance",
        "analysis_template_code": process.template_snapshot_json["template_code"],
        "analysis_decision": "Reparar", "problem_conclusion": "Falha confirmada",
        "services_proposed": "Substituir sensor", "diagnostic_mode": "late_authorized",
        "inspection_needed": "no", "quote_needed": "no",
    }
    denied = authenticated_client.post(
        "/v2-clean/workshop/validacao/save", data=payload, follow_redirects=False,
    )
    assert "error=diagnostic_late_authorization_required" in denied.headers["location"]
    advanced = authenticated_client.post(
        "/v2-clean/workshop/validacao/save",
        data={**payload, "diagnostic_late_authorization_confirmed": "yes"},
        follow_redirects=False,
    )
    assert advanced.status_code == 303
    assert "/v2-clean/workshop/reparacao" in advanced.headers["location"]
    db_session.expire_all()
    diagnostic = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "diagnostico",
    ))
    assert diagnostic.status == "pending_documents"
    assert process.metadata_json["diagnostic_mode"] == "late_authorized"


def _v2_repair_process(db_session):
    vehicle = Vehicle(plate="SV-26-AA", active=True, lifecycle_status="active")
    db_session.add(vehicle)
    db_session.flush()
    process = WorkshopPhasedProcess(
        public_reference="OF-SIMPLIFIED-TEST",
        process_type="workshop",
        title="Reparação simplificada",
        creation_mode="synthetic_test",
        status="active",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="reparacao",
        priority="normal",
        origin="v2_clean",
        metadata_json={"workshop_flow_version": 2, "diagnostic_mode": "late_authorized"},
    )
    db_session.add(process)
    db_session.flush()
    db_session.add_all([
        WorkshopPhasedProcessPhase(
            process_id=process.id, phase_code="entrada", name="Entrada", status="completed",
            sort_order=1, data_json={"entry_km": "12345", "entry_reasons": ["Avaria"]},
        ),
        WorkshopPhasedProcessPhase(
            process_id=process.id, phase_code="validacao", name="Análise", status="completed",
            sort_order=2, data_json={
                "form_snapshot": {"problem_conclusion": "Travagem", "services_proposed": "Trocar pastilhas",
                                  "quote_needed": "no", "diagnostic_mode": "late_authorized"},
                "proposed_materials": [{"reference": "PAD-001", "description": "Pastilhas",
                                        "quantity": "1", "status": "proposed"}],
            },
        ),
        WorkshopPhasedProcessPhase(
            process_id=process.id, phase_code="reparacao", name="Execução", status="in_progress",
            sort_order=3, data_json={"form_snapshot": {}},
        ),
    ])
    db_session.commit()
    return process


def test_legacy_simplified_save_preserves_unshown_advanced_fields(authenticated_client, db_session):
    vehicle = Vehicle(plate="SV-26-LEG", active=True, lifecycle_status="active")
    db_session.add(vehicle)
    db_session.flush()
    process = WorkshopPhasedProcess(
        public_reference="OF-LEGACY-PRESERVE", process_type="workshop",
        title="Reparação antiga", creation_mode="synthetic_test", status="active",
        vehicle_id=vehicle.id, plate_snapshot=vehicle.plate,
        current_phase_code="reparacao", priority="normal", origin="v2_clean",
        metadata_json={},
    )
    db_session.add(process)
    db_session.flush()
    repair = WorkshopPhasedProcessPhase(
        process_id=process.id, phase_code="reparacao", name="Reparação",
        status="in_progress", sort_order=6,
        data_json={
            "legacy_meta": "Registo anterior conservado",
            "form_snapshot": {
                "repair_summary": "Texto anterior",
                "repair_done": "yes",
                "repair_deviation_reason": "Desvio documentado anteriormente",
                "repair_material_1_reference": "PECA-ANTIGA-001",
                "repair_hidden_markup": "<script>alert(1)</script>",
            },
        },
    )
    db_session.add(repair)
    db_session.commit()

    saved = authenticated_client.post(
        "/v2-clean/workshop/reparacao/save",
        data={"process_id": process.id, "action": "save",
              "repair_summary": "Texto novo", "repair_execution_status": "Em curso"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    db_session.expire_all()
    snapshot = repair.data_json["form_snapshot"]
    assert snapshot["repair_summary"] == "Texto novo"
    assert snapshot["repair_deviation_reason"] == "Desvio documentado anteriormente"
    assert snapshot["repair_material_1_reference"] == "PECA-ANTIGA-001"
    assert repair.data_json["legacy_meta"] == "Registo anterior conservado"
    page = authenticated_client.get(f"/v2-clean/workshop/reparacao?process_id={process.id}")
    assert page.status_code == 200
    readonly = page.text.split('class="clean-panel clean-card-wide clean-workshop-legacy-records"', 1)[1]
    readonly = readonly.split("</details>", 1)[0]
    assert "Dados guardados desta fase" in readonly
    assert "Desvio documentado anteriormente" in readonly
    assert "PECA-ANTIGA-001" in readonly
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in readonly
    assert "<script>" not in readonly
    assert "<input" not in readonly and "<textarea" not in readonly
    cleared = authenticated_client.post(
        "/v2-clean/workshop/reparacao/save",
        data={"process_id": process.id, "action": "save",
              "form_state_json": '{"repair_summary":"","repair_done":""}'},
        follow_redirects=False,
    )
    assert cleared.status_code == 303
    db_session.expire_all()
    assert repair.data_json["form_snapshot"]["repair_summary"] == ""
    assert repair.data_json["form_snapshot"]["repair_done"] == ""
    assert repair.data_json["form_snapshot"]["repair_deviation_reason"] == (
        "Desvio documentado anteriormente"
    )


def test_v2_repair_requires_current_authorization_and_invalidates_on_revision(authenticated_client, db_session):
    process = _v2_repair_process(db_session)
    page = authenticated_client.get(f"/v2-clean/workshop/reparacao?process_id={process.id}")
    assert page.status_code == 200
    assert "Trabalho a autorizar" in page.text
    assert "Execução bloqueada" in page.text
    assert "Imprimir processo" in page.text
    dossier = authenticated_client.get(f"/v2-clean/workshop/{process.id}/print/process-dossier")
    assert dossier.status_code == 200
    assert "Dossiê do processo de Oficina" in dossier.text
    assert "PAD-001" in dossier.text

    blocked = authenticated_client.post(
        "/v2-clean/workshop/reparacao/save",
        data={"process_id": process.id, "action": "advance", "repair_execution_status": "Concluída",
              "repair_summary": "Troca efetuada"}, follow_redirects=False,
    )
    assert "error=authorization_required" in blocked.headers["location"]

    requested = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/repair-authorization",
        data={"action": "request"}, follow_redirects=False,
    )
    assert requested.status_code == 303
    approved = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/repair-authorization",
        data={"action": "approve", "approval_reference": "AUT-123"}, follow_redirects=False,
    )
    assert approved.status_code == 303
    db_session.expire_all()
    assert clean_workshop_v2_authorization_valid(process, clean_workshop_v2_proposal(db_session, process))

    revised = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/repair-proposal",
        data={"services": "Trocar pastilhas\nTrocar discos", "material_reference": "PAD-001",
              "material_description": "Pastilhas", "material_quantity": "1"}, follow_redirects=False,
    )
    assert revised.status_code == 303
    db_session.expire_all()
    assert not clean_workshop_v2_authorization_valid(process, clean_workshop_v2_proposal(db_session, process))
    assert process.metadata_json["repair_authorization"]["status"] == "stale"


def test_v2_quote_can_be_approved_after_analysis_and_requires_new_request(authenticated_client, db_session):
    process = _v2_repair_process(db_session)
    analysis = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "validacao",
    ))
    data = dict(analysis.data_json)
    snapshot = dict(data["form_snapshot"])
    snapshot.update({"quote_needed": "yes", "quote_status": "pending"})
    data["form_snapshot"] = snapshot
    analysis.data_json = data
    db_session.commit()
    url = f"/v2-clean/workshop/{process.id}/repair-authorization"
    authenticated_client.post(url, data={"action": "request"}, follow_redirects=False)
    denied = authenticated_client.post(
        url, data={"action": "approve", "approval_reference": "AUT-Q-1"},
        follow_redirects=False,
    )
    assert "error=quote_pending" in denied.headers["location"]
    updated = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/quote-update",
        data={"quote_status": "approved", "quote_reference": "ORC-001", "quote_amount": "125,00"},
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.expire_all()
    assert process.metadata_json["repair_authorization"]["status"] == "stale"
    authenticated_client.post(url, data={"action": "request"}, follow_redirects=False)
    approved = authenticated_client.post(
        url, data={"action": "approve", "approval_reference": "AUT-Q-2"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    db_session.expire_all()
    assert clean_workshop_v2_authorization_valid(process, clean_workshop_v2_proposal(db_session, process))


def test_v2_stock_request_is_allowed_but_direct_usage_is_not(authenticated_client, db_session):
    process = _v2_repair_process(db_session)
    url = f"/v2-clean/workshop/{process.id}/material-needs"
    direct = authenticated_client.post(url, data={"request_mode": "direct_usage",
        "material_description": "Pastilhas", "material_code": "PAD-001", "requested_quantity": "1"},
        follow_redirects=False)
    assert "error=material_request_only" in direct.headers["location"]
    request = authenticated_client.post(url, data={"request_mode": "request",
        "material_description": "Pastilhas", "material_code": "PAD-001", "requested_quantity": "1"},
        follow_redirects=False)
    assert request.status_code == 303
    db_session.expire_all()
    needs = db_session.scalars(select(WorkshopMaterialNeed).where(WorkshopMaterialNeed.process_id == process.id)).all()
    assert len(needs) == 1
    assert needs[0].stock_status == "requested"
    order = authenticated_client.get(f"/v2-clean/workshop/{process.id}/print/repair-order")
    assert order.status_code == 200
    assert "Rascunho - autorização pendente" in order.text
    assert "PAD-001" in order.text
    authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/repair-authorization",
        data={"action": "request"}, follow_redirects=False,
    )
    approved = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/repair-authorization",
        data={"action": "approve", "approval_reference": "AUT-STOCK-1"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    db_session.expire_all()
    needs[0].stock_status = "delivered"
    db_session.commit()
    assert clean_workshop_v2_authorization_valid(process, clean_workshop_v2_proposal(db_session, process))
    applied = authenticated_client.post(
        f"/v2-clean/workshop/material-needs/{needs[0].id}/confirm-applied",
        follow_redirects=False,
    )
    assert applied.status_code == 303
    applied_order = authenticated_client.get(f"/v2-clean/workshop/{process.id}/print/repair-order")
    assert "Aplicado" in applied_order.text
    assert applied_order.text.count("PAD-001") == 1


def test_v2_external_repair_is_visible_in_external_dashboard(authenticated_client, db_session):
    process = _v2_repair_process(db_session)
    authorization_url = f"/v2-clean/workshop/{process.id}/repair-authorization"
    authenticated_client.post(authorization_url, data={"action": "request"}, follow_redirects=False)
    approved = authenticated_client.post(
        authorization_url,
        data={"action": "approve", "approval_reference": "AUT-EXT-1"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    saved = authenticated_client.post(
        "/v2-clean/workshop/reparacao/save",
        data={
            "process_id": process.id, "action": "save",
            "repair_summary": "Reparação externa em curso",
            "repair_external": "yes", "repair_external_partner": "Oficina Parceira",
            "repair_external_reference": "EXT-001", "repair_external_status": "Enviada",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    db_session.expire_all()
    repair = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "reparacao",
    ))
    assert repair.data_json["form_snapshot"]["repair_external"] == "yes"
    external = authenticated_client.get("/v2-clean/workshop?location=external&q=SV-26-AA")
    assert external.status_code == 200
    assert "<strong>SV-26-AA</strong>" in external.text
    assert "Oficina Parceira" in external.text
    internal = authenticated_client.get("/v2-clean/workshop?location=internal&q=SV-26-AA")
    assert "<strong>SV-26-AA</strong>" not in internal.text


def test_v2_external_repair_quote_followup_print_and_close(authenticated_client, db_session):
    process = _v2_repair_process(db_session)
    analysis = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "validacao",
    ))
    analysis_data = dict(analysis.data_json)
    analysis_data["form_snapshot"] = {
        **analysis_data["form_snapshot"], "quote_needed": "yes", "quote_status": "requested",
    }
    analysis.data_json = analysis_data
    db_session.commit()

    authorization_url = f"/v2-clean/workshop/{process.id}/repair-authorization"
    authenticated_client.post(authorization_url, data={"action": "request"}, follow_redirects=False)
    premature = authenticated_client.post(
        authorization_url, data={"action": "approve", "approval_reference": "AUT-EXT-2"},
        follow_redirects=False,
    )
    assert "error=quote_pending" in premature.headers["location"]
    quote = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/quote-update",
        data={"quote_status": "approved", "quote_reference": "ORC-EXT-1", "quote_amount": "225,00"},
        files={"quote_file": (
            "orcamento-teste.pdf", b"%PDF-1.4\nsynthetic test\n%%EOF", "application/pdf",
        )},
        follow_redirects=False,
    )
    assert quote.status_code == 303
    db_session.expire_all()
    assert analysis.data_json["form_snapshot"]["quote_reference"] == "ORC-EXT-1"
    assert any(item["field"] == "quote_file" for item in analysis.data_json["uploads"])

    authenticated_client.post(authorization_url, data={"action": "request"}, follow_redirects=False)
    approved = authenticated_client.post(
        authorization_url, data={"action": "approve", "approval_reference": "AUT-EXT-2"},
        follow_redirects=False,
    )
    assert approved.status_code == 303
    execution = {
        "process_id": process.id, "repair_summary": "Pastilhas substituídas na oficina parceira",
        "repair_external": "yes", "repair_external_partner": "Oficina Parceira",
        "repair_external_reference": "EXT-002", "repair_external_status": "Em execução",
        "repair_external_eta": "2026-10-02", "repair_execution_status": "Em curso",
    }
    saved = authenticated_client.post(
        "/v2-clean/workshop/reparacao/save", data={**execution, "action": "save"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    db_session.expire_all()
    repair = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "reparacao",
    ))
    assert repair.data_json["form_snapshot"]["repair_external_status"] == "Em execução"
    dossier = authenticated_client.get(f"/v2-clean/workshop/{process.id}/print/process-dossier")
    assert dossier.status_code == 200
    assert "Oficina Parceira" in dossier.text
    assert "ORC-EXT-1" in dossier.text
    assert "orcamento-teste.pdf" in dossier.text

    advanced = authenticated_client.post(
        "/v2-clean/workshop/reparacao/save",
        data={**execution, "action": "advance", "repair_execution_status": "Concluída",
              "repair_external_status": "Devolvida"},
        follow_redirects=False,
    )
    assert advanced.headers["location"] == f"/v2-clean/workshop/fecho?process_id={process.id}"
    closed = authenticated_client.post(
        "/v2-clean/workshop/fecho/save",
        data={"process_id": process.id, "action": "close_process",
              "closure_final_summary": "Viatura entregue após reparação externa",
              "closure_vehicle_validated": "yes", "closure_history_updated": "yes",
              "closure_fleet_state_defined": "yes", "closure_min_docs_attached": "yes"},
        follow_redirects=False,
    )
    assert closed.status_code == 303
    db_session.expire_all()
    assert process.status == "closed"
    final_report = authenticated_client.get(f"/v2-clean/workshop/{process.id}/print/final-report")
    assert final_report.status_code == 200
    assert "Viatura entregue após reparação externa" in final_report.text
    assert "Oficina Parceira" in final_report.text
    assert "EXT-002" in final_report.text
    assert "ORC-EXT-1" in final_report.text
    closed_dossier = authenticated_client.get(
        f"/v2-clean/workshop/{process.id}/print/process-dossier"
    )
    assert "Oficina Parceira" in closed_dossier.text
    assert "Devolvida" in closed_dossier.text
    closed_external = authenticated_client.get(
        "/v2-clean/workshop?scope=closed&location=external&q=SV-26-AA"
    )
    assert "<strong>SV-26-AA</strong>" in closed_external.text


def test_v2_close_requires_assigned_pending_diagnostic(authenticated_client, db_session):
    process = _v2_repair_process(db_session)
    process.current_phase_code = "fecho"
    db_session.add(WorkshopPhasedProcessPhase(
        process_id=process.id, phase_code="diagnostico", name="Diagnóstico",
        status="pending_documents", sort_order=3, data_json={"form_snapshot": {
            "diagnostic_mode": "late_authorized", "diagnostic_closed": "Pendente",
        }},
    ))
    db_session.add(WorkshopPhasedProcessPhase(
        process_id=process.id, phase_code="fecho", name="Fecho", status="in_progress",
        sort_order=7, data_json={"form_snapshot": {}},
    ))
    db_session.commit()
    page = authenticated_client.get(f"/v2-clean/workshop/fecho?process_id={process.id}")
    assert page.status_code == 200
    assert "Os documentos de diagnóstico ainda não estão validados" in page.text
    data = {"process_id": process.id, "closure_final_summary": "Sem reparação; viatura retida",
            "closure_vehicle_validated": "yes", "closure_history_updated": "yes",
            "closure_fleet_state_defined": "yes", "closure_min_docs_attached": "yes"}
    blocked = authenticated_client.post(
        "/v2-clean/workshop/fecho/save", data={**data, "action": "close_process"},
        follow_redirects=False,
    )
    assert "error=diagnostic_pending" in blocked.headers["location"]
    closed = authenticated_client.post(
        "/v2-clean/workshop/fecho/save",
        data={**data, "action": "close_with_pending", "closure_pending_description": "Validar PDF de diagnóstico",
              "closure_pending_owner": "Responsável oficina", "closure_pending_due": "2026-10-01"},
        follow_redirects=False,
    )
    assert closed.status_code == 303
    db_session.expire_all()
    assert process.status == "closed"
    assert process.closed_at is not None
    report = WorkshopPhasedTechnicalReport(
        process_id=process.id, report_code="other_reading", report_name="Relatório tardio",
        reading_origin="manual", report_moment="initial", status="pending_validation",
        raw_values_json={}, extracted_values_json={},
    )
    db_session.add(report)
    db_session.commit()
    validation = authenticated_client.post(
        f"/v2-clean/workshop/technical-reports/{report.id}/validate",
        data={"reading_report_id": str(report.id), "reading_field_code": "manual_reading",
              "reading_corrected_value": "", "reading_status": "OK", "reading_observation": "Verificado"},
        follow_redirects=False,
    )
    assert validation.status_code == 303
    db_session.expire_all()
    diagnostic = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "diagnostico",
    ))
    closure = db_session.scalar(select(WorkshopPhasedProcessPhase).where(
        WorkshopPhasedProcessPhase.process_id == process.id,
        WorkshopPhasedProcessPhase.phase_code == "fecho",
    ))
    assert diagnostic.status == "completed"
    assert closure.data_json["form_snapshot"]["closure_diagnostic_pending"] == "no"
