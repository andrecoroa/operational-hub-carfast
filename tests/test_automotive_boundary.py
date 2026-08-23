from datetime import UTC, datetime

from app.automotive import (
    AUTOMOTIVE_MANIFEST,
    AutomotiveFacade,
    AutomotiveReference,
    decide_automotive_permission,
)
from app.models.vehicles import Vehicle
from app.models.workshop_phased import WorkshopPhasedProcess


def test_references_are_stable_and_versioned() -> None:
    for kind in ("vehicle", "workshop-process", "sale-profile"):
        reference = AutomotiveReference(kind, 7)
        assert AutomotiveReference.parse(reference.value) == reference


def test_vehicle_and_open_process_snapshots_preserve_operational_context(db_session) -> None:
    vehicle = Vehicle(plate="00-AA-00", brand="Synthetic", model="Fleet", lifecycle_status="active")
    db_session.add(vehicle)
    db_session.flush()
    opened = datetime(2026, 1, 2, tzinfo=UTC)
    process = WorkshopPhasedProcess(
        opened_at=opened,
        process_type="repair",
        title="Synthetic process",
        creation_mode="manual",
        status="in_progress",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="diagnostico",
        priority="normal",
        responsible_user_id=None,
    )
    db_session.add(process)
    db_session.flush()

    facade = AutomotiveFacade(db_session)
    summary = facade.vehicle_summary(AutomotiveReference("vehicle", vehicle.id))
    snapshot = facade.workshop_snapshot(AutomotiveReference("workshop-process", process.id))

    assert summary and summary.plate == "00-AA-00"
    assert snapshot and snapshot.status == "in_progress"
    assert snapshot.phase_code == "diagnostico"
    assert snapshot.opened_at == opened
    assert snapshot.vehicle_reference == AutomotiveReference("vehicle", vehicle.id)


def test_manifest_keeps_internal_capabilities_separate() -> None:
    assert AUTOMOTIVE_MANIFEST.code == "automotive"
    assert {"fleet", "workshop", "sales"} <= set(AUTOMOTIVE_MANIFEST.capabilities)
    assert "stock" not in AUTOMOTIVE_MANIFEST.dependencies


def test_permissions_map_legacy_without_expansion() -> None:
    assert decide_automotive_permission("automotive.fleet.read", {"vehicles.read"}).allowed
    assert decide_automotive_permission("automotive.workshop.write", {"workshop.write"}).allowed
    assert not decide_automotive_permission("automotive.workshop.write", {"workshop.read"}).allowed
    assert not decide_automotive_permission("automotive.unknown", {"admin.manage"}).allowed


def test_core_package_does_not_import_optional_stock_or_web_routes() -> None:
    import app.automotive as automotive

    source = open(automotive.__file__, encoding="utf-8").read()
    assert "stock_domain" not in source
    assert "app.web" not in source
