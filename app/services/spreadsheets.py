from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
import unicodedata

from openpyxl import load_workbook


def normalize_header(name: Any) -> str:
    text = unicodedata.normalize("NFKD", str(name or "").lower())
    return "".join(ch for ch in text if ch.isalnum() and not unicodedata.combining(ch))


def build_column_lookup(headers: list[str]) -> dict[str, int]:
    lookup: dict[str, int] = {}
    for idx, name in enumerate(headers):
        lookup[name] = idx
        lookup[normalize_header(name)] = idx
    return lookup


def row_value(row: tuple[Any, ...], col: dict[str, int], name: str) -> Any:
    idx = col.get(name)
    return row[idx] if idx is not None and idx < len(row) else None


def first_row_value(row: tuple[Any, ...], col: dict[str, int], candidates: list[str]) -> Any:
    for name in candidates:
        value = row_value(row, col, name)
        if value not in (None, ""):
            return value
        value = row_value(row, col, normalize_header(name))
        if value not in (None, ""):
            return value
    return None


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def clean_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def excel_date_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, (int, float)):
        try:
            return (datetime(1899, 12, 30) + timedelta(days=float(value))).date().isoformat()
        except (TypeError, ValueError, OverflowError):
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return text


def iter_xlsx_rows(path: str | Path, preferred_sheet: str | None = None):
    wb = load_workbook(path, data_only=True, read_only=True)
    try:
        ws = wb[preferred_sheet] if preferred_sheet and preferred_sheet in wb.sheetnames else wb[wb.sheetnames[0]]
        headers = [str(cell.value).strip() if cell.value is not None else "" for cell in ws[1]]
        for row_number, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            raw = {
                headers[idx] or f"coluna_{idx + 1}": value
                for idx, value in enumerate(row)
                if idx < len(headers)
            }
            yield ws.title, headers, row_number, row, raw
    finally:
        wb.close()
