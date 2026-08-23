"""Optional Workshop adapter. Stock core never imports this module."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.vehicles import Vehicle
from app.models.workshop_phased import WorkshopMaterialNeed, WorkshopPhasedProcess


def material_request_rows(db: Session, scope: str) -> list[tuple[object, object, object]]:
    statement = (
        select(WorkshopMaterialNeed, WorkshopPhasedProcess, Vehicle)
        .join(WorkshopPhasedProcess, WorkshopPhasedProcess.id == WorkshopMaterialNeed.process_id)
        .outerjoin(Vehicle, Vehicle.id == WorkshopMaterialNeed.vehicle_id)
        .where(WorkshopMaterialNeed.stock_request_reference.is_not(None))
    )
    if scope == "pending":
        statement = statement.where(
            WorkshopMaterialNeed.stock_status.in_(("requested", "usage_reported"))
        )
    elif scope == "completed":
        statement = statement.where(WorkshopMaterialNeed.stock_status.in_(("delivered", "applied")))
    return list(
        db.execute(statement.order_by(WorkshopMaterialNeed.created_at, WorkshopMaterialNeed.id))
    )


def lock_material_needs(db: Session, request_reference: str) -> list[object]:
    return list(
        db.scalars(
            select(WorkshopMaterialNeed)
            .where(WorkshopMaterialNeed.stock_request_reference == request_reference)
            .with_for_update()
        )
    )


def record_fulfilment(
    need: object,
    *,
    article_id: int,
    movement_id: int,
    location_id: int,
    unit_cost: str,
    total_cost: str,
    user_id: int | None,
) -> None:
    direct_usage = (need.detail_json or {}).get("request_mode") == "direct_usage"
    need.stock_status = "applied" if direct_usage else "delivered"
    if direct_usage:
        need.applied_confirmed_by_id = user_id
        need.applied_confirmed_at = datetime.now(UTC)
    detail = dict(need.detail_json or {})
    detail.update(
        {
            "article_id": article_id,
            "movement_id": movement_id,
            "stock_location_id": location_id,
            "unit_cost": unit_cost,
            "total_cost": total_cost,
        }
    )
    need.detail_json = detail
