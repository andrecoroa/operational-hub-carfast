from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import func, select

from app.models.audit import AuditLog
from app.models.stock import StockArticle, StockLocation, StockMovement
from app.models.vehicles import Vehicle
from app.models.workshop_phased import (
    WorkshopMaterialNeed,
    WorkshopPhasedProcess,
    WorkshopPhasedProcessPhase,
)
from app.services.stock import stock_balances


def _source_process_with_applied_tyres(db_session):
    vehicle = Vehicle(
        plate="BC-00-FB",
        brand="DS",
        model="4",
        active=True,
        lifecycle_status="active",
    )
    article = StockArticle(
        internal_ref="19510317210V3",
        name="215/65R17 99V TL EC 6 DEMO PNEU CONTI.",
        unit="un",
        average_cost=Decimal("80.00"),
    )
    location = StockLocation(code="WORKSHOP-REPLACEMENT", name="Oficina", active=True)
    db_session.add_all([vehicle, article, location])
    db_session.flush()
    db_session.add(
        StockMovement(
            article_id=article.id,
            movement_type="entry",
            quantity=Decimal("5"),
            unit="un",
            unit_cost=Decimal("80.00"),
            to_location_id=location.id,
            reason="Existência inicial",
            effective_date=date(2026, 7, 14),
        )
    )
    process = WorkshopPhasedProcess(
        public_reference="OF-2025-0099",
        opened_at=datetime(2026, 7, 14, tzinfo=UTC),
        received_at=datetime(2026, 7, 14, tzinfo=UTC),
        process_type="workshop",
        title="OF-2025-0099 · BC-00-FB",
        creation_mode="operational",
        status="open",
        vehicle_id=vehicle.id,
        plate_snapshot=vehicle.plate,
        current_phase_code="reparacao",
        priority="normal",
        origin="v2_clean",
        initial_km=52265,
        initial_observation="Substituição de dois pneus.",
        metadata_json={"entry_reasons": ["Pneus"]},
    )
    db_session.add(process)
    db_session.flush()
    db_session.add(
        WorkshopPhasedProcessPhase(
            process_id=process.id,
            phase_code="entrada",
            name="Entrada",
            status="completed",
            sort_order=1,
            data_json={
                "entry_reasons": ["Pneus"],
                "entry_km": "52265",
                "short_description": "Substituição de dois pneus.",
            },
        )
    )
    exit_movement = StockMovement(
        article_id=article.id,
        movement_type="exit",
        quantity=Decimal("2"),
        unit="un",
        unit_cost=Decimal("80.00"),
        from_location_id=location.id,
        external_reference_type="workshop_material_request",
        external_reference_id="OF-TEST-TYRES",
        reason=f"Entrega à Oficina · processo #{process.id}",
        effective_date=date(2026, 7, 14),
    )
    db_session.add(exit_movement)
    db_session.flush()
    need = WorkshopMaterialNeed(
        process_id=process.id,
        phase_code="reparacao",
        origin="repair",
        operation_code="repair_material",
        operation_label="Material para reparação",
        vehicle_id=vehicle.id,
        material_code=article.internal_ref,
        material_description=article.name,
        requested_quantity="2",
        stock_status="applied",
        stock_request_reference="OF-TEST-TYRES",
        detail_json={
            "article_id": article.id,
            "movement_id": exit_movement.id,
            "stock_location_id": location.id,
            "unit_cost": "80.0000",
            "total_cost": "160.0000",
        },
    )
    db_session.add(need)
    db_session.commit()
    return process, need, article, location, exit_movement


def test_admin_replaces_process_and_transfers_stock_attribution_atomically(
    authenticated_client, db_session
):
    process, need, article, location, movement = _source_process_with_applied_tyres(db_session)
    movement_count_before = db_session.scalar(select(func.count(StockMovement.id)))
    balance_before = stock_balances(db_session)[(article.id, location.id)]

    response = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/replace",
        data={
            "observation": "Migrar o processo para o novo fluxo simplificado.",
            "task_action": "keep",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    query = parse_qs(urlsplit(response.headers["location"]).query)
    replacement_id = int(query["process_id"][0])
    assert int(query["replaced_from"][0]) == process.id
    db_session.expire_all()

    source = db_session.get(WorkshopPhasedProcess, process.id)
    replacement = db_session.get(WorkshopPhasedProcess, replacement_id)
    assert source.status == "cancelled"
    assert source.metadata_json["replacement"]["process_id"] == replacement.id
    assert source.metadata_json["cancellation"]["replacement_process_id"] == replacement.id
    assert replacement.creation_mode == "historical"
    assert replacement.status == "open"
    assert replacement.current_phase_code == "entrada"
    assert replacement.opened_at.date() == date(2026, 7, 14)
    assert replacement.received_at.date() == date(2026, 7, 14)
    assert replacement.initial_km == 52265
    assert replacement.metadata_json["workshop_flow_version"] == 2
    assert replacement.metadata_json["replaces"]["process_id"] == source.id

    replacement_entry = db_session.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == replacement.id,
            WorkshopPhasedProcessPhase.phase_code == "entrada",
        )
    )
    assert replacement_entry.data_json["historical_intervention_date"] == "2026-07-14"
    assert replacement_entry.data_json["entry_reasons"] == ["Pneus"]
    assert replacement_entry.data_json["replacement_source_process_id"] == source.id

    source_need = db_session.get(WorkshopMaterialNeed, need.id)
    replacement_need = db_session.scalar(
        select(WorkshopMaterialNeed).where(WorkshopMaterialNeed.process_id == replacement.id)
    )
    assert source_need.stock_status == "transferred"
    assert replacement_need.stock_status == "applied"
    assert replacement_need.requested_quantity == "2"
    assert replacement_need.detail_json["movement_id"] == movement.id
    assert (
        replacement_need.detail_json["stock_attribution_transfer"]["source_material_need_id"]
        == source_need.id
    )
    assert (
        source_need.detail_json["stock_attribution_transfer"]["target_material_need_id"]
        == replacement_need.id
    )

    assert db_session.scalar(select(func.count(StockMovement.id))) == movement_count_before
    assert stock_balances(db_session)[(article.id, location.id)] == balance_before
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "workshop_phased_process",
            AuditLog.entity_id == str(source.id),
            AuditLog.action == "workshop.process.replaced",
        )
    )
    assert db_session.scalar(
        select(AuditLog).where(
            AuditLog.entity_type == "workshop_material_need",
            AuditLog.entity_id == str(replacement_need.id),
            AuditLog.action == "workshop.material_need.transferred",
        )
    )

    repeated = authenticated_client.post(
        f"/v2-clean/workshop/{source.id}/replace",
        data={"observation": "Repetição", "task_action": "keep"},
        follow_redirects=False,
    )
    assert repeated.status_code == 303
    assert f"process_id={replacement.id}" in repeated.headers["location"]
    assert db_session.scalar(select(func.count(WorkshopPhasedProcess.id))) == 2
    assert db_session.scalar(select(func.count(StockMovement.id))) == movement_count_before

    blocked_reopen = authenticated_client.post(
        f"/v2-clean/workshop/{source.id}/reopen",
        data={"justification": "Tentar reabrir o processo substituído."},
        follow_redirects=False,
    )
    assert blocked_reopen.status_code == 303
    assert "admin_error=replacement_active" in blocked_reopen.headers["location"]
    db_session.expire_all()
    assert db_session.get(WorkshopPhasedProcess, source.id).status == "cancelled"

    source_page = authenticated_client.get(f"/v2-clean/workshop/reparacao?process_id={source.id}")
    assert source_page.status_code == 200
    assert "Processo arquivado após substituição" in source_page.text
    assert f"/v2-clean/workshop/{source.id}/reopen" not in source_page.text


def test_replacement_rolls_back_when_applied_material_has_no_stock_movement(
    authenticated_client, db_session
):
    process, need, _article, _location, _movement = _source_process_with_applied_tyres(db_session)
    need.detail_json = {"article_id": need.detail_json["article_id"]}
    db_session.commit()

    response = authenticated_client.post(
        f"/v2-clean/workshop/{process.id}/replace",
        data={"observation": "Tentar migração inválida", "task_action": "keep"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "admin_error=replacement_failed" in response.headers["location"]
    db_session.expire_all()
    assert db_session.get(WorkshopPhasedProcess, process.id).status == "open"
    assert db_session.get(WorkshopMaterialNeed, need.id).stock_status == "applied"
    assert db_session.scalar(select(func.count(WorkshopPhasedProcess.id))) == 1
