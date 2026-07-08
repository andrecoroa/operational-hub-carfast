from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

from app.models.vehicles import Vehicle
from app.models.workshop_phased import (
    WorkshopPhasedProcess,
    WorkshopPhasedProcessPhase,
    WorkshopPhasedTechnicalReport,
)
from app.web.router import clean_workshop_technical_reading_rows


def _created_process_id(location: str) -> int:
    return int(parse_qs(urlparse(location).query)["process_id"][0])


def test_clean_workshop_entry_validation_and_diagnostic_flow(client, db_session):
    vehicle = Vehicle(
        plate="BB-13-PT",
        vin="VINBB13PT123456789",
        brand="PEUGEOT",
        model="2008",
        version="ALLURE",
        rentway_unit_nr="57",
        lifecycle_status="active",
        operational_status="free",
        active=True,
    )
    db_session.add(vehicle)
    db_session.commit()
    db_session.refresh(vehicle)

    login = client.post(
        "/login",
        data={"email": "admin.tests@carfast.local", "password": "Secret123!"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    notice = client.post("/change-notice", data={"next_url": "/"}, follow_redirects=False)
    assert notice.status_code == 303

    created = client.get(
        f"/v2-clean/workshop-entry?vehicle_id={vehicle.id}&new=1",
        follow_redirects=False,
    )
    assert created.status_code == 303
    process_id = _created_process_id(created.headers["location"])

    entry_payload = {
        "process_id": str(process_id),
        "entry_reasons": ["Revisão / degradação óleo", "Pneus"],
        "short_description": "Teste entrada",
        "requested_service": "Confirmar manutenção e pneus",
        "entry_km": "143161",
        "reported_by": "Operador",
        "priority": "Normal",
        "can_drive": "Por confirmar",
        "visible_damage": "not_checked",
        "damage_matches_rentway": "not_checked",
        "dua_copy": "yes",
        "green_card_valid": "yes",
        "vv_device": "yes",
        "reflective_vest": "yes",
        "triangle": "yes",
        "spare_tyre": "yes",
        "jack": "yes",
        "inflation_kit": "yes",
        "physical_check_note": "ok",
        "minimum_reason_selected": "yes",
        "minimum_km_confirmed": "yes",
        "minimum_dashboard_photo": "yes",
        "minimum_damage_photos": "yes",
        "expected_exit": "2026-06-30T10:00",
        "validation_notes": "nota",
    }

    saved_entry = client.post(
        "/v2-clean/workshop-entry",
        data={**entry_payload, "action": "save"},
        files={
            "dashboard_photo": ("quadrante.jpg", b"fake dashboard image", "image/jpeg"),
            "vehicle_front_photo": ("frente.jpg", b"fake front image", "image/jpeg"),
        },
        follow_redirects=False,
    )
    assert saved_entry.status_code == 303
    assert saved_entry.headers["location"] == f"/v2-clean/workshop-entry?process_id={process_id}&saved=1"

    advanced_entry = client.post(
        "/v2-clean/workshop-entry",
        data={**entry_payload, "action": "advance"},
        follow_redirects=False,
    )
    assert advanced_entry.status_code == 303
    assert advanced_entry.headers["location"] == f"/v2-clean/workshop/validacao?process_id={process_id}"

    process = db_session.get(WorkshopPhasedProcess, process_id)
    assert process is not None
    assert process.current_phase_code == "validacao"
    assert process.initial_km == 143161

    entry_phase = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == "entrada",
        )
    )
    assert entry_phase is not None
    assert entry_phase.status == "completed"
    assert len(entry_phase.data_json["uploads"]) == 2
    assert {item["slot"] for item in entry_phase.data_json["uploads"]} == {"dashboard", "front"}
    assert entry_phase.data_json["physical_checks"]["damage_matches_rentway"] == "not_checked"
    assert entry_phase.data_json["minimum_checks"]["minimum_reason_selected"] == "yes"
    assert entry_phase.data_json["minimum_checks"]["minimum_km_confirmed"] == "yes"
    assert entry_phase.data_json["minimum_checks"]["minimum_damage_photos"] == "yes"

    validation_payload = {
        "process_id": str(process_id),
        "service_type": ["Revisão / degradação óleo", "Pneus"],
        "service_already_done": ["Não", "Sim"],
        "previous_service_date": ["2026-01-10", "2026-03-01"],
        "previous_service_km": ["120000", "130000"],
        "previous_service_supplier": ["Oficina A", "Oficina B"],
        "previous_service_document": ["FO 1", "FT 2"],
        "service_decision": ["Seguir diagnóstico", "Pedir confirmação"],
        "validation_observation": "teste validacao",
    }

    saved_validation = client.post(
        "/v2-clean/workshop/validacao/save",
        data={**validation_payload, "action": "save"},
        follow_redirects=False,
    )
    assert saved_validation.status_code == 303
    assert saved_validation.headers["location"] == f"/v2-clean/workshop/validacao?process_id={process_id}&saved=1"

    advanced_validation = client.post(
        "/v2-clean/workshop/validacao/save",
        data={**validation_payload, "action": "advance"},
        follow_redirects=False,
    )
    assert advanced_validation.status_code == 303
    assert advanced_validation.headers["location"] == f"/v2-clean/workshop/diagnostico?process_id={process_id}"

    validation_phase = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == "validacao",
        )
    )
    assert validation_phase is not None
    assert validation_phase.status == "completed"
    assert validation_phase.data_json["form_snapshot"]["service_decision"] == [
        "Seguir diagnóstico",
        "Pedir confirmação",
    ]

    upload = client.post(
        f"/v2-clean/workshop/{process_id}/technical-reports/upload",
        data={"report_code": "maintenance_information"},
        files={"report_file": ("teste.pdf", b"not a real pdf", "application/pdf")},
        follow_redirects=False,
    )
    assert upload.status_code == 303
    assert upload.headers["location"] == f"/v2-clean/workshop/diagnostico?process_id={process_id}&report_uploaded=1#leituras"

    report = db_session.scalar(
        select(WorkshopPhasedTechnicalReport).where(WorkshopPhasedTechnicalReport.process_id == process_id)
    )
    assert report is not None
    assert report.status == "unable_to_read"

    diagnosis_page = client.get(f"/v2-clean/workshop/diagnostico?process_id={process_id}")
    assert diagnosis_page.status_code == 200
    assert "Dados extraídos por validar" in diagnosis_page.text
    assert "Leitura automática" in diagnosis_page.text
    assert "Abrir documento" in diagnosis_page.text

    diagnosis_payload = {
        "process_id": str(process_id),
        "pre_report_exists": "Existe",
        "post_report_exists": "Por confirmar",
        "bsi_vs_billing": "Divergente",
        "remote_download_vs_tsb": "Por confirmar",
        "comparison_differences": "Diferença entre BSI e faturação.",
        "comparison_evidence": "Relatório manutenção vs FO.",
        "diagnostic_problem_detected": "Problema identificado",
        "diagnostic_problem_title": "BSI incoerente",
        "diagnostic_problem_origin": "Informações manutenção",
        "diagnostic_problem_evidence": "Nº de manutenções não coincide.",
        "diagnostic_problem_action": "Acompanhar em auditoria.",
        "diagnostic_closed": "Com reservas",
        "diagnostic_priority": "Alta",
        "diagnostic_conclusion": "Diagnóstico pronto para inspeção.",
        "inspection_required_oil": "yes",
        "inspection_required_bsi": "yes",
        "inspection_required_road_test": "yes",
        "diagnostic_reserve_reason": "Falta confirmar histórico completo.",
    }

    saved_diagnosis = client.post(
        "/v2-clean/workshop/diagnostico/save",
        data={**diagnosis_payload, "action": "save"},
        follow_redirects=False,
    )
    assert saved_diagnosis.status_code == 303
    assert saved_diagnosis.headers["location"] == f"/v2-clean/workshop/diagnostico?process_id={process_id}&saved=1"

    advanced_diagnosis = client.post(
        "/v2-clean/workshop/diagnostico/save",
        data={**diagnosis_payload, "action": "advance"},
        follow_redirects=False,
    )
    assert advanced_diagnosis.status_code == 303
    assert advanced_diagnosis.headers["location"] == f"/v2-clean/workshop/inspecao?process_id={process_id}"

    diagnosis_phase = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == "diagnostico",
        )
    )
    assert diagnosis_phase is not None
    assert diagnosis_phase.status == "completed"
    assert diagnosis_phase.data_json["form_snapshot"]["diagnostic_problem_title"] == "BSI incoerente"
    assert diagnosis_phase.data_json["form_snapshot"]["inspection_required_oil"] == "yes"

    inspection_payload = {
        "process_id": str(process_id),
        "inspection_check_lights": "ok",
        "inspection_check_battery": "review",
        "inspection_check_leaks": "nc",
        "inspection_check_noises": "ok",
        "inspection_check_road_test": "na",
        "inspection_check_leaks_note": "Fuga ligeira visível.",
        "tyres_front_condition": "4 mm",
        "tyres_rear_condition": "5 mm",
        "pads_front_condition": "30%",
        "discs_front_condition": "Sem ressalto",
        "brakes_rear_condition": "Conforme",
        "oil_level": "OK",
        "oil_visual_state": "Suspeito",
        "coolant_level": "OK",
        "brake_fluid_level": "OK",
        "oil_diagnosis_confirmed": "Sim",
        "oil_levels_observation": "Compatível com o diagnóstico.",
        "inspection_closed": "Com reservas",
        "inspection_priority": "Alta",
        "inspection_summary": "Inspeção pronta para auditoria.",
        "inspection_create_task": "yes",
        "inspection_needs_quote": "yes",
        "inspection_reserve_reason": "Falta decisão sobre orçamento.",
    }

    saved_inspection = client.post(
        "/v2-clean/workshop/inspecao/save",
        data={**inspection_payload, "action": "save"},
        follow_redirects=False,
    )
    assert saved_inspection.status_code == 303
    assert saved_inspection.headers["location"] == f"/v2-clean/workshop/inspecao?process_id={process_id}&saved=1"

    advanced_inspection = client.post(
        "/v2-clean/workshop/inspecao/save",
        data={**inspection_payload, "action": "advance"},
        follow_redirects=False,
    )
    assert advanced_inspection.status_code == 303
    assert advanced_inspection.headers["location"] == f"/v2-clean/workshop/auditoria?process_id={process_id}"

    inspection_phase = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == "inspecao",
        )
    )
    assert inspection_phase is not None
    assert inspection_phase.status == "completed"
    assert inspection_phase.data_json["form_snapshot"]["inspection_check_leaks"] == "nc"
    assert inspection_phase.data_json["form_snapshot"]["inspection_summary"] == "Inspeção pronta para auditoria."

    audit_payload = {
        "process_id": str(process_id),
        "audit_evidence_summary": "Diagnóstico e inspeção suportam decisão técnica.",
        "audit_bsi_billing_result": "Divergente",
        "audit_oil_limit_result": "Crítico",
        "audit_remote_download_result": "Por confirmar",
        "audit_service_repeat_result": "Sim - suspeita",
        "audit_open_items_summary": "Falta validar histórico e orçamento.",
        "audit_decision_main": "Pedir orçamento",
        "audit_repair_authorized": "Com reserva",
        "audit_responsibility": "Fornecedor",
        "audit_quote_needed": "Sim",
        "audit_estimated_value": "350,00",
        "audit_decision_reason": "Necessário orçamento antes de autorizar.",
        "audit_closed": "Com reservas",
        "audit_priority": "Alta",
        "audit_summary": "Auditoria pronta para reparação condicionada.",
        "audit_condition_service_confirmed": "yes",
        "audit_condition_problems_logged": "yes",
        "audit_reserve_reason": "Aguardar orçamento.",
    }

    saved_audit = client.post(
        "/v2-clean/workshop/auditoria/save",
        data={**audit_payload, "action": "save"},
        follow_redirects=False,
    )
    assert saved_audit.status_code == 303
    assert saved_audit.headers["location"] == f"/v2-clean/workshop/auditoria?process_id={process_id}&saved=1"

    advanced_audit = client.post(
        "/v2-clean/workshop/auditoria/save",
        data={**audit_payload, "action": "advance"},
        follow_redirects=False,
    )
    assert advanced_audit.status_code == 303
    assert advanced_audit.headers["location"] == f"/v2-clean/workshop/reparacao?process_id={process_id}"

    audit_phase = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == "auditoria",
        )
    )
    assert audit_phase is not None
    assert audit_phase.status == "completed"
    assert audit_phase.data_json["form_snapshot"]["audit_decision_main"] == "Pedir orçamento"

    repair_payload = {
        "process_id": str(process_id),
        "repair_authorized_services": "Confirmar óleo e validar BSI.",
        "repair_execution_status": "Em curso",
        "repair_responsible": "Oficina Porto",
        "repair_started_on": "2026-06-30",
        "repair_eta": "2026-07-01",
        "repair_vehicle_immobilized": "Sim",
        "repair_execution_note": "A aguardar validação final do orçamento.",
        "repair_fo_status": "Recebida",
        "repair_photos_status": "Parcial",
        "repair_post_report_status": "Pendente",
        "repair_campaign_proof_status": "N/A",
        "repair_deviation_exists": "Sim",
        "repair_new_quote_needed": "Sim",
        "repair_deviation_reason": "Foram detetadas peças adicionais.",
        "repair_timing_impact": "Adia conclusão",
        "repair_financial_impact": "125,00",
        "repair_action_needed": "Validar novo valor.",
        "repair_closed": "Com reservas",
        "repair_exit_status": "Alta",
        "repair_summary": "Reparação segue com reserva documental.",
        "repair_done": "yes",
        "repair_fo_attached": "yes",
        "repair_reserve_reason": "Pós-relatório ainda em falta.",
    }

    saved_repair = client.post(
        "/v2-clean/workshop/reparacao/save",
        data={**repair_payload, "action": "save"},
        follow_redirects=False,
    )
    assert saved_repair.status_code == 303
    assert saved_repair.headers["location"] == f"/v2-clean/workshop/reparacao?process_id={process_id}&saved=1"

    advanced_repair = client.post(
        "/v2-clean/workshop/reparacao/save",
        data={**repair_payload, "action": "advance"},
        follow_redirects=False,
    )
    assert advanced_repair.status_code == 303
    assert advanced_repair.headers["location"] == f"/v2-clean/workshop/fecho?process_id={process_id}"

    repair_phase = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == "reparacao",
        )
    )
    assert repair_phase is not None
    assert repair_phase.status == "completed"
    assert repair_phase.data_json["form_snapshot"]["repair_authorized_services"] == "Confirmar óleo e validar BSI."

    closure_payload = {
        "process_id": str(process_id),
        "closure_vehicle_ready": "Sim",
        "closure_final_status": "Normal",
        "closure_exit_observation": "Viatura pronta a regressar à frota.",
        "closure_km_checked": "yes",
        "closure_dashboard_exit_photo": "yes",
        "closure_final_test_ok": "yes",
        "closure_can_drive": "yes",
        "closure_back_to_fleet": "yes",
        "closure_work_order_status": "Validada",
        "closure_invoice_status": "Recebida",
        "closure_post_report_status": "Recebido",
        "closure_final_photos_status": "Recebidas",
        "closure_service_history_status": "Registado",
        "closure_next_maintenance_status": "Atualizada",
        "closure_problem_history_status": "Acompanhar",
        "closure_audit_history_status": "Reserva",
        "closure_sale_state_status": "Aviso",
        "closure_pending_exists": "Sim",
        "closure_pending_type": "Auditoria histórico",
        "closure_pending_owner": "Gestão",
        "closure_pending_due": "2026-07-05",
        "closure_pending_blocks_use": "Não",
        "closure_pending_description": "Fechar auditoria histórica.",
        "closure_result": "Fechado com reparação",
        "closure_state": "Com reserva",
        "closure_summary": "Processo encerrado com reparação executada.",
        "closure_vehicle_validated": "yes",
        "closure_min_docs_attached": "yes",
        "closure_history_updated": "yes",
        "closure_pending_assigned": "yes",
        "closure_fleet_state_defined": "yes",
        "closure_final_note": "Reserva apenas administrativa.",
    }

    saved_closure = client.post(
        "/v2-clean/workshop/fecho/save",
        data={**closure_payload, "action": "save"},
        follow_redirects=False,
    )
    assert saved_closure.status_code == 303
    assert saved_closure.headers["location"] == f"/v2-clean/workshop/fecho?process_id={process_id}&saved=1"

    advanced_closure = client.post(
        "/v2-clean/workshop/fecho/save",
        data={**closure_payload, "action": "advance"},
        follow_redirects=False,
    )
    assert advanced_closure.status_code == 303
    assert advanced_closure.headers["location"] == f"/v2-clean/workshop/fecho?process_id={process_id}&saved=1"

    closure_phase = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == "fecho",
        )
    )
    assert closure_phase is not None
    assert closure_phase.status == "completed"
    assert closure_phase.data_json["form_snapshot"]["closure_result"] == "Fechado com reparação"

    db_session.expire_all()
    process = db_session.get(WorkshopPhasedProcess, process_id)
    assert process is not None
    assert process.status == "closed"

    closed_page = client.get(f"/v2-clean/workshop/fecho?process_id={process_id}")
    assert closed_page.status_code == 200
    assert "Processo fechado" in closed_page.text
    assert "Este processo de oficina está encerrado." in closed_page.text
    assert 'name="action" value="advance"' not in closed_page.text

    validate = client.post(
        f"/v2-clean/workshop/technical-reports/{report.id}/validate",
        data={
            "reading_report_id": str(report.id),
            "reading_field_code": "manual_reading",
            "reading_corrected_value": "PDF ilegível mas confirmado manualmente",
            "reading_status": "Corrigido",
            "reading_observation": "teste",
        },
        follow_redirects=False,
    )
    assert validate.status_code == 303
    assert validate.headers["location"] == f"/v2-clean/workshop/diagnostico?process_id={process_id}&report_validated=1#leituras"

    db_session.expire_all()
    report = db_session.scalar(
        select(WorkshopPhasedTechnicalReport).where(WorkshopPhasedTechnicalReport.process_id == process_id)
    )
    assert report is not None
    assert report.status == "corrected_manually"
    assert report.validated_values_json["manual_reading"]["status"] == "Corrigido"


def test_clean_workshop_reading_rows_hide_failed_report_when_valid_data_exists():
    reports = [
        WorkshopPhasedTechnicalReport(
            id=1,
            process_id=10,
            report_code="maintenance_information",
            report_name="Informações manutenção",
            status="unable_to_read",
            original_link="uploads/workshop_reports/10/maintenance_information.pdf",
            raw_values_json={"extraction_error": "Failed to open stream"},
            extracted_values_json={},
            validated_values_json=None,
        ),
        WorkshopPhasedTechnicalReport(
            id=2,
            process_id=10,
            report_code="engine_lubrication",
            report_name="Lubrificacao motor",
            status="pending_validation",
            original_link="uploads/workshop_reports/10/engine_lubrication.pdf",
            raw_values_json={"original_name": "lub.pdf"},
            extracted_values_json={"engine_speed": "0", "oil_dilution_rate": "5.125"},
            validated_values_json=None,
        ),
    ]

    rows = clean_workshop_technical_reading_rows(reports)

    assert [row["field_code"] for row in rows] == ["engine_speed", "oil_dilution_rate"]
    assert all(row["report"] == "Lubrificacao motor" for row in rows)
