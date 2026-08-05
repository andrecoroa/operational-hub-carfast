"""Add normalized Rentway gearbox to vehicles.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b5c6d7e8f9a0"
down_revision: str | Sequence[str] | None = "a4b5c6d7e8f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _key(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return "".join(ch for ch in text if ch.isalnum() and not unicodedata.combining(ch))


def _value(data: dict[str, Any], *candidates: str) -> str | None:
    wanted = {_key(candidate) for candidate in candidates}
    for key, value in data.items():
        if _key(key) in wanted and str(value or "").strip():
            return str(value).strip()
    return None


def _payload(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _gearbox(data: dict[str, Any], version: str | None) -> str | None:
    direct = _value(
        data, "Gearbox", "Gear Box", "Transmission", "Transmission Type",
        "Caixa", "Caixa de velocidades", "Tipo de caixa",
    )
    if direct:
        return direct
    match = re.search(
        r"\b(CVM\s*\d+|BVM\s*\d+|EAT\s*\d+|DSG\s*\d*|DCT\s*\d*|CVT|"
        r"AUTOM[AÁ]TIC[AO]?|AUTOMATIC|MANUAL)\b",
        str(version or ""),
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", "", match.group(1)).upper() if match else None


def upgrade() -> None:
    op.add_column("vehicles", sa.Column("rentway_gearbox", sa.String(length=80), nullable=True))
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT s.vehicle_id, s.data_json, v.version "
            "FROM vehicle_external_snapshots s JOIN vehicles v ON v.id=s.vehicle_id "
            "WHERE s.source_system='rentway'"
        )
    ).mappings()
    update = sa.text("UPDATE vehicles SET rentway_gearbox=:gearbox WHERE id=:vehicle_id")
    for row in rows:
        connection.execute(
            update,
            {"vehicle_id": row["vehicle_id"], "gearbox": _gearbox(_payload(row["data_json"]), row["version"])},
        )


def downgrade() -> None:
    op.drop_column("vehicles", "rentway_gearbox")
