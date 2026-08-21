"""Supplier-aware invoice OCR parsing, independent from document workflow validation.

This module deliberately accepts text instead of owning an OCR engine.  It makes the
output from Azure/Tesseract/PDF text extraction deterministic and testable, while the
caller remains responsible for obtaining the text and for operational classification.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

SUPPLIERS = {
    "500115966": {"code": "filinto_mota", "name": "Filinto Mota"},
    "500112967": {"code": "gamobar", "name": "Gamobar"},
}


@dataclass(frozen=True)
class InvoiceLine:
    description: str
    reference: str | None = None
    quantity: Decimal | None = None
    unit: str | None = None
    unit_price: Decimal | None = None
    discount: Decimal | None = None
    base_amount: Decimal | None = None
    vat_rate: Decimal | None = None


@dataclass
class InvoiceOCRResult:
    supplier_tax_id: str | None
    supplier_code: str | None
    supplier_name: str | None
    layout: str
    fields: dict[str, str | Decimal | date] = field(default_factory=dict)
    lines: list[InvoiceLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def serializable(self) -> dict[str, object]:
        """Return JSON-safe data without converting amounts through binary floats."""
        payload = asdict(self)
        payload["fields"] = {
            key: value.isoformat() if isinstance(value, date) else str(value)
            for key, value in self.fields.items()
        }
        payload["lines"] = [
            {
                key: str(value) if isinstance(value, Decimal) else value
                for key, value in asdict(line).items()
            }
            for line in self.lines
        ]
        return payload


def normalize_tax_id(value: str | None) -> str | None:
    """Normalize a Portuguese NIF, rejecting arbitrary digit sequences."""
    digits = re.sub(r"\D", "", value or "")
    return digits if len(digits) == 9 else None


def parse_decimal(value: str | None) -> Decimal | None:
    """Parse Portuguese or international money syntax directly into ``Decimal``."""
    original = value or ""
    without_currency = re.sub(r"\b(?:EUR|EURO|EUROS)\b|€", "", original, flags=re.I)
    if re.search(r"[A-Za-zÀ-ÿ]", without_currency):
        return None
    clean = re.sub(r"[^\d,().+\-]", "", without_currency).strip()
    if not clean:
        return None
    negative = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()")
    if "," in clean and "." in clean:
        clean = (
            clean.replace(".", "").replace(",", ".")
            if clean.rfind(",") > clean.rfind(".")
            else clean.replace(",", "")
        )
    elif "," in clean:
        clean = clean.replace(".", "").replace(",", ".")
    elif clean.count(".") > 1:
        clean = clean.replace(".", "")
    try:
        number = Decimal(clean)
    except InvalidOperation:
        return None
    return -number if negative else number


def extract_invoice(text: str, *, supplier_tax_id: str | None = None) -> InvoiceOCRResult:
    """Extract an invoice using the normalized supplier NIF and its layout template."""
    # Keep column spacing: OCR engines commonly use repeated spaces as table separators.
    lines = [line.strip().replace("\x00", " ") for line in text.splitlines() if line.strip()]
    detected_nif = normalize_tax_id(supplier_tax_id) or _detect_supplier_nif(lines)
    supplier = SUPPLIERS.get(detected_nif or "")
    layout = _layout_key(lines, supplier["code"] if supplier else "generic")
    result = InvoiceOCRResult(
        supplier_tax_id=detected_nif,
        supplier_code=supplier["code"] if supplier else None,
        supplier_name=supplier["name"] if supplier else None,
        layout=layout,
    )
    if not detected_nif:
        result.warnings.append("NIF do fornecedor não identificado.")
    elif not supplier:
        result.warnings.append(f"Sem template específico para o NIF {detected_nif}.")

    aliases = {
        "invoice_number": ("fatura", "factura", "invoice", "documento nº", "documento no"),
        "invoice_date": ("data fatura", "data documento", "data emissão", "data emissao"),
        "plate": ("matrícula", "matricula", "viatura"),
        "km": ("quilometragem", "kms", "km"),
        "total_with_vat": ("total c/ iva", "total com iva", "total documento", "total a pagar"),
        "work_order": ("folha de obra",),
    }
    for key, labels in aliases.items():
        value = _field_value(lines, labels)
        if not value:
            continue
        if key == "total_with_vat":
            amount = parse_decimal(value)
            if amount is not None:
                result.fields[key] = amount
        elif key == "km":
            match = re.search(r"\d[\d .]*", value)
            if match:
                result.fields[key] = re.sub(r"\D", "", match.group())
        else:
            result.fields[key] = value

    # Filinto's “FO / O.R.” is the supplier's own reference, never CarFast's work order.
    if result.supplier_code == "filinto_mota" and "work_order" in result.fields:
        source_line = next((line for line in lines if str(result.fields["work_order"]) in line), "")
        if re.search(r"\b(?:FO\s*/\s*O\.?R\.?|O\.?R\.?)\b", source_line, re.I):
            result.fields.pop("work_order", None)

    result.lines = list(_extract_table_lines(lines))
    if not result.lines:
        result.warnings.append("Não foram identificadas linhas de detalhe com confiança.")
    return result


def _detect_supplier_nif(lines: Iterable[str]) -> str | None:
    candidates: list[str] = []
    for line in lines:
        if re.search(r"\b(NIF|NIPC|CONTRIBUINTE|VAT)\b", line, re.I):
            candidates.extend(re.findall(r"(?<!\d)(\d[\d .-]{7,14}\d)(?!\d)", line))
    normalized = [normalize_tax_id(candidate) for candidate in candidates]
    return next(
        (nif for nif in normalized if nif in SUPPLIERS), next(iter(filter(None, normalized)), None)
    )


def _layout_key(lines: list[str], supplier_code: str) -> str:
    anchors = []
    for line in lines[:80]:
        simple = _simplify(line)
        if any(
            word in simple
            for word in ("fatura", "descricao", "quantidade", "preco", "iva", "referencia")
        ):
            anchors.append(re.sub(r"\d+", "#", simple))
    digest = hashlib.sha256("|".join(anchors).encode()).hexdigest()[:10]
    return f"{supplier_code}:{digest}"


def _extract_table_lines(lines: list[str]) -> Iterable[InvoiceLine]:
    header = next(
        (
            i
            for i, line in enumerate(lines)
            if "descri" in _simplify(line)
            and any(x in _simplify(line) for x in ("quant", "preco", "valor"))
        ),
        None,
    )
    if header is None:
        return
    for raw in lines[header + 1 :]:
        simple = _simplify(raw)
        if re.search(r"\b(total|subtotal|base tributavel|resumo iva)\b", simple):
            break
        if _is_vertical_or_watermark(raw):
            continue
        columns = [
            part.strip() for part in re.split(r"\s{2,}|\t|\s*\|\s*|\s*;\s*", raw) if part.strip()
        ]
        if len(columns) < 4:
            continue
        numeric_positions = [
            i for i, value in enumerate(columns) if parse_decimal(value) is not None
        ]
        if len(numeric_positions) < 2:
            continue
        first_number = numeric_positions[0]
        description = " ".join(columns[:first_number]).strip()
        if not description or len(description) < 3:
            continue
        reference = (
            columns[0]
            if re.fullmatch(r"[A-Z0-9./-]{3,}", columns[0], re.I) and first_number > 1
            else None
        )
        if reference:
            description = " ".join(columns[1:first_number]).strip()
        nums = [parse_decimal(columns[i]) for i in numeric_positions]
        unit = (
            columns[first_number + 1]
            if first_number + 1 < len(columns) and first_number + 1 not in numeric_positions
            else None
        )
        yield InvoiceLine(
            description=description,
            reference=reference,
            quantity=nums[0],
            unit=unit,
            unit_price=nums[1] if len(nums) > 1 else None,
            discount=nums[2] if len(nums) > 4 else None,
            base_amount=nums[-2] if len(nums) > 3 else nums[-1],
            vat_rate=nums[-1] if len(nums) > 3 else None,
        )


def _field_value(lines: list[str], aliases: tuple[str, ...]) -> str | None:
    for index, line in enumerate(lines):
        simple = _simplify(line)
        for alias in aliases:
            simple_alias = _simplify(alias)
            match = re.search(
                rf"\b{re.escape(simple_alias)}\b\s*(?:n[ºo.]*)?\s*[:#-]?\s*(.+)$", simple
            )
            if match and match.group(1).strip():
                # Slice after a visible separator when possible to preserve original accents/case.
                visible = re.split(r"\s*[:#]\s*", line, maxsplit=1)
                return (visible[1] if len(visible) == 2 else match.group(1)).strip()
            if simple == simple_alias and index + 1 < len(lines):
                return lines[index + 1]
    return None


def _is_vertical_or_watermark(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    spaced_letters = len(re.findall(r"(?:\b[A-Za-zÀ-ÿ]\b\s*){4,}", line)) > 0
    return (
        spaced_letters
        or len(compact) < 3
        or bool(re.search(r"marca\s+d['’]?agua|watermark", line, re.I))
    )


def _clean(value: str) -> str:
    return " ".join(value.replace("\x00", " ").split())


def _simplify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.lower())
    return re.sub(
        r"[^a-z0-9%]+", " ", "".join(c for c in normalized if not unicodedata.combining(c))
    ).strip()
