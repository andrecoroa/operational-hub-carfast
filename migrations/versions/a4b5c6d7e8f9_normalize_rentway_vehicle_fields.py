"""Normalize filterable Rentway vehicle fields.

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a4b5c6d7e8f9"
down_revision: str | Sequence[str] | None = "f3a4b5c6d7e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEXED_COLUMNS = (
    "rentway_category",
    "rentway_group",
    "rentway_fuel",
    "rentway_status",
    "rentway_client",
    "rentway_return_date",
    "rentway_ipo_date",
    "rentway_registration_date",
    "rentway_location",
)


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in text if ch.isalnum() and not unicodedata.combining(ch))


def _value(data: dict[str, Any], *candidates: str) -> Any:
    normalized = {_key(candidate) for candidate in candidates}
    for key, value in data.items():
        if _key(key) in normalized and value not in (None, ""):
            return value
    return None


def _text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _integer(value: Any, *, positive: bool = False) -> int | None:
    try:
        parsed = int(float(str(value).replace(" ", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return parsed if not positive or parsed > 0 else None


def _date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
        except (ValueError, OverflowError):
            return None
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            pass
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", text)
    return date.fromisoformat(match.group(1)) if match else None


def _category(value: Any) -> str | None:
    normalized = str(value or "").casefold()
    if any(token in normalized for token in ("comerc", "commercial", "cargo", "van", "furg")):
        return "Comerciais"
    if any(token in normalized for token in ("ligeir", "passage", "passenger", "car")):
        return "Ligeiros"
    return None


def _snapshot_payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("rentway_category", sa.String(length=40), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_group", sa.String(length=80), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_fuel", sa.String(length=80), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_seats", sa.Integer(), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_colour", sa.String(length=120), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_status", sa.String(length=120), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_client", sa.String(length=200), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_return_date", sa.Date(), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_ipo_date", sa.Date(), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_registration_date", sa.Date(), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_km", sa.Integer(), nullable=True))
    op.add_column("vehicles", sa.Column("rentway_location", sa.String(length=160), nullable=True))
    for column in INDEXED_COLUMNS:
        op.create_index(f"ix_vehicles_{column}", "vehicles", [column], unique=False)

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT vehicle_id, data_json FROM vehicle_external_snapshots "
            "WHERE source_system = 'rentway'"
        )
    ).mappings()
    update = sa.text(
        "UPDATE vehicles SET rentway_category=:category, rentway_group=:group_value, "
        "rentway_fuel=:fuel, rentway_seats=:seats, rentway_colour=:colour, "
        "rentway_status=:status, rentway_client=:client, rentway_return_date=:return_date, "
        "rentway_ipo_date=:ipo_date, rentway_registration_date=:registration_date, "
        "rentway_km=:km, rentway_location=:location WHERE id=:vehicle_id"
    )
    for row in rows:
        data = _snapshot_payload(row["data_json"])
        connection.execute(
            update,
            {
                "vehicle_id": row["vehicle_id"],
                "category": _category(_value(data, "Category", "VehicleCategory", "Categoria", "VehicleType")),
                "group_value": _text(_value(data, "GroupId", "Group ID", "RentwayGroup", "Grupo Rentway", "Grupo")),
                "fuel": _text(_value(data, "Fuel", "FuelType", "Combustível", "Combustivel")),
                "seats": _integer(_value(data, "Seats", "SeatCount", "NumberOfSeats", "Lugares", "Nº Lugares"), positive=True),
                "colour": _text(_value(data, "Colour", "Color", "Cor")),
                "status": _text(_value(data, "CurrentStatus", "Current Status", "Estado Rentway", "Estado atual")),
                "client": _text(_value(data, "Client", "ClientName", "Customer", "CustomerName", "Cliente", "Cliente atual")),
                "return_date": _date(_value(data, "ReturnDate", "ExpectedReturnDate", "Data prevista de devolução", "Data devolução")),
                "ipo_date": _date(_value(data, "InspectionDate", "NextInspectionDate", "IPODate", "Data IPO", "Próxima IPO")),
                "registration_date": _date(_value(data, "PlateDate", "RegistrationDate", "Data matrícula", "Data de matrícula")),
                "km": _integer(_value(data, "Kms", "KM", "Odometer", "CurrentKm", "Quilómetros")),
                "location": _text(_value(data, "RentalStation", "Station", "Location", "Estação", "Localização")),
            },
        )


def downgrade() -> None:
    for column in reversed(INDEXED_COLUMNS):
        op.drop_index(f"ix_vehicles_{column}", table_name="vehicles")
    for column in (
        "rentway_location",
        "rentway_km",
        "rentway_registration_date",
        "rentway_ipo_date",
        "rentway_return_date",
        "rentway_client",
        "rentway_status",
        "rentway_colour",
        "rentway_seats",
        "rentway_fuel",
        "rentway_group",
        "rentway_category",
    ):
        op.drop_column("vehicles", column)
