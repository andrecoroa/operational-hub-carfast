from __future__ import annotations

from pathlib import Path
from typing import Any

from app.services.spreadsheets import iter_xlsx_rows


RENTWAY_IMPORT_KINDS = {
    "fleet": "Atualização da frota",
    "work_orders": "Folhas de obra",
    "work_order_details": "Detalhes das folhas de obra",
    "contracts": "Contratos",
    "impros": "Impros",
}


def preview_structured_spreadsheet(
    path: str | Path,
    *,
    import_kind: str,
    sample_limit: int = 25,
) -> dict[str, Any]:
    """Return a bounded, serializable preview without changing the database."""

    if import_kind not in RENTWAY_IMPORT_KINDS:
        raise ValueError("Tipo de importação Rentway inválido.")
    rows: list[dict[str, Any]] = []
    total_rows = 0
    sheet_name = ""
    headers: list[str] = []
    for current_sheet, current_headers, row_number, _row, raw in iter_xlsx_rows(
        Path(path)
    ):
        sheet_name = current_sheet
        headers = current_headers
        total_rows += 1
        if len(rows) < sample_limit:
            rows.append(
                {
                    "row_number": row_number,
                    "values": {
                        str(key): "" if value is None else str(value)
                        for key, value in raw.items()
                    },
                }
            )
    return {
        "import_kind": import_kind,
        "import_label": RENTWAY_IMPORT_KINDS[import_kind],
        "sheet_name": sheet_name,
        "headers": headers,
        "total_rows": total_rows,
        "rows": rows,
        "preview_truncated": total_rows > len(rows),
    }
