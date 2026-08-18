import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.admin import User
from app.models.vehicles import Vehicle
from app.models.workshop_phased import (
    WorkshopDiagnosticCatalogItem,
    WorkshopMaterialNeed,
    WorkshopPhasedProcess,
    WorkshopPublicCounter,
    WorkshopTemplate,
    WorkshopTemplateVersion,
)
from app.services.workshop_configuration import allocate_workshop_public_reference
from app.web.router import (
    clean_workshop_next_phase_key,
    clean_workshop_process_reference,
)


def test_public_reference_sequence_is_atomic_across_sessions(tmp_path):
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'workshop-sequence.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    WorkshopPublicCounter.__table__.create(bind=engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    moment = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)

    def allocate() -> str:
        with sessions() as db:
            reference = allocate_workshop_public_reference(db, moment)
            db.commit()
            return reference

    with ThreadPoolExecutor(max_workers=6) as executor:
        references = list(executor.map(lambda _: allocate(), range(12)))

    assert len(set(references)) == 12
    assert sorted(int(reference.rsplit("-", 1)[1]) for reference in references) == list(
        range(1, 13)
    )
    assert all(reference.startswith("OF-2026-") for reference in references)


def test_new_clean_process_keeps_real_author_and_template_snapshot(
    authenticated_client,
    db_session: Session,
):
    vehicle = Vehicle(
        plate="OF-26-AA",
        vin="VINOF26AA123456789",
        brand="PEUGEOT",
        model="208",
        version="1.5 BlueHDi",
        active=True,
    )
    db_session.add(vehicle)
    db_session.commit()

    response = authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={
            "plate": vehicle.plate,
            "entry_reasons": ["Revisão / degradação óleo"],
            "entry_km": "44000",
            "priority": "Normal",
            "action": "save",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    process_id = int(response.headers["location"].split("process_id=")[1].split("&")[0])
    db_session.expire_all()
    process = db_session.get(WorkshopPhasedProcess, process_id)
    creator = db_session.scalar(select(User).where(User.email == "admin.tests@carfast.local"))

    assert process is not None
    assert process.public_reference == "OF-2026-0001"
    assert process.opened_at is not None
    assert process.created_by_id == creator.id
    assert process.responsible_user_id == creator.id
    assert process.template_snapshot_json["template_code"] == "scheduled_maintenance"
    original_snapshot = process.template_snapshot_json

    template = db_session.scalar(
        select(WorkshopTemplate).where(WorkshopTemplate.code == "scheduled_maintenance")
    )
    published = authenticated_client.post(
        f"/v2-clean/admin/workshop-models/{template.id}/new-version",
        data={"change_note": "Nova versão para processos futuros"},
        follow_redirects=False,
    )
    assert published.status_code == 303
    db_session.expire_all()
    process = db_session.get(WorkshopPhasedProcess, process_id)
    versions = db_session.scalars(
        select(WorkshopTemplateVersion).where(WorkshopTemplateVersion.template_id == template.id)
    ).all()
    assert len(versions) == 2
    assert process.template_snapshot_json == original_snapshot

    process.responsible_user_id = None
    db_session.commit()
    db_session.refresh(process)
    assert process.created_by_id == creator.id


def test_general_template_navigation_and_historical_reference_compatibility(
    authenticated_client,
    db_session: Session,
):
    vehicle = Vehicle(plate="OF-26-BB", vin="VINOF26BB123456789", active=True)
    db_session.add(vehicle)
    legacy = WorkshopPhasedProcess(
        process_type="workshop",
        title="Processo legado",
        creation_mode="operational",
        status="open",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="entrada",
        priority="normal",
        origin="v2_clean",
        metadata_json={},
    )
    db_session.add(legacy)
    db_session.commit()
    assert clean_workshop_process_reference(legacy).startswith("OFI-")

    response = authenticated_client.post(
        "/v2-clean/workshop-entry",
        data={
            "plate": vehicle.plate,
            "entry_reasons": ["Outro"],
            "entry_km": "1200",
            "action": "save",
        },
        follow_redirects=False,
    )
    process_id = int(response.headers["location"].split("process_id=")[1].split("&")[0])
    db_session.expire_all()
    process = db_session.get(WorkshopPhasedProcess, process_id)

    assert process.template_snapshot_json["template_code"] == "general_minimum"
    assert clean_workshop_next_phase_key("entrada", process) == "validacao"
    assert clean_workshop_next_phase_key("validacao", process) == "diagnostico"
    assert clean_workshop_next_phase_key("diagnostico", process) == "fecho"

    legacy_page = authenticated_client.get(f"/v2-clean/workshop-entry?process_id={legacy.id}")
    assert legacy_page.status_code == 200
    assert clean_workshop_process_reference(legacy) in legacy_page.text


def test_material_need_records_contract_without_simulating_stock(
    authenticated_client,
    db_session: Session,
):
    vehicle = Vehicle(
        plate="OF-26-CC",
        vin="VINOF26CC123456789",
        version="1.2 PureTech",
        active=True,
    )
    db_session.add(vehicle)
    db_session.flush()
    process = WorkshopPhasedProcess(
        public_reference="OF-2026-9999",
        opened_at=datetime.now(UTC),
        process_type="workshop",
        title="Material",
        creation_mode="operational",
        status="open",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="reparacao",
        priority="normal",
        origin="v2_clean",
        metadata_json={},
    )
    db_session.add(process)
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/material-needs",
        data={
            "origin": "diagnostic",
            "operation_code": "replace_front_pads",
            "operation_label": "Substituir pastilhas dianteiras",
            "material_code": "PAD-FRONT",
            "material_description": "Jogo de pastilhas dianteiras",
            "requested_quantity": "1 jogo",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    need = db_session.scalar(
        select(WorkshopMaterialNeed).where(WorkshopMaterialNeed.process_id == process.id)
    )
    assert need is not None
    assert need.origin == "diagnostic"
    assert need.vehicle_variant == "1.2 PureTech"
    assert need.stock_status == "unavailable"
    assert need.stock_request_reference is None
    assert need.detail_json["neutral_message"] == "Stock ainda não disponível"

    contract_response = authenticated_client.get("/api/workshop/stock-contract")
    assert contract_response.status_code == 200
    contract = contract_response.json()
    assert contract["available"] is False
    assert contract["message"] == "Stock ainda não disponível"
    assert "availability" in contract["ownership"]["stock"]
    assert "application_confirmation" in contract["ownership"]["workshop"]


def test_admin_publishes_validated_template_config_and_edits_diagnostic_catalog(
    authenticated_client,
    db_session: Session,
):
    authenticated_client.get("/v2-clean/admin/workshop-models")
    template = db_session.scalar(
        select(WorkshopTemplate).where(WorkshopTemplate.code == "general_minimum")
    )
    latest = db_session.scalar(
        select(WorkshopTemplateVersion)
        .where(WorkshopTemplateVersion.template_id == template.id)
        .order_by(WorkshopTemplateVersion.version_number.desc())
    )
    edited_config = dict(latest.config_json)
    edited_config["rules"] = {"fallback": True, "admin_test": True}

    published = authenticated_client.post(
        f"/v2-clean/admin/workshop-models/{template.id}/new-version",
        data={
            "change_note": "Configuração administrada",
            "config_json": json.dumps(edited_config),
        },
        follow_redirects=False,
    )
    assert published.status_code == 303
    db_session.expire_all()
    newest = db_session.scalar(
        select(WorkshopTemplateVersion)
        .where(WorkshopTemplateVersion.template_id == template.id)
        .order_by(WorkshopTemplateVersion.version_number.desc())
    )
    assert newest.version_number == latest.version_number + 1
    assert newest.config_json["rules"]["admin_test"] is True

    invalid = authenticated_client.post(
        f"/v2-clean/admin/workshop-models/{template.id}/new-version",
        data={"change_note": "Inválida", "config_json": json.dumps({"phases": []})},
        follow_redirects=False,
    )
    assert invalid.status_code == 303
    assert "error=" in invalid.headers["location"]

    diagnostic = db_session.scalar(select(WorkshopDiagnosticCatalogItem))
    updated = authenticated_client.post(
        f"/v2-clean/admin/workshop-diagnostics/{diagnostic.id}",
        data={
            "name": diagnostic.name,
            "family": diagnostic.family,
            "equipment": diagnostic.equipment or "",
            "phase_code": "diagnostico",
            "requirement": "required",
            "validity_days": "14",
            "expected_document_type": diagnostic.expected_document_type or "",
            "applicability_json": json.dumps({"models": ["208"]}),
            "history_rules_json": json.dumps({"prefer_recent_validated": True}),
            "extraction_fields_json": json.dumps(["faults"]),
            "active": "on",
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    db_session.expire_all()
    diagnostic = db_session.get(WorkshopDiagnosticCatalogItem, diagnostic.id)
    assert diagnostic.requirement == "required"
    assert diagnostic.validity_days == 14
    assert diagnostic.applicability_json == {"models": ["208"]}


def test_admin_publishes_workshop_model_from_visual_form_preserving_advanced_fields(
    authenticated_client,
    db_session: Session,
):
    authenticated_client.get("/v2-clean/admin/workshop-models")
    template = db_session.scalar(
        select(WorkshopTemplate).where(WorkshopTemplate.code == "general_minimum")
    )
    previous = db_session.scalar(
        select(WorkshopTemplateVersion)
        .where(WorkshopTemplateVersion.template_id == template.id)
        .order_by(WorkshopTemplateVersion.version_number.desc())
    )
    entry_before = next(
        phase for phase in previous.config_json["phases"] if phase["code"] == "entrada"
    )

    response = authenticated_client.post(
        f"/v2-clean/admin/workshop-models/{template.id}/new-version",
        data={
            "template_name": "Modelo geral operacional",
            "template_description": "Gerido pelo formulário visual.",
            "entry_reason_code": "",
            "change_note": "Reordenação visual",
            "phase_included": ["0", "1", "2"],
            "phase_required": ["0", "2"],
            "phase_order": ["1", "2", "3"],
            "phase_code": ["entrada", "diagnostico", "fecho"],
            "phase_name": ["Entrada compacta", "Diagnóstico", "Fecho"],
            "phase_responsible_role": ["workshop", "technician", "workshop_manager"],
            "phase_transition_rules": [
                "entry_km_present, entry_reason_present",
                "reports_validated_or_reserved",
                "closure_conditions_met",
            ],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "published=" in response.headers["location"]
    db_session.expire_all()
    template = db_session.get(WorkshopTemplate, template.id)
    newest = db_session.scalar(
        select(WorkshopTemplateVersion)
        .where(WorkshopTemplateVersion.template_id == template.id)
        .order_by(WorkshopTemplateVersion.version_number.desc())
    )
    assert template.name == "Modelo geral operacional"
    assert template.entry_reason_code is None
    assert newest.version_number == previous.version_number + 1
    assert [phase["code"] for phase in newest.config_json["phases"]] == [
        "entrada",
        "diagnostico",
        "fecho",
    ]
    entry_after = newest.config_json["phases"][0]
    assert entry_after["required_fields"] == entry_before["required_fields"]
    assert entry_after["transition_rules"] == ["entry_km_present", "entry_reason_present"]
    assert newest.config_json["template_name"] == "Modelo geral operacional"
    assert newest.config_json["entry_reason_code"] is None
    assert newest.config_json["rules"]["fallback"] is True


def test_visual_workshop_model_validation_does_not_mutate_template_metadata(
    authenticated_client,
    db_session: Session,
):
    authenticated_client.get("/v2-clean/admin/workshop-models")
    template = db_session.scalar(
        select(WorkshopTemplate).where(WorkshopTemplate.code == "scheduled_maintenance")
    )
    original_name = template.name
    original_version_count = len(
        db_session.scalars(
            select(WorkshopTemplateVersion).where(
                WorkshopTemplateVersion.template_id == template.id
            )
        ).all()
    )

    response = authenticated_client.post(
        f"/v2-clean/admin/workshop-models/{template.id}/new-version",
        data={
            "template_name": "Nome que não deve persistir",
            "change_note": "Inválida sem fecho",
            "phase_included": ["0"],
            "phase_required": ["0"],
            "phase_order": ["1"],
            "phase_code": ["entrada"],
            "phase_name": ["Entrada"],
            "phase_responsible_role": ["workshop"],
            "phase_transition_rules": ["entry_km_present"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "error=" in response.headers["location"]
    db_session.expire_all()
    template = db_session.get(WorkshopTemplate, template.id)
    assert template.name == original_name
    assert len(
        db_session.scalars(
            select(WorkshopTemplateVersion).where(
                WorkshopTemplateVersion.template_id == template.id
            )
        ).all()
    ) == original_version_count
