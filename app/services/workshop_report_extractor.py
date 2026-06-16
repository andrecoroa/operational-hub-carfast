from __future__ import annotations

import re
import tempfile
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.services.workshop_templates import STELLANTIS_REPORTS


FIELD_ALIASES: dict[str, list[str]] = {
    "engine_speed": ["Regime motor"],
    "oil_temperature": ["Temperatura oleo", "Temperatura óleo"],
    "oil_pressure_reference": ["Pressao oleo referencia", "Pressão óleo referência"],
    "oil_pressure_current": ["Pressao oleo atual", "Pressão óleo atual"],
    "oil_pressure_regulation_opening": ["Abertura regulacao pressao oleo", "Abertura regulação pressão óleo"],
    "oil_dilution_rate": ["Diluicao estimada do oleo", "Diluição estimada do óleo", "Taxa de diluicao"],
    "oil_carbon_rate": ["Carbono estimado no oleo", "Carbono estimado no óleo"],
    "anti_dilution_protection": ["Protecao anti-diluicao", "Proteção anti-diluição"],
    "calculated_interval": ["Intervalo calculado por perfil"],
    "km_last_maintenance_reset": ["Km ultima reposicao manutencao", "Km última reposição manutenção"],
    "km_before_next_maintenance": ["Km antes proxima manutencao", "Km antes próxima manutenção"],
    "days_before_next_maintenance": ["Dias restantes antes manutencao", "Dias restantes antes manutenção"],
    "time_limit_exceeded": ["Limite temporal ultrapassado"],
    "km_limit_exceeded": ["Limite quilometrico ultrapassado", "Limite quilométrico ultrapassado"],
    "oil_change_limit_exceeded": [
        "Limite manutencao excedido sem substituir oleo motor",
        "Limite manutenção excedido sem substituir óleo motor",
    ],
    "maintenance_key_display": ["Chave de manutencao", "Chave de manutenção"],
    "days_since_last_reset": ["Dias desde ultima reposicao", "Dias desde última reposição"],
    "maintenance_count": ["N. manutencoes efetuadas", "Nº manutenções efetuadas", "N. manutenções efetuadas"],
    "maintenance_threshold": ["Limiar manutencao", "Limiar manutenção"],
    "total_duration_before_maintenance": ["Duracao total antes manutencao", "Duração total antes manutenção"],
    "first_maintenance_start": ["Inicio da primeira manutencao", "Início da primeira manutenção"],
    "duration_before_first_maintenance": ["Duracao antes primeira manutencao", "Duração antes primeira manutenção"],
    "engine_managed_maintenance_type": ["Tipo de manutencao gerida pela motorizacao", "Tipo de manutenção gerida pela motorização"],
    "software_reference": ["Referencia do software", "Referência do software"],
    "remote_download_date": ["Data de telecarregamento"],
    "remote_download_count": ["Numero de telecarregamentos", "Número de telecarregamentos"],
}


def extract_workshop_report_values(source: str, report_code: str) -> dict[str, Any]:
    path, cleanup = _materialize_source(source)
    try:
        text = _extract_pdf_text(path)
    finally:
        if cleanup:
            path.unlink(missing_ok=True)
    return _extract_values_from_text(text, report_code)


def extract_workshop_report_values_from_bytes(
    content: bytes,
    report_code: str,
    filename: str | None = None,
) -> dict[str, Any]:
    text = _extract_pdf_text_from_bytes(content, filename or "relatorio.pdf")
    return _extract_values_from_text(text, report_code)


def _extract_values_from_text(text: str, report_code: str) -> dict[str, Any]:
    lines = [_normalize(line) for line in text.splitlines() if _normalize(line)]
    values: dict[str, Any] = {}
    for field in _fields_for_report(report_code):
        value = _extract_field(lines, field["code"], field["label"])
        if value:
            values[field["code"]] = value
    values.update(_extract_psa_values(lines, report_code))
    return values


def _extract_psa_values(lines: list[str], report_code: str) -> dict[str, Any]:
    if report_code == "engine_lubrication":
        return _extract_psa_engine_lubrication(lines)
    if report_code == "maintenance_information":
        return _extract_psa_maintenance_information(lines)
    if report_code == "maintenance_programming":
        return _extract_psa_maintenance_programming(lines)
    if report_code == "fault_reading":
        return _extract_psa_fault_reading(lines)
    return {}


def _extract_psa_engine_lubrication(lines: list[str]) -> dict[str, Any]:
    pressure_indices = _find_indices(lines, lambda line: _simplify(line) == "pressao de oleo")
    current_pressure = ""
    if len(pressure_indices) > 1:
        current_pressure = _next_number_from(lines, pressure_indices[-1], stop_after=4)
    elif pressure_indices:
        current_pressure = _next_number_from(lines, pressure_indices[0], stop_after=4)

    protection_idx = _find_index(lines, lambda line: "estado da protecao" in _simplify(line))
    protection = ""
    if protection_idx >= 0:
        for line in lines[protection_idx : protection_idx + 8]:
            simple = _simplify(line)
            if "protecao" in simple and ("ativa" in simple or "inativa" in simple):
                protection = _clean_value(line)
                break

    return _clean_empty(
        {
            "engine_speed": _value_after_anchor(lines, "regime motor", exact=True),
            "oil_temperature": _value_after_anchor(lines, "temperatura", require_any=("leo", "oleo")),
            "oil_pressure_reference": _value_after_anchor(lines, "valor de referencia", stop_after=6),
            "oil_pressure_current": current_pressure,
            "oil_pressure_regulation_opening": _value_after_anchor(lines, "relacao ciclica", stop_after=8),
            "oil_dilution_rate": _value_after_anchor(lines, "taxa de diluicao", stop_after=8),
            "oil_carbon_rate": _value_after_anchor(lines, "taxa de carbono", stop_after=8),
            "anti_dilution_protection": protection,
            "calculated_interval": _value_after_anchor(lines, "intervalo de", stop_after=12),
        }
    )


def _extract_psa_maintenance_information(lines: list[str]) -> dict[str, Any]:
    km_before_idx = _find_index(
        lines,
        lambda line, idx: _simplify(line) == "numero de"
        and _window_contains(lines, idx, ("quilometros antes", "manutencao"), stop_after=5),
        with_index=True,
    )
    days_before_idx = _find_index(
        lines,
        lambda line, idx: "numero de dias" in _simplify(line)
        and _window_contains(lines, idx, ("restantes antes", "manutencao"), stop_after=5),
        with_index=True,
    )
    time_limit_idx = _find_index(
        lines,
        lambda _line, idx: _window_contains(lines, idx, ("limite de manutencao", "temporal"), stop_after=4),
        with_index=True,
    )
    km_limit_idx = _find_index(
        lines,
        lambda _line, idx: _window_contains(lines, idx, ("limite de manutencao", "quilometrico"), stop_after=5),
        with_index=True,
    )
    maintenance_key_idx = _find_index(lines, lambda line: "visualizacao da chave" in _simplify(line))
    days_since_idx = _find_index(
        lines,
        lambda line, idx: "numero de dias a" in _simplify(line)
        and _window_contains(lines, idx, ("ultima", "reposicao"), stop_after=8),
        with_index=True,
    )
    count_idx = _find_index(
        lines,
        lambda line, idx: _simplify(line) == "numero de"
        and _window_contains(lines, idx, ("manutencoes", "efetuadas"), stop_after=5),
        with_index=True,
    )
    oil_change_limit_idx = _find_index(
        lines,
        lambda _line, idx: _window_contains(
            lines,
            idx,
            ("limite de manutencao", "sem substituir", "oleo do motor"),
            stop_after=8,
        ),
        with_index=True,
    )

    return _clean_empty(
        {
            "km_last_maintenance_reset": _value_after_anchor(lines, "quilometragem do", stop_after=8),
            "km_before_next_maintenance": _next_number_from(lines, km_before_idx, stop_after=6) if km_before_idx >= 0 else "",
            "days_before_next_maintenance": _next_number_from(lines, days_before_idx, stop_after=6) if days_before_idx >= 0 else "",
            "time_limit_exceeded": _yes_no_from(lines, time_limit_idx, stop_after=5) if time_limit_idx >= 0 else "",
            "km_limit_exceeded": _yes_no_from(lines, km_limit_idx, stop_after=6) if km_limit_idx >= 0 else "",
            "maintenance_key_display": _maintenance_key_text(lines, maintenance_key_idx),
            "days_since_last_reset": _next_number_from(lines, days_since_idx, stop_after=10) if days_since_idx >= 0 else "",
            "maintenance_count": _next_number_from(lines, count_idx, stop_after=5) if count_idx >= 0 else "",
            "oil_change_limit_exceeded": _yes_no_from(lines, oil_change_limit_idx, stop_after=10) if oil_change_limit_idx >= 0 else "",
        }
    )


def _extract_psa_maintenance_programming(lines: list[str]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for line in lines:
        simple = _simplify(line)
        if "limiar manutencao" in simple:
            values["maintenance_threshold"] = _after_colon_or_number(line)
        elif "duracao total antes da manutencao" in simple:
            values["total_duration_before_maintenance"] = _after_colon_or_number(line)
        elif "inicio da primeira manutencao" in simple:
            values["first_maintenance_start"] = _after_colon_or_number(line)
        elif "duracao antes da primeira manutencao" in simple:
            values["duration_before_first_maintenance"] = _after_colon_or_number(line)
        elif "selecao da manutencao gerida pela motorizacao" in simple:
            values["engine_managed_maintenance_type"] = _after_colon_or_number(line)
    return _clean_empty(values)


def _extract_psa_fault_reading(lines: list[str]) -> dict[str, Any]:
    faults: list[str] = []
    for idx, line in enumerate(lines):
        if not re.fullmatch(r"[A-Z][A-Z0-9]{4}\s+[0-9A-F]{2}", line.strip(), flags=re.I):
            continue
        description_parts: list[str] = []
        for next_line in lines[idx + 1 : idx + 6]:
            simple = _simplify(next_line)
            if simple in {"propriedades", "origem", "estatuto", "caracterizacao"}:
                break
            if re.fullmatch(r"[A-Z][A-Z0-9]{4}\s+[0-9A-F]{2}", next_line.strip(), flags=re.I):
                break
            description_parts.append(next_line)
        faults.append(f"{line.strip()} - {' '.join(description_parts).strip()}".strip(" -"))
    return {
        "faults_found": "Sim" if faults else "Não",
        "faults": " | ".join(faults),
    } if faults else {}


def _fields_for_report(report_code: str) -> list[dict[str, Any]]:
    for report in STELLANTIS_REPORTS:
        if report["code"] == report_code:
            return list(report.get("fields") or [])
    return []


def _materialize_source(source: str) -> tuple[Path, bool]:
    clean = (source or "").strip().strip('"')
    if not clean:
        raise ValueError("Indica primeiro o link ou caminho do relatório.")
    parsed = urlparse(clean)
    if parsed.scheme in {"http", "https"}:
        suffix = Path(parsed.path).suffix or ".pdf"
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        target = Path(handle.name)
        handle.close()
        request = urllib.request.Request(clean, headers={"User-Agent": "CarFast-v2-report-extractor"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                target.write_bytes(response.read())
        except Exception as exc:  # noqa: BLE001
            target.unlink(missing_ok=True)
            raise ValueError("Não foi possível descarregar o PDF. Usa um link direto, caminho local acessível ao servidor ou classifica o documento manualmente.") from exc
        return target, True
    path = Path(clean)
    if not path.exists():
        raise ValueError("O caminho indicado não existe no servidor.")
    return path, False


def _extract_pdf_text(path: Path) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("PyMuPDF não está instalado. Adiciona a dependência PyMuPDF para ativar a extração.") from exc
    if path.suffix.lower() != ".pdf":
        raise ValueError("A extração automática só está preparada para ficheiros PDF.")
    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("O PDF não devolveu texto. Pode ser imagem/scanner e precisar de OCR.")
    return text


def _extract_pdf_text_from_bytes(content: bytes, filename: str) -> str:
    try:
        import fitz  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("PyMuPDF não está instalado. Adiciona a dependência PyMuPDF para ativar a extração.") from exc
    if not filename.lower().endswith(".pdf"):
        raise ValueError("A extração automática só está preparada para ficheiros PDF.")
    if not content:
        raise ValueError("O ficheiro PDF está vazio.")
    parts: list[str] = []
    with fitz.open(stream=content, filetype="pdf") as doc:
        for page in doc:
            parts.append(page.get_text("text"))
    text = "\n".join(parts)
    if not text.strip():
        raise ValueError("O PDF não devolveu texto. Pode ser imagem/scanner e precisar de OCR.")
    return text


def _normalize(text: str) -> str:
    return " ".join(str(text).replace("\x00", " ").split())


def _extract_field(lines: list[str], code: str, label: str) -> str:
    aliases = [label, *FIELD_ALIASES.get(code, [])]
    for alias in aliases:
        value = _extract_by_alias(lines, alias)
        if value:
            return value
    return ""


def _extract_by_alias(lines: list[str], alias: str) -> str:
    alias_low = _simplify(alias)
    for idx, line in enumerate(lines):
        simple = _simplify(line)
        if simple == alias_low and idx + 1 < len(lines):
            return _clean_value(lines[idx + 1])
        if simple.startswith(alias_low + " "):
            return _clean_value(line[len(alias) :].strip(" :\t"))
        if alias_low in simple and ":" in line:
            after = line.split(":", 1)[1].strip()
            if after:
                return _clean_value(after)
    return ""


def _simplify(value: str) -> str:
    value = value.lower()
    replacements = str.maketrans("áàãâäéèêëíìîïóòõôöúùûüçºª", "aaaaaeeeeiiiiooooouuuucao")
    value = value.translate(replacements)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _clean_value(value: str) -> str:
    return _normalize(value).strip(" :;\t")


def _clean_empty(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, "")}


def _find_index(lines: list[str], predicate: Any, *, with_index: bool = False) -> int:
    for idx, line in enumerate(lines):
        if with_index:
            if predicate(line, idx):
                return idx
        elif predicate(line):
            return idx
    return -1


def _find_indices(lines: list[str], predicate: Any) -> list[int]:
    return [idx for idx, line in enumerate(lines) if predicate(line)]


def _window_contains(lines: list[str], start: int, parts: tuple[str, ...], stop_after: int = 8) -> bool:
    simple = " ".join(_simplify(line) for line in lines[start : start + stop_after])
    return all(_simplify(part) in simple for part in parts)


def _next_number_from(lines: list[str], start: int, stop_after: int = 8) -> str:
    if start < 0:
        return ""
    for line in lines[start : start + stop_after]:
        number = _number_in_text(line)
        if number:
            return number
    return ""


def _value_after_anchor(
    lines: list[str],
    anchor: str,
    *,
    exact: bool = False,
    require_any: tuple[str, ...] = (),
    stop_after: int = 8,
) -> str:
    anchor_simple = _simplify(anchor)
    required = tuple(_simplify(item) for item in require_any)
    for idx, line in enumerate(lines):
        simple = _simplify(line)
        if exact and simple != anchor_simple:
            continue
        if not exact and anchor_simple not in simple:
            continue
        if required and not any(item in simple for item in required):
            continue
        return _next_number_from(lines, idx, stop_after=stop_after)
    return ""


def _yes_no_from(lines: list[str], start: int, stop_after: int = 6) -> str:
    if start < 0:
        return ""
    simple = " ".join(_simplify(line) for line in lines[start : start + stop_after])
    if "nao" in simple:
        return "Não"
    if "sim" in simple:
        return "Sim"
    return ""


def _maintenance_key_text(lines: list[str], start: int) -> str:
    if start < 0:
        return ""
    ignored = {
        "visualizacao da chave",
        "de manutencao",
        "valor",
        "unidade",
        "descricao",
        "ajuda",
    }
    for line in lines[start : start + 8]:
        simple = _simplify(line)
        if not simple or simple in ignored:
            continue
        if "estado" in simple and ("apagado" in simple or "fixo" in simple):
            return _clean_value(line)
    return ""


def _line_window(lines: list[str], needle: str, stop_after: int = 8) -> list[str]:
    needle_simple = _simplify(needle)
    simplified = [_simplify(line) for line in lines]
    joined = ""
    start = -1
    for idx, simple in enumerate(simplified):
        joined = " ".join(simplified[idx : idx + stop_after])
        if needle_simple in joined:
            start = idx
            break
    if start < 0:
        return []
    return lines[start : start + stop_after]


def _number_in_text(value: str) -> str:
    match = re.search(r"-?\d[\d\s]*(?:[,.]\d+)?", value)
    return _clean_value(match.group(0)) if match else ""


def _next_numeric_after(lines: list[str], needle: str, stop_after: int = 8) -> str:
    for line in _line_window(lines, needle, stop_after):
        number = _number_in_text(line)
        if number:
            return number
    return ""


def _number_on_or_after(lines: list[str], needle: str, stop_after: int = 4) -> str:
    return _next_numeric_after(lines, needle, stop_after)


def _next_numeric_after_exact(lines: list[str], needle: str, stop_after: int = 4) -> str:
    needle_simple = _simplify(needle)
    for idx, line in enumerate(lines):
        if _simplify(line) != needle_simple:
            continue
        for next_line in lines[idx + 1 : idx + stop_after]:
            number = _number_in_text(next_line)
            if number:
                return number
    return ""


def _next_text_after(lines: list[str], needle: str, stop_after: int = 8) -> str:
    window = _line_window(lines, needle, stop_after)
    found = False
    for line in window:
        simple = _simplify(line)
        if not found:
            found = _simplify(needle) in " ".join(_simplify(item) for item in window[: window.index(line) + 1])
            continue
        if _number_in_text(line):
            continue
        if simple in {"ajuda", "descricao", "valor", "unidade"}:
            continue
        if simple and not any(word in simple for word in {"estado", "protecao", "anti diluicao", "oleo", "motor", "visualizacao", "chave", "manutencao"}):
            return _clean_value(line)
        if "protecao" in simple and "inativa" in simple:
            return _clean_value(line)
        if "estado" in simple and ("apagado" in simple or "fixo" in simple):
            return _clean_value(line)
    return ""


def _yes_no_on_or_after(lines: list[str], needle: str, stop_after: int = 6) -> str:
    text = " ".join(_line_window(lines, needle, stop_after))
    simple = _simplify(text)
    if "nao" in simple:
        return "Não"
    if "sim" in simple:
        return "Sim"
    return ""


def _after_colon_or_number(line: str) -> str:
    if ":" in line:
        return _clean_value(line.split(":", 1)[1])
    return _number_in_text(line)
