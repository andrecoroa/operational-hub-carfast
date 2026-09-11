from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import unicodedata
from typing import Any, Iterable


REMEDIATION_SCHEMA = "carfast.invoice-service-remediation.v2"
TWO_PLACES = Decimal("0.01")


def _normalise(value: Any) -> str:
    folded = unicodedata.normalize("NFKD", str(value or ""))
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def _money(value: Any) -> Decimal:
    text = str(value or "").strip().replace(" ", "").replace(",", ".")
    if not text:
        return Decimal("0")
    try:
        return Decimal(text).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return Decimal("0")


def _contains(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


def build_article_axle_lookup(payload: dict[str, Any]) -> dict[str, dict[str, str]]:
    if payload.get("schema") != "carfast.invoice-article-axle-map.v1":
        raise ValueError("Esquema inválido para o mapa fornecedor+artigo.")
    lookup: dict[str, dict[str, str]] = {}
    for mapping in payload.get("mappings", []):
        supplier_key = str(mapping.get("supplier_key") or "").strip()
        article_reference = str(mapping.get("article_reference") or "").strip()
        axle = str(mapping.get("axle") or "").strip()
        if not supplier_key or not article_reference or axle not in {"front", "rear", "both"}:
            raise ValueError("Entrada incompleta ou eixo inválido no mapa fornecedor+artigo.")
        key = f"{_normalise(supplier_key)}|{_normalise(article_reference)}"
        if key in lookup:
            raise ValueError("Entrada duplicada no mapa fornecedor+artigo.")
        lookup[key] = {
            "axle": axle,
            "evidence": str(mapping.get("evidence") or "").strip(),
        }
    return lookup


def _explicit_axle(text: str) -> tuple[str, str]:
    front = bool(re.search(r"\b(frente|frt|fr|front|diant|dianteir[oa]s?|af)\b", text))
    rear = bool(re.search(r"\b(tras|traseir[oa]s?|rear|tr|at)\b", text))
    if front and rear:
        return "both", "descrição contém indicadores explícitos dianteiro e traseiro"
    if front:
        return "front", "descrição contém indicador explícito dianteiro"
    if rear:
        return "rear", "descrição contém indicador explícito traseiro"
    return "", ""


@dataclass(slots=True)
class ClassifiedLine:
    source_line_id: str
    line_number: int
    description: str
    reference: str
    amount: Decimal
    role: str
    service_code: str = ""
    axle: str = ""
    axle_source: str = "unknown"
    axle_evidence: str = ""
    confidence: Decimal = Decimal("0")
    reason: str = ""
    auxiliary_codes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["amount"] = str(self.amount)
        payload["confidence"] = str(self.confidence)
        return payload


def classify_invoice_line(
    row: dict[str, Any],
    *,
    supplier_key: str = "",
    article_axle_map: dict[str, dict[str, str]] | None = None,
) -> ClassifiedLine:
    description = str(row.get("description") or "").strip()
    text = _normalise(description)
    source_role = str(row.get("line_role") or "").strip()
    explicit_axle, explicit_evidence = _explicit_axle(text)
    line = ClassifiedLine(
        source_line_id=str(row.get("source_line_id") or "").strip(),
        line_number=int(str(row.get("line_number") or "0") or 0),
        description=description,
        reference=str(row.get("reference") or "").strip(),
        amount=_money(row.get("line_total")),
        role="labor" if source_role == "LINE.LABOR" or _contains(text, "mao de obra", "operacao de servico") else "part",
        axle=explicit_axle,
        axle_source="description_explicit" if explicit_axle else "unknown",
        axle_evidence=explicit_evidence,
    )

    if _contains(text, "ecolub", "sigou", "taxa", "lavagem", "aspiracao"):
        line.role = "ancillary"
        line.reason = "linha auxiliar sem evento técnico autónomo"
        line.confidence = Decimal("0.99")
        return line
    if _contains(text, "ensaio apos", "teste apos"):
        line.role = "labor"
        line.reason = "ensaio associado ao serviço técnico precedente"
        line.confidence = Decimal("0.80")
        return line
    if _contains(text, "diagnostico", "procura de pane", "diagnose"):
        line.service_code = "DIAG.GENERAL"
        line.reason = "diagnóstico/procura de avaria explícito"
        line.confidence = Decimal("0.96")
    elif _contains(text, "avisador travao", "avisador de travao", "sensor travao", "sensor de travao"):
        line.service_code = "BRAKE.SENSOR"
        line.reason = "avisador/sensor de travão explícito"
        line.confidence = Decimal("0.91")
    elif _contains(
        text,
        "calco",
        "pastilha",
        "placa travao",
        "placas travao",
        "placa de travao",
        "placas de travao",
    ):
        line.service_code = "BRAKE.PAD"
        if re.search(r"\bpastilhas? tra\b", text):
            line.reason = "TRA interpretado como travão; eixo depende de contexto explícito"
            line.confidence = Decimal("0.92")
        else:
            line.reason = "calços/pastilhas de travão explícitos"
            line.confidence = Decimal("0.98")
    elif "disco" in text and (_contains(text, "trava", "travagem", "jogo disco", "jogo de disco") or line.axle):
        line.service_code = "BRAKE.DISC"
        line.reason = "discos de travão explícitos"
        line.confidence = Decimal("0.98")
    elif _contains(text, "pneu", "bestdrive", "michelin", "continental", "bridgestone", "hankook", "goodyear", "kormoran") or re.search(
        r"\b\d{3}\s+\d{2}r\d{2}\b", text
    ):
        line.service_code = "TYRE.REPLACE"
        line.reason = "pneu/medida de pneu explícita"
        line.confidence = Decimal("0.94")
    elif _contains(text, "equilibr", "jante"):
        line.service_code = "TYRE.BALANCE"
        line.reason = "equilibragem explícita"
        line.confidence = Decimal("0.96")
    elif _contains(text, "valvula tubeless", "valvula pneu"):
        line.service_code = "TYRE.VALVE"
        line.reason = "válvula de pneu explícita"
        line.confidence = Decimal("0.91")
    elif _contains(text, "lampada", "iluminacao", "substituicao luz", "substituir luz"):
        line.service_code = "ELECTRIC.LIGHTING"
        line.reason = "iluminação/lâmpada explícita"
        line.confidence = Decimal("0.97")
    elif _contains(text, "bateria", "acumulador"):
        line.service_code = "ELECTRIC.BATTERY"
        line.reason = "bateria explícita"
        line.confidence = Decimal("0.96")
    elif _contains(text, "filtro habitaculo", "filtro polen"):
        line.service_code = "FILTER.CABIN"
        line.reason = "filtro de habitáculo explícito"
        line.confidence = Decimal("0.99")
    elif _contains(text, "filtro ar", "filtro de ar"):
        line.service_code = "FILTER.AIR"
        line.reason = "filtro de ar explícito"
        line.confidence = Decimal("0.99")
    elif _contains(text, "filtro combustivel", "filtro gasoleo"):
        line.service_code = "FILTER.FUEL"
        line.reason = "filtro de combustível explícito"
        line.confidence = Decimal("0.99")
    elif _contains(text, "filtro oleo", "filtro de oleo"):
        line.service_code = "FILTER.OIL"
        line.reason = "filtro de óleo explícito"
        line.confidence = Decimal("0.99")
    elif _contains(text, "oleo motor", "oleo do motor", "mudar oleo", "mudanca de oleo", "oleo total", "total ineo") or re.search(r"\b\d{1,2}w\d{2}\b", text):
        line.service_code = "FLUID.ENGINE_OIL"
        if _contains(text, "filtro"):
            line.auxiliary_codes.append("FILTER.OIL")
        line.reason = "óleo do motor explícito"
        line.confidence = Decimal("0.98")
    elif _contains(text, "junta bujao", "bujão oleo", "bujao ole"):
        line.service_code = "FLUID.ENGINE_OIL"
        line.reason = "consumível específico de mudança de óleo"
        line.confidence = Decimal("0.82")
    else:
        line.role = "labor" if line.role == "labor" else "unassigned"
        line.reason = "sem regra técnica determinística"

    if not line.axle and line.reference and article_axle_map:
        lookup_key = f"{_normalise(supplier_key)}|{_normalise(line.reference)}"
        mapping = article_axle_map.get(lookup_key)
        if mapping and mapping.get("axle") in {"front", "rear", "both"}:
            line.axle = mapping["axle"]
            line.axle_source = "validated_article_map"
            line.axle_evidence = (
                f"mapa validado fornecedor+artigo: {supplier_key} + {line.reference}"
                + (f"; {mapping['evidence']}" if mapping.get("evidence") else "")
            )
    return line


def _group_code(code: str) -> str:
    if code in {"FLUID.ENGINE_OIL", "FILTER.OIL"}:
        return "MAINT.OIL"
    if code in {"TYRE.REPLACE", "TYRE.BALANCE", "TYRE.VALVE"}:
        return "TYRE.SERVICE"
    return code


def _nearest_group(lines: list[ClassifiedLine], index: int, groups: dict[tuple[str, str], list[int]]) -> tuple[str, str] | None:
    candidates: list[tuple[int, int, tuple[str, str]]] = []
    for key, indexes in groups.items():
        for assigned_index in indexes:
            distance = abs(index - assigned_index)
            # Prefer a preceding technical line at equal distance.
            direction_penalty = 0 if assigned_index < index else 1
            candidates.append((distance, direction_penalty, key))
    return min(candidates, default=(0, 0, None))[2]


def build_document_service_proposals(
    document: dict[str, Any],
    line_rows: Iterable[dict[str, Any]],
    *,
    article_axle_map: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    supplier_key = str(
        document.get("supplier_group")
        or document.get("supplier_nif_extracted")
        or document.get("supplier_name_extracted")
        or document.get("supplier_name_record")
        or ""
    )
    lines = sorted(
        (
            classify_invoice_line(
                row,
                supplier_key=supplier_key,
                article_axle_map=article_axle_map,
            )
            for row in line_rows
        ),
        key=lambda line: line.line_number,
    )
    groups: dict[tuple[str, str], list[int]] = {}
    for index, line in enumerate(lines):
        if line.service_code:
            key = (_group_code(line.service_code), line.axle if line.service_code.startswith("BRAKE.") else "")
            groups.setdefault(key, []).append(index)

    # Abbreviations such as ``TRA`` in part names mean ``travão``, not
    # ``traseiro``.  An unspecified brake part inherits an axle only when the
    # same invoice supplies one unambiguous explicit brake context.
    for service_code in {key[0] for key in groups if key[0].startswith("BRAKE.")}:
        unknown_key = (service_code, "")
        unknown_indexes = groups.get(unknown_key, [])
        if not unknown_indexes:
            continue
        same_code_axles = {key[1] for key in groups if key[0] == service_code and key[1]}
        contextual_axles = same_code_axles or {
            key[1] for key in groups if key[0].startswith("BRAKE.") and key[1]
        }
        if len(contextual_axles) == 1:
            inferred_axle = next(iter(contextual_axles))
            groups.setdefault((service_code, inferred_axle), []).extend(unknown_indexes)
            groups.pop(unknown_key, None)
            for index in unknown_indexes:
                lines[index].axle = inferred_axle
                lines[index].axle_source = "context_consistent"
                context_ids = [
                    lines[context_index].source_line_id
                    for key, context_indexes in groups.items()
                    if key[0].startswith("BRAKE.") and key[1] == inferred_axle
                    for context_index in context_indexes
                    if context_index not in unknown_indexes
                ]
                lines[index].axle_evidence = (
                    f"contexto único de travagem {inferred_axle}; linhas "
                    + "|".join(dict.fromkeys(context_ids))
                )
                lines[index].reason += (
                    f"; eixo {inferred_axle} inferido pelo único contexto explícito "
                    "de travagem na mesma fatura"
                )

    for index, line in enumerate(lines):
        if line.service_code or line.role == "ancillary":
            continue
        nearest = _nearest_group(lines, index, groups)
        if nearest is not None and line.role == "labor":
            groups[nearest].append(index)

    oil_indexes = groups.pop(("MAINT.OIL", ""), [])
    if oil_indexes:
        oil_codes = {
            code
            for index in oil_indexes
            for code in ([lines[index].service_code] + lines[index].auxiliary_codes)
            if code
        }
        periodic_codes = {"FILTER.AIR", "FILTER.FUEL", "FILTER.CABIN"}
        for periodic_code in periodic_codes:
            periodic_indexes = groups.pop((periodic_code, ""), [])
            if periodic_indexes:
                oil_indexes.extend(periodic_indexes)
                oil_codes.add(periodic_code)
        primary = "MAINT.PLAN" if oil_codes.intersection(periodic_codes) else "MAINT.OIL_INTERIM"
        groups[(primary, "")] = oil_indexes

    proposals: list[dict[str, Any]] = []
    assigned: set[int] = set()
    for sequence, (key, indexes) in enumerate(sorted(groups.items(), key=lambda item: min(item[1])), start=1):
        unique_indexes = sorted(set(indexes))
        assigned.update(unique_indexes)
        group_lines = [lines[index] for index in unique_indexes]
        group_code, group_axle = key
        codes = [line.service_code for line in group_lines if line.service_code]
        primary_code = (
            group_code
            if group_code not in {"TYRE.SERVICE"}
            else "TYRE.REPLACE"
            if "TYRE.REPLACE" in codes
            else "TYRE.BALANCE"
        )
        auxiliary_codes = sorted({code for code in codes if code != primary_code})
        amount = sum((line.amount for line in group_lines), Decimal("0")).quantize(TWO_PLACES)
        confidence = min((line.confidence for line in group_lines if line.confidence), default=Decimal("0.50"))
        source_ids = [line.source_line_id for line in group_lines]
        axle_sources = [line.axle_source for line in group_lines if line.axle_source != "unknown"]
        axle_source = (
            "description_explicit"
            if "description_explicit" in axle_sources
            else "validated_article_map"
            if "validated_article_map" in axle_sources
            else "context_consistent"
            if "context_consistent" in axle_sources
            else "unknown"
        )
        proposals.append(
            {
                "stable_key": f"{document.get('run_id', 'remediation')}:{document['document_id']}:S{sequence:02d}:{primary_code}:{group_axle or 'NA'}",
                "document_id": int(document["document_id"]),
                "service_code": primary_code,
                "subcategory": ", ".join(auxiliary_codes),
                "axle": group_axle,
                "axle_source": axle_source,
                "axle_evidence": " | ".join(
                    dict.fromkeys(line.axle_evidence for line in group_lines if line.axle_evidence)
                ),
                "service_text": " | ".join(line.description for line in group_lines),
                "source_line_ids": "|".join(source_ids),
                "source_lines": [line.as_dict() for line in group_lines],
                "parts": " | ".join(line.description for line in group_lines if line.role == "part"),
                "labor": " | ".join(line.description for line in group_lines if line.role == "labor"),
                "amount": str(amount),
                "confidence": str(confidence),
                "confidence_reason": " | ".join(dict.fromkeys(line.reason for line in group_lines)),
                "status": "pending_validation",
            }
        )

    unassigned_lines = [line for index, line in enumerate(lines) if index not in assigned]
    source_total = sum((line.amount for line in lines), Decimal("0")).quantize(TWO_PLACES)
    service_total = sum((_money(item["amount"]) for item in proposals), Decimal("0")).quantize(TWO_PLACES)
    excluded_total = sum((line.amount for line in unassigned_lines), Decimal("0")).quantize(TWO_PLACES)
    invoice_total = _money(document.get("total_extracted") or document.get("total_source"))
    residual = (invoice_total - source_total).quantize(TWO_PLACES)
    relevant_unassigned = [line for line in unassigned_lines if line.role != "ancillary" and line.amount != 0]
    projection = "services_classified" if proposals and not relevant_unassigned else "services_review_required"
    return {
        "schema": REMEDIATION_SCHEMA,
        "document_id": int(document["document_id"]),
        "document_projection": projection,
        "services": proposals,
        "unassigned_lines": [line.as_dict() for line in unassigned_lines],
        "reconciliation": {
            "invoice_total": str(invoice_total),
            "source_line_total": str(source_total),
            "service_total": str(service_total),
            "excluded_or_unassigned_total": str(excluded_total),
            "invoice_minus_source_lines": str(residual),
            "service_plus_excluded_minus_source_lines": str(
                (service_total + excluded_total - source_total).quantize(TWO_PLACES)
            ),
        },
    }
