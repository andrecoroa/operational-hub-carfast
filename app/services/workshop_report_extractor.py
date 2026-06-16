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
    lines = [_normalize(line) for line in text.splitlines() if _normalize(line)]
    values: dict[str, Any] = {}
    for field in _fields_for_report(report_code):
        value = _extract_field(lines, field["code"], field["label"])
        if value:
            values[field["code"]] = value
    return values


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
