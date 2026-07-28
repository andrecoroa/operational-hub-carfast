from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import io
import logging
import os
import re
import shutil
import subprocess
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import DiagnosticDocument, DiagnosticExtraction, Document
from app.services.diagnostic_documents import (
    classify_diagnostic_type,
    ensure_diagnostic_profile,
    normalize_vin,
)

logging.getLogger("pdfminer").setLevel(logging.ERROR)

EXTRACTOR_NAME = "carfast_diagnostic_pdf"
EXTRACTOR_VERSION = "1.0.0"
PARSER_VERSION = "1.1.0"

_FILENAME_PATTERN = re.compile(
    r"^(?P<machine>[AS])_(?P<family>[A-Z0-9]+)_"
    r"(?P<vin>[A-HJ-NPR-Z0-9]{17})_"
    r"(?:(?P<date>\d{6})(?:_(?P<time>\d{4}))?|sem_data)\.pdf$",
    re.IGNORECASE,
)
_DTC_PATTERN = re.compile(r"\b[BCPU]\d{4}(?:-\d{2})?\b", re.IGNORECASE)


def _plain_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value)
    return "".join(char for char in text if not unicodedata.combining(char)).lower()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_diagnostic_filename(filename: str) -> dict[str, str | None]:
    match = _FILENAME_PATTERN.match(Path(filename).name)
    if not match:
        return {
            "machine_prefix": None,
            "family": None,
            "vin": None,
            "capture_date": None,
            "capture_time": None,
        }
    values = {
        key: value.upper() if value else None
        for key, value in match.groupdict().items()
    }
    return {
        "machine_prefix": values["machine"],
        "family": values["family"],
        "vin": values["vin"],
        "capture_date": values["date"],
        "capture_time": values["time"],
    }


def parse_diagnostic_report_datetime(
    value: str | None,
    *,
    capture_date: str | None = None,
    capture_time: str | None = None,
) -> datetime | None:
    """Normalize the local timestamp printed by the diagnostic machine.

    Reports do not carry a reliable timezone, so this deliberately stores a
    timezone-naive local timestamp. The original string remains in the lossless
    extraction payload.
    """

    clean_value = " ".join((value or "").strip().split())
    if clean_value:
        patterns = (
            (
                r"\b(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)\b",
                ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"),
            ),
            (
                r"\b(\d{2}/\d{2}/\d{4})[ ,T]+(\d{2}:\d{2}(?::\d{2})?)\b",
                ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M"),
            ),
            (
                r"\b(\d{2}-\d{2}-\d{4})[ T](\d{2}:\d{2}(?::\d{2})?)\b",
                ("%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M"),
            ),
            (
                r"\b(\d{4}/\d{2}/\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)\b",
                ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"),
            ),
        )
        for pattern, formats in patterns:
            match = re.search(pattern, clean_value)
            if not match:
                continue
            candidate = f"{match.group(1)} {match.group(2)}"
            for date_format in formats:
                try:
                    return datetime.strptime(candidate, date_format)
                except ValueError:
                    continue

    if capture_date:
        compact_time = capture_time or "0000"
        try:
            return datetime.strptime(f"{capture_date}{compact_time}", "%y%m%d%H%M")
        except ValueError:
            return None
    return None


def detect_diagnostic_machine(filename: str, text: str) -> str:
    filename_data = parse_diagnostic_filename(filename)
    corpus = _plain_text(text)
    autel_score = sum(
        token in corpus
        for token in ("autel", "maxia", "maxidas", "maxisys", "numero do relatorio")
    )
    stellantis_score = sum(
        token in corpus
        for token in ("psa-diag", "diagbox", "teste global", "family\\", "utilizador :")
    )
    if autel_score > stellantis_score:
        return "autel"
    if stellantis_score > autel_score:
        return "stellantis_diagbox"
    if filename_data["machine_prefix"] == "A":
        return "autel"
    if filename_data["machine_prefix"] == "S":
        return "stellantis_diagbox"
    return "unknown"


def _word_payload(word: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"text": str(word.get("text", ""))}
    for key in ("x0", "x1", "top", "bottom", "doctop"):
        value = word.get(key)
        if isinstance(value, (int, float)):
            payload[key] = round(float(value), 3)
    return payload


def _native_quality(text: str) -> float:
    if not text.strip():
        return 0.0
    printable = sum(char.isprintable() or char in "\r\n\t" for char in text)
    alphanumeric = sum(char.isalnum() for char in text)
    printable_ratio = printable / max(len(text), 1)
    alphanumeric_ratio = alphanumeric / max(len(text), 1)
    length_score = min(len(text.strip()) / 400, 1.0)
    return round(
        (printable_ratio * 0.35) + (alphanumeric_ratio * 0.25) + (length_score * 0.4),
        4,
    )


def _find_executable(env_name: str, command: str, candidates: list[Path]) -> str | None:
    configured = os.getenv(env_name)
    if configured and Path(configured).is_file():
        return configured
    discovered = shutil.which(command)
    if discovered:
        return discovered
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return None


def _pdftoppm_command() -> str | None:
    return _find_executable(
        "CARFAST_PDFTOPPM",
        "pdftoppm",
        [
            Path(r"C:\Program Files\poppler\Library\bin\pdftoppm.exe"),
            Path(r"C:\Program Files\poppler\bin\pdftoppm.exe"),
        ],
    )


def _tesseract_command() -> str | None:
    return _find_executable(
        "CARFAST_TESSERACT",
        "tesseract",
        [Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")],
    )


@lru_cache(maxsize=8)
def _command_version(command: str, version_argument: str) -> str | None:
    try:
        result = subprocess.run(
            [command, version_argument],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (result.stdout or result.stderr).strip()
    return output.splitlines()[0] if output else None


def _ocr_page(
    pdf_path: Path,
    page_number: int,
    *,
    languages: str,
    dpi: int,
) -> tuple[dict[str, Any] | None, str | None]:
    pdftoppm = _pdftoppm_command()
    tesseract = _tesseract_command()
    if not pdftoppm or not tesseract:
        missing = []
        if not pdftoppm:
            missing.append("pdftoppm")
        if not tesseract:
            missing.append("tesseract")
        return None, f"OCR não executado: falta {', '.join(missing)}."

    with tempfile.TemporaryDirectory(prefix="carfast-diagnostic-") as temp_dir:
        output_root = Path(temp_dir) / f"page-{page_number}"
        render = subprocess.run(
            [
                pdftoppm,
                "-f",
                str(page_number),
                "-l",
                str(page_number),
                "-singlefile",
                "-r",
                str(dpi),
                "-png",
                str(pdf_path),
                str(output_root),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        image_path = output_root.with_suffix(".png")
        if render.returncode or not image_path.is_file():
            message = render.stderr.strip() or "falha desconhecida ao renderizar a página"
            return None, f"OCR não executado na página {page_number}: {message}"

        ocr = subprocess.run(
            [
                tesseract,
                str(image_path),
                "stdout",
                "-l",
                languages,
                "--psm",
                "6",
                "tsv",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        if ocr.returncode:
            message = ocr.stderr.strip() or "falha desconhecida no Tesseract"
            return None, f"OCR falhou na página {page_number}: {message}"

    words: list[dict[str, Any]] = []
    lines: dict[tuple[int, int, int], list[tuple[int, str]]] = defaultdict(list)
    confidences: list[float] = []
    for row in csv.DictReader(io.StringIO(ocr.stdout), delimiter="\t"):
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            confidence = float(row.get("conf", "-1"))
            left = int(row.get("left", "0"))
            top = int(row.get("top", "0"))
            width = int(row.get("width", "0"))
            height = int(row.get("height", "0"))
            line_key = (
                int(row.get("block_num", "0")),
                int(row.get("par_num", "0")),
                int(row.get("line_num", "0")),
            )
            word_number = int(row.get("word_num", "0"))
        except (TypeError, ValueError):
            continue
        if confidence >= 0:
            confidences.append(confidence)
        words.append(
            {
                "text": text,
                "confidence": confidence,
                "left": left,
                "top": top,
                "width": width,
                "height": height,
            }
        )
        lines[line_key].append((word_number, text))
    text = "\n".join(
        " ".join(item[1] for item in sorted(line_words))
        for _, line_words in sorted(lines.items())
    )
    return (
        {
            "renderer": "pdftoppm",
            "renderer_version": _command_version(pdftoppm, "-v"),
            "engine": "tesseract",
            "engine_version": _command_version(tesseract, "--version"),
            "languages": languages,
            "dpi": dpi,
            "mean_confidence": (
                round(sum(confidences) / len(confidences), 3) if confidences else None
            ),
            "text": text,
            "words": words,
        },
        None,
    )


def _table_header_positions(
    words: list[dict[str, Any]],
    labels: tuple[str, ...],
) -> dict[str, dict[str, Any]] | None:
    normalized_labels = {_plain_text(label): label for label in labels}
    for anchor in words:
        anchor_text = _plain_text(str(anchor.get("text", "")))
        if anchor_text not in normalized_labels:
            continue
        anchor_top = float(anchor["top"])
        row = {
            _plain_text(str(word.get("text", ""))): word
            for word in words
            if abs(float(word["top"]) - anchor_top) <= 2.5
        }
        if all(_plain_text(label) in row for label in labels):
            return {label: row[_plain_text(label)] for label in labels}
    return None


def _join_words(words: list[dict[str, Any]]) -> str:
    return " ".join(
        str(word["text"])
        for word in sorted(words, key=lambda item: (float(item["top"]), float(item["x0"])))
    ).strip()


def _autel_observations(page: dict[str, Any]) -> list[dict[str, Any]]:
    words = page.get("words") or []
    headers = _table_header_positions(words, ("NO.", "Nome", "Valor", "Unidade"))
    if not headers:
        return []
    number_header = headers["NO."]
    name_header = headers["Nome"]
    value_header = headers["Valor"]
    unit_header = headers["Unidade"]

    header_top = float(value_header["top"])
    number_x = float(number_header["x0"])
    name_x = float(name_header["x0"])
    value_x = float(value_header["x0"])
    unit_x = float(unit_header["x0"])
    anchors = [
        word
        for word in words
        if float(word["top"]) > header_top + 3
        and abs(float(word["x0"]) - number_x) < 15
        and str(word["text"]).isdigit()
    ]
    anchors.sort(key=lambda word: float(word["top"]))
    observations: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        anchor_top = float(anchor["top"])
        lower = (
            header_top
            if index == 0
            else (float(anchors[index - 1]["top"]) + anchor_top) / 2
        )
        if index + 1 == len(anchors):
            previous_gap = (
                anchor_top - float(anchors[index - 1]["top"]) if index else 40.0
            )
            upper = anchor_top + max(previous_gap / 2, 20.0)
        else:
            upper = (anchor_top + float(anchors[index + 1]["top"])) / 2
        row_words = [
            word for word in words if lower < float(word["top"]) <= upper
        ]
        description = _join_words(
            [
                word
                for word in row_words
                if name_x - 5 <= float(word["x0"]) < value_x - 8
            ]
        )
        value = _join_words(
            [
                word
                for word in row_words
                if value_x - 8 <= float(word["x0"]) < unit_x - 8
            ]
        )
        unit = _join_words(
            [word for word in row_words if float(word["x0"]) >= unit_x - 8]
        )
        if description:
            observations.append(
                {
                    "sequence": int(anchor["text"]),
                    "label": description,
                    "value": value or None,
                    "unit": unit or None,
                    "help": None,
                    "page": page["number"],
                    "source": "autel_coordinate_table",
                    "anchor_top": round(anchor_top, 3),
                }
            )
    return observations


def _group_value_anchors(
    words: list[dict[str, Any]],
    *,
    minimum_top: float,
    minimum_x: float,
    maximum_x: float,
) -> list[list[dict[str, Any]]]:
    candidates = [
        word
        for word in words
        if float(word["top"]) > minimum_top + 3
        and minimum_x <= float(word["x0"]) < maximum_x
    ]
    candidates.sort(key=lambda word: (float(word["top"]), float(word["x0"])))
    groups: list[list[dict[str, Any]]] = []
    for word in candidates:
        if not groups or abs(float(groups[-1][0]["top"]) - float(word["top"])) > 2.5:
            groups.append([word])
        else:
            groups[-1].append(word)
    merged: list[list[dict[str, Any]]] = []
    for group in groups:
        if (
            merged
            and float(group[0]["top"])
            - max(float(word["top"]) for word in merged[-1])
            <= 17.0
        ):
            merged[-1].extend(group)
        else:
            merged.append(group)
    return merged


def _stellantis_observations(page: dict[str, Any]) -> list[dict[str, Any]]:
    words = page.get("words") or []
    headers = _table_header_positions(words, ("Descrição", "Valor", "Unidade"))
    if not headers:
        return []
    value_header = headers["Valor"]

    header_top = float(value_header["top"])
    # DiagBox centers the header text inside each column, so its x coordinate
    # changes with the number of columns. Body columns remain fixed on A4 and
    # scale proportionally when the PDF page has another width.
    page_width = float(page.get("width") or 595.0)
    description_x = page_width * 0.052
    value_x = page_width * 0.247
    unit_x = page_width * 0.45
    help_x = page_width * 0.649
    anchors = _group_value_anchors(
        words,
        minimum_top=header_top,
        # Stellantis aligns body text a few points left of the header label.
        minimum_x=value_x - 15,
        maximum_x=unit_x - 8,
    )
    observations: list[dict[str, Any]] = []
    for index, anchor_words in enumerate(anchors):
        anchor_top = float(anchor_words[0]["top"])
        anchor_last_top = max(float(word["top"]) for word in anchor_words)
        previous_top = (
            header_top
            if index == 0
            else max(float(word["top"]) for word in anchors[index - 1])
        )
        if index + 1 == len(anchors):
            previous_gap = anchor_top - previous_top
            next_top = anchor_last_top + max(previous_gap, 40.0)
        else:
            next_top = float(anchors[index + 1][0]["top"])
        lower = (previous_top + anchor_top) / 2
        upper = (anchor_last_top + next_top) / 2
        row_words = [
            word for word in words if lower < float(word["top"]) <= upper
        ]
        description = _join_words(
            [
                word
                for word in row_words
                if description_x - 10 <= float(word["x0"]) < value_x - 15
            ]
        )
        value = _join_words(anchor_words)
        unit = _join_words(
            [
                word
                for word in row_words
                if unit_x - 6 <= float(word["x0"]) < help_x - 8
            ]
        )
        help_text = _join_words(
            [word for word in row_words if float(word["x0"]) >= help_x - 6]
        )
        if description:
            observations.append(
                {
                    "sequence": index + 1,
                    "label": description,
                    "value": value or None,
                    "unit": unit or None,
                    "help": help_text or None,
                    "page": page["number"],
                    "source": "stellantis_coordinate_table",
                    "anchor_top": round(anchor_top, 3),
                }
            )
    return observations


def extract_coordinate_observations(
    pages: list[dict[str, Any]],
    machine: str,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    for page in pages:
        if machine == "autel":
            observations.extend(_autel_observations(page))
        elif machine == "stellantis_diagbox":
            observations.extend(_stellantis_observations(page))
    return observations


def _label_value_candidates(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page in pages:
        for line_number, line in enumerate((page.get("layout_text") or "").splitlines(), start=1):
            clean_line = " ".join(line.split())
            if ":" not in clean_line:
                continue
            label, value = clean_line.split(":", 1)
            if not label.strip() or len(label) > 120:
                continue
            candidates.append(
                {
                    "label": label.strip(),
                    "value": value.strip() or None,
                    "page": page["number"],
                    "line": line_number,
                    "raw": clean_line,
                    "source": "layout_label_value",
                }
            )
    return candidates


def _first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return " ".join(match.group(1).strip().split()) or None
    return None


def _extract_dtc_codes(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for page in pages:
        lines = (
            page.get("layout_text")
            or page.get("native_text")
            or (page.get("ocr") or {}).get("text", "")
        ).splitlines()
        for line_number, line in enumerate(lines, start=1):
            for match in _DTC_PATTERN.finditer(line):
                code = match.group(0).upper()
                key = (page["number"], code)
                if key in seen:
                    continue
                seen.add(key)
                context = " ".join(
                    item.strip()
                    for item in lines[max(0, line_number - 2) : line_number + 1]
                    if item.strip()
                )
                results.append(
                    {
                        "code": code,
                        "page": page["number"],
                        "line": line_number,
                        "raw_context": context,
                    }
                )
    return results


def _extract_vin(text: str, filename_vin: str | None) -> str | None:
    strict = _first_match(text, [r"\bVIN\s*:?\s*([A-HJ-NPR-Z0-9]{17})\b"])
    if strict:
        return normalize_vin(strict)
    for match in re.finditer(
        r"\bVIN\s*:?\s*([A-HJ-NPR-Z0-9][A-HJ-NPR-Z0-9\s-]{15,40})",
        text,
        re.IGNORECASE,
    ):
        candidate = normalize_vin(match.group(1))
        if len(candidate) >= 17:
            return candidate[:17]
    candidate = normalize_vin(filename_vin)
    return candidate if len(candidate) == 17 else None


def parse_diagnostic_payload(
    *,
    filename: str,
    pages: list[dict[str, Any]],
    machine: str | None = None,
) -> dict[str, Any]:
    filename_data = parse_diagnostic_filename(filename)
    full_text = "\n\n".join(
        page.get("layout_text") or page.get("native_text") or page.get("ocr", {}).get("text", "")
        for page in pages
    )
    source_machine = machine or detect_diagnostic_machine(filename, full_text)
    vin = _extract_vin(full_text, filename_data.get("vin"))
    raw_test_datetime = _first_match(
        full_text,
        [
            r"Tempo de teste\s*:\s*([^\r\n]+)",
            r"Data impress[ãa]o\s*:\s*([^\r\n]+)",
        ],
    )
    report_datetime = parse_diagnostic_report_datetime(
        raw_test_datetime,
        capture_date=filename_data.get("capture_date"),
        capture_time=filename_data.get("capture_time"),
    )
    normalized = {
        "source_machine": source_machine,
        "source_family": filename_data.get("family"),
        "vin": vin,
        "plate": _first_match(
            full_text,
            [
                r"\bMatr[íi]cula\s*:\s*([A-Z0-9-]{4,12}|--)",
                r"\bPlate\s*:\s*([A-Z0-9-]{4,12}|--)",
            ],
        ),
        "report_number": _first_match(
            full_text,
            [r"N[úu]mero do relat[óo]rio\s*:\s*([^\s]+)"],
        ),
        "test_datetime": raw_test_datetime,
        "report_datetime": (
            report_datetime.isoformat(sep=" ") if report_datetime else None
        ),
        "technician_name": _first_match(
            full_text,
            [r"Nome do t[ée]cnico\s*:\s*([^\r\n]+)"],
        ),
        "tool": _first_match(
            full_text,
            [
                r"Ferramenta\s*:\s*(.*?)\s+N[úu]mero de s[ée]rie\s*:",
                r"(Maxi(?:DAS|Sys)\s+[A-Z0-9-]+)",
            ],
        ),
        "tool_serial": _first_match(
            full_text,
            [r"N[úu]mero de s[ée]rie\s*:\s*([^\s]+)"],
        ),
        "tool_version": _first_match(
            full_text,
            [
                r"Vers[ãa]o da ferramenta\s*:\s*([^\s]+)",
                r"Vers[ãa]o\s*:\s*([^\s]+)",
            ],
        ),
        "odometer": _first_match(
            full_text,
            [r"Quilometragem\s*:\s*([0-9.,]+\s*(?:km)?|--)"],
        ),
        "vehicle": _first_match(
            full_text,
            [
                r"Ve[íi]culo\s*:\s*(.*?)(?:\s{2,}|$)",
                r"\d{4}/[^/\r\n]+/([^\r\n]+?)\s+Quilometragem\s*:",
            ],
        ),
    }
    if normalized["plate"] == "--":
        normalized["plate"] = None
    normalized["diagnostic_type"] = classify_diagnostic_type(full_text, filename)
    observations = extract_coordinate_observations(pages, source_machine)
    label_values = _label_value_candidates(pages)
    return {
        "parser_name": f"{source_machine}_diagnostic_parser",
        "parser_version": PARSER_VERSION,
        "normalized": normalized,
        "observations": observations,
        "label_values": label_values,
        "dtcs": _extract_dtc_codes(pages),
    }


def extract_diagnostic_pdf(
    pdf_path: str | Path,
    *,
    enable_ocr: bool = True,
    force_ocr: bool = False,
    ocr_languages: str = "por+eng",
    ocr_dpi: int = 300,
    minimum_native_characters: int = 80,
    minimum_native_quality: float = 0.35,
) -> dict[str, Any]:
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    try:
        import pdfplumber
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError(
            "A extração de diagnósticos requer pypdf e pdfplumber."
        ) from exc

    warnings: list[str] = []
    reader = PdfReader(path)
    pdf_metadata = _json_value(dict(reader.metadata or {}))
    filename_data = parse_diagnostic_filename(path.name)
    stat = path.stat()
    raw_metadata = {
        "pdf": pdf_metadata,
        "libraries": {
            "pypdf": importlib.metadata.version("pypdf"),
            "pdfplumber": importlib.metadata.version("pdfplumber"),
        },
        "filesystem": {
            "size_bytes": stat.st_size,
            "modified_ns": stat.st_mtime_ns,
            "suffix": path.suffix.lower(),
        },
        "filename": filename_data,
    }

    pages: list[dict[str, Any]] = []
    with pdfplumber.open(path) as plumber_pdf:
        for index, pdf_page in enumerate(reader.pages):
            page_number = index + 1
            try:
                native_text = pdf_page.extract_text() or ""
            except Exception as exc:  # malformed PDFs must remain processable
                native_text = ""
                warnings.append(f"Página {page_number}: texto nativo pypdf falhou: {exc}")
            plumber_page = plumber_pdf.pages[index]
            try:
                layout_text = plumber_page.extract_text(layout=True) or native_text
            except Exception as exc:
                layout_text = native_text
                warnings.append(
                    f"Página {page_number}: reconstrução de layout falhou: {exc}"
                )
            try:
                words = [_word_payload(word) for word in plumber_page.extract_words()]
            except Exception as exc:
                words = []
                warnings.append(
                    f"Página {page_number}: extração de coordenadas falhou: {exc}"
                )
            quality = _native_quality(layout_text or native_text)
            needs_ocr = (
                force_ocr
                or len((layout_text or native_text).strip()) < minimum_native_characters
                or quality < minimum_native_quality
            )
            page_payload: dict[str, Any] = {
                "number": page_number,
                "width": round(float(plumber_page.width), 3),
                "height": round(float(plumber_page.height), 3),
                "rotation": int(pdf_page.get("/Rotate", 0) or 0),
                "native_text": native_text,
                "layout_text": layout_text,
                "words": words,
                "native_quality": quality,
                "ocr_needed": needs_ocr,
                "ocr": None,
            }
            if enable_ocr and needs_ocr:
                ocr_payload, warning = _ocr_page(
                    path,
                    page_number,
                    languages=ocr_languages,
                    dpi=ocr_dpi,
                )
                page_payload["ocr"] = ocr_payload
                if warning:
                    warnings.append(warning)
            pages.append(page_payload)

    preferred_text = "\n\n".join(
        page.get("layout_text")
        or page.get("native_text")
        or (page.get("ocr") or {}).get("text", "")
        for page in pages
    )
    machine = detect_diagnostic_machine(path.name, preferred_text)
    parsed = parse_diagnostic_payload(filename=path.name, pages=pages, machine=machine)
    ocr_pages = [page for page in pages if page.get("ocr")]
    ocr_text = "\n\n".join(page["ocr"]["text"] for page in ocr_pages)
    confidence_components = [
        sum(page["native_quality"] for page in pages) / max(len(pages), 1),
        1.0 if machine != "unknown" else 0.3,
        1.0 if parsed["normalized"].get("vin") else 0.4,
    ]
    confidence = round(sum(confidence_components) / len(confidence_components), 4)
    methods = ["native_text", "layout_words"]
    if ocr_pages:
        methods.append("tesseract_ocr")
    return {
        "extractor_name": EXTRACTOR_NAME,
        "extractor_version": EXTRACTOR_VERSION,
        "parser_name": parsed["parser_name"],
        "parser_version": parsed["parser_version"],
        "source_machine": machine,
        "source_family": filename_data.get("family"),
        "source_filename": path.name,
        "source_sha256": _source_sha256(path),
        "source_page_count": len(pages),
        "extraction_method": "+".join(methods),
        "extraction_status": "extracted" if preferred_text or ocr_text else "needs_review",
        "confidence": confidence,
        "native_text": preferred_text,
        "ocr_text": ocr_text or None,
        "raw_metadata": raw_metadata,
        "pages": pages,
        "normalized": parsed["normalized"],
        "dynamic_fields": {
            "observations": parsed["observations"],
            "label_values": parsed["label_values"],
            "dtcs": parsed["dtcs"],
        },
        "warnings": warnings,
    }


def _integer_odometer(value: str | None) -> int | None:
    if not value or value == "--":
        return None
    digits = re.sub(r"[^\d]", "", value)
    return int(digits) if digits else None


def _normalized_report_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def persist_diagnostic_extraction(
    db: Session,
    profile: DiagnosticDocument,
    payload: dict[str, Any],
) -> DiagnosticExtraction:
    existing = db.scalar(
        select(DiagnosticExtraction).where(
            DiagnosticExtraction.diagnostic_document_id == profile.id,
            DiagnosticExtraction.source_sha256 == payload["source_sha256"],
            DiagnosticExtraction.extractor_name == payload["extractor_name"],
            DiagnosticExtraction.extractor_version == payload["extractor_version"],
            DiagnosticExtraction.parser_version == payload["parser_version"],
        )
    )
    if existing:
        synchronize_diagnostic_profile_from_extraction(db, profile, existing)
        return existing

    extraction = DiagnosticExtraction(
        diagnostic_document_id=profile.id,
        extractor_name=payload["extractor_name"],
        extractor_version=payload["extractor_version"],
        parser_name=payload["parser_name"],
        parser_version=payload["parser_version"],
        source_machine=payload.get("source_machine"),
        source_family=payload.get("source_family"),
        source_filename=payload.get("source_filename"),
        source_sha256=payload["source_sha256"],
        source_page_count=payload["source_page_count"],
        extraction_method=payload["extraction_method"],
        extraction_status=payload["extraction_status"],
        confidence=payload.get("confidence"),
        native_text=payload.get("native_text"),
        ocr_text=payload.get("ocr_text"),
        raw_metadata_json=payload.get("raw_metadata"),
        pages_json=payload.get("pages"),
        normalized_data_json=payload.get("normalized"),
        dynamic_fields_json=payload.get("dynamic_fields"),
        warnings_json=payload.get("warnings"),
    )
    db.add(extraction)
    db.flush()

    synchronize_diagnostic_profile_from_extraction(db, profile, extraction)
    return extraction


def synchronize_diagnostic_profile_from_extraction(
    db: Session,
    profile: DiagnosticDocument,
    extraction: DiagnosticExtraction,
) -> None:
    """Make operational states agree with the latest immutable extraction."""
    normalized = extraction.normalized_data_json or {}
    profile.report_number = normalized.get("report_number") or profile.report_number
    profile.diagnostic_tool = normalized.get("tool") or profile.diagnostic_tool
    profile.diagnostic_tool_serial = normalized.get("tool_serial") or profile.diagnostic_tool_serial
    profile.technician_name = normalized.get("technician_name") or profile.technician_name
    profile.odometer_km = _integer_odometer(normalized.get("odometer")) or profile.odometer_km
    parsed_report_datetime = _normalized_report_datetime(
        normalized.get("report_datetime")
    )
    profile.report_datetime = parsed_report_datetime or profile.report_datetime
    profile.detected_plate = normalized.get("plate") or profile.detected_plate
    profile.detected_vin = normalized.get("vin") or profile.detected_vin
    parsed_type = normalized.get("diagnostic_type")
    if parsed_type and (
        profile.diagnostic_type == "other_diagnostic" or not profile.diagnostic_type
    ):
        profile.diagnostic_type = parsed_type
    profile.ocr_status = (
        "extracted" if extraction.extraction_status == "extracted" else "failed"
    )
    profile.ocr_confidence = extraction.confidence
    profile.ocr_text = extraction.native_text or extraction.ocr_text
    profile.ocr_payload_json = {
        "latest_extraction_id": extraction.id,
        "extractor_version": extraction.extractor_version,
        "parser_version": extraction.parser_version,
        "source_machine": extraction.source_machine,
        "source_family": extraction.source_family,
        "source_sha256": extraction.source_sha256,
        "page_count": extraction.source_page_count,
        "dynamic_field_count": sum(
            len(value)
            for value in (extraction.dynamic_fields_json or {}).values()
            if isinstance(value, list)
        ),
        "warnings": extraction.warnings_json or [],
    }
    if profile.validation_status == "pending":
        profile.validation_status = "needs_review"
    if extraction.extraction_status == "extracted" and profile.diagnostic_status in {
        "received",
        "processing",
    }:
        profile.diagnostic_status = "ready_for_review"

    document = db.get(Document, profile.document_id)
    if document:
        if parsed_report_datetime and not document.document_date:
            document.document_date = parsed_report_datetime.date()
        if not document.file_hash:
            document.file_hash = extraction.source_sha256
        ensure_diagnostic_profile(
            db,
            document,
            detected_plate=profile.detected_plate,
            detected_vin=profile.detected_vin,
        )
