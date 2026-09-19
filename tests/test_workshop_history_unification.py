from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.models.vehicles import Vehicle
from app.models.workshop import WorkshopProcess
from app.models.workshop_phased import (
    WorkshopPhasedProcess,
    WorkshopProcessReferenceAlias,
    WorkshopProcessSourceLink,
)
from app.services.workshop_history_unification import (
    build_workshop_history_unification_plan,
    format_unified_workshop_reference,
    normalize_workshop_reference,
)


def _vehicle(db: Session, plate: str) -> Vehicle:
    vehicle = Vehicle(plate=plate, vin=f"VIN{plate.replace('-', '')}123456789", active=True)
    db.add(vehicle)
    db.flush()
    return vehicle


def test_global_reference_format_and_normalization():
    assert format_unified_workshop_reference(1) == "OF-000001"
    assert format_unified_workshop_reference(9876) == "OF-009876"
    assert normalize_workshop_reference(" of-2026 / 0097 ") == "OF20260097"


def test_plan_numbers_legacy_and_current_processes_chronologically(db_session: Session):
    vehicle = _vehicle(db_session, "UN-01-AA")
    legacy = WorkshopProcess(
        vehicle_id=vehicle.id,
        title="Intervenção antiga",
        status="closed",
        opened_on=date(2024, 2, 1),
    )
    current = WorkshopPhasedProcess(
        public_reference="OF-2026-0009",
        opened_at=datetime(2026, 1, 15, 9, 0, tzinfo=UTC),
        process_type="workshop",
        title="Intervenção atual",
        creation_mode="operational",
        status="open",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="entrada",
        priority="normal",
        origin="v2_clean",
    )
    db_session.add_all([legacy, current])
    db_session.commit()

    plan = build_workshop_history_unification_plan(db_session)
    relevant = [item for item in plan.items if item.vehicle_id == vehicle.id]

    assert [item.canonical_reference for item in relevant] == ["OF-000001", "OF-000002"]
    assert relevant[0].plan_operation == "create_historical"
    assert relevant[0].legacy_references == [f"OFI-2024-{legacy.id:06d}"]
    assert relevant[1].plan_operation == "renumber_existing"
    assert relevant[1].legacy_references == ["OF-2026-0009"]


def test_existing_source_link_prevents_duplicate_logical_process(db_session: Session):
    vehicle = _vehicle(db_session, "UN-02-BB")
    legacy = WorkshopProcess(
        vehicle_id=vehicle.id,
        title="Processo antigo ligado",
        status="closed",
        opened_on=date(2025, 4, 8),
    )
    current = WorkshopPhasedProcess(
        opened_at=datetime(2025, 4, 8, 12, 0, tzinfo=UTC),
        process_type="workshop",
        title="Processo unificado",
        creation_mode="historical",
        status="closed",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="fecho",
        priority="normal",
        origin="legacy_migration",
    )
    db_session.add_all([legacy, current])
    db_session.flush()
    db_session.add(
        WorkshopProcessSourceLink(
            process_id=current.id,
            source_system="carfast_legacy",
            source_entity_type="workshop_process",
            source_entity_id=str(legacy.id),
            source_reference="LEGACY-42",
        )
    )
    db_session.commit()

    plan = build_workshop_history_unification_plan(db_session)
    relevant = [item for item in plan.items if item.vehicle_id == vehicle.id]

    assert len(relevant) == 1
    assert relevant[0].source_records == [
        f"workshop_phased_process:{current.id}",
        f"workshop_process:{legacy.id}",
    ]
    assert "LEGACY-42" in relevant[0].legacy_references


def test_same_vehicle_and_date_is_reviewed_not_automatically_merged(db_session: Session):
    vehicle = _vehicle(db_session, "UN-03-CC")
    legacy = WorkshopProcess(
        vehicle_id=vehicle.id,
        title="Possível duplicado",
        status="opening",
        opened_on=date(2026, 5, 20),
    )
    current = WorkshopPhasedProcess(
        opened_at=datetime(2026, 5, 20, 16, 30, tzinfo=UTC),
        process_type="workshop",
        title="Registo atual",
        creation_mode="operational",
        status="open",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="entrada",
        priority="normal",
        origin="v2_clean",
    )
    db_session.add_all([legacy, current])
    db_session.commit()

    plan = build_workshop_history_unification_plan(db_session)
    relevant = [item for item in plan.items if item.vehicle_id == vehicle.id]

    assert len(relevant) == 2
    assert all("possible_duplicate_same_vehicle_and_date" in item.issues for item in relevant)
    legacy_item = next(item for item in relevant if item.target_process_id is None)
    assert legacy_item.plan_operation == "review_before_import"
    assert "legacy_non_terminal_status_requires_review" in legacy_item.issues


def test_history_process_is_visible_and_searchable_by_old_reference(
    authenticated_client,
    db_session: Session,
):
    vehicle = _vehicle(db_session, "UN-04-DD")
    process = WorkshopPhasedProcess(
        canonical_sequence=88,
        public_reference="OF-000088",
        opened_at=datetime(2023, 3, 10, 8, 0, tzinfo=UTC),
        process_type="workshop",
        title="Histórico unificado",
        creation_mode="historical",
        status="closed",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="fecho",
        priority="normal",
        origin="history_unification",
    )
    db_session.add(process)
    db_session.flush()
    db_session.add(
        WorkshopProcessReferenceAlias(
            process_id=process.id,
            reference="OFI-2023-000777",
            normalized_reference="OFI2023000777",
            reference_kind="legacy",
            source_system="carfast_legacy",
            source_entity_id="777",
        )
    )
    db_session.commit()

    response = authenticated_client.get("/v2-clean/workshop?scope=all&q=OFI-2023-000777")

    assert response.status_code == 200
    assert "OF-000088" in response.text
    assert "OFI-2023-000777" in response.text
    assert vehicle.plate in response.text
