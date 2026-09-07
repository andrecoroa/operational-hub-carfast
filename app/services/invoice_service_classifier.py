from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
import unicodedata


TAXONOMY_VERSION = "1.1.0-draft"


def normalize_invoice_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value or "")
    ascii_text = "".join(char for char in folded if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).strip()


def _has(text: str, *terms: str) -> bool:
    return any(term in text for term in terms)


@dataclass(slots=True)
class InvoiceClassificationProposal:
    taxonomy_version: str = TAXONOMY_VERSION
    taxonomy_codes: list[str] = field(default_factory=list)
    legacy_projection: dict[str, list[str]] = field(
        default_factory=lambda: {
            key: [] for key in ("maintenance", "pads", "discs", "tyres", "ipo", "other")
        }
    )
    motives: list[str] = field(default_factory=list)
    auxiliary: list[str] = field(default_factory=list)
    evidence: dict[str, list[str]] = field(default_factory=dict)
    blocked_reasons: list[str] = field(default_factory=list)

    def add_code(self, code: str, reason: str) -> None:
        if code not in self.taxonomy_codes:
            self.taxonomy_codes.append(code)
        self.evidence.setdefault(code, []).append(reason)

    def add_legacy(self, category: str, value: str) -> None:
        values = self.legacy_projection[category]
        if value not in values:
            values.append(value)

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def classify_invoice_service_text(value: str) -> InvoiceClassificationProposal:
    """Build a deterministic proposal without mutating application data."""

    text = normalize_invoice_text(value)
    proposal = InvoiceClassificationProposal()
    if not text:
        proposal.blocked_reasons.append("empty_text")
        return proposal

    has_engine_oil = _has(text, "oleo motor", "oleo do motor", "lubrificante motor")
    has_oil_filter = _has(text, "filtro oleo", "filtro de oleo")
    periodic_components = {
        "FILTER.AIR": _has(text, "filtro ar", "filtro de ar"),
        "FILTER.FUEL": _has(text, "filtro combustivel", "filtro de combustivel", "filtro gasoleo"),
        "FILTER.CABIN": _has(text, "filtro habitaculo", "filtro do habitaculo", "filtro polen", "filtro de polen"),
        "IGNITION.SPARK_PLUG": _has(text, "vela ignicao", "velas ignicao", "velas de ignicao"),
        "BRAKE.FLUID": _has(text, "fluido travoes", "fluido de travoes", "oleo travoes", "oleo de travoes"),
    }
    for code, present in periodic_components.items():
        if present:
            proposal.add_code(code, "componente periódico explícito")
    if has_engine_oil:
        proposal.add_code("FLUID.ENGINE_OIL", "óleo do motor explícito")
    if has_oil_filter:
        proposal.add_code("FILTER.OIL", "filtro de óleo explícito")
    if _has(text, "liquido refrigerante", "anticongelante", "anti congelante"):
        proposal.add_code("FLUID.COOLANT", "líquido refrigerante explícito")
    if "adblue" in text:
        proposal.add_code("FLUID.ADBLUE", "AdBlue explícito")
    if _has(text, "lampada", "iluminacao", "farol", "farolim"):
        proposal.add_code("ELECTRIC.LIGHTING", "intervenção de iluminação explícita")

    explicit_plan = _has(
        text,
        "revisao",
        "manutencao programada",
        "manutencao conforme plano",
        "servico periodico",
    ) and not _has(text, "proxima revisao", "proxima manutencao")
    maintenance_bundle = has_engine_oil and has_oil_filter and any(periodic_components.values())
    if explicit_plan or maintenance_bundle:
        proposal.add_code("MAINT.PLAN", "menção explícita ou conjunto periódico completo")
        proposal.add_legacy("maintenance", "revision")
    elif has_engine_oil and has_oil_filter:
        proposal.add_code("MAINT.OIL_INTERIM", "óleo do motor e filtro sem componente periódico adicional")
        proposal.add_legacy("maintenance", "degradation")
    elif "degrad" in text:
        proposal.blocked_reasons.append("degradation_without_oil_and_filter")

    if "telecarreg" in text:
        proposal.add_code("DIAG.DOWNLOAD", "telecarregamento explícito")

    washer_context = _has(
        text,
        "lava vidros",
        "lavavidros",
        "limpa vidros",
        "limpavidros",
        "liquido para brisas",
        "escova limpa",
    )
    if washer_context:
        proposal.add_code("FLUID.WASHER", "líquido ou sistema lava-vidros")
    glass_context = _has(text, "para brisas", "parabrisas", "vidro", "vidraca")
    glass_action = _has(text, "substitu", "repara", "montagem", "desmontagem", "quebrado", "partido")
    if glass_context and glass_action and not washer_context:
        proposal.add_code("GLASS.REPLACE", "intervenção explícita em vidro")
        proposal.add_legacy("other", "glass")

    pads = _has(text, "calco", "pastilha") or ("placa" in text and "trava" in text)
    discs = "disco" in text and _has(text, "trava", "travagem")
    if pads:
        proposal.add_code("BRAKE.PAD", "calço/pastilha/placa de travão explícito")
        proposal.add_legacy("pads", "undefined")
    if discs:
        proposal.add_code("BRAKE.DISC", "disco de travão explícito")
        proposal.add_legacy("discs", "undefined")

    tyre_context = _has(text, "pneu", "roda", "furo", "furado")
    if tyre_context:
        if _has(text, "furo", "furado"):
            proposal.add_code("TYRE.REPAIR", "furo explícito")
            proposal.add_legacy("tyres", "puncture")
        elif _has(text, "equilibr"):
            proposal.add_code("TYRE.BALANCE", "equilibragem explícita")
        elif _has(text, "alinham", "geometr"):
            proposal.add_code("TYRE.ALIGN", "alinhamento/geometria explícito")
        elif _has(text, "rotacao", "permut"):
            proposal.add_code("TYRE.ROTATE", "rotação explícita")
        elif _has(text, "substitu", "montagem", "troca", "novo"):
            proposal.add_code("TYRE.REPLACE", "substituição explícita")
            proposal.add_legacy("tyres", "undefined")
        else:
            proposal.blocked_reasons.append("tyre_operation_undefined")

    if _has(text, "ipo", "inspecao periodica"):
        proposal.add_code("INSPECTION.PERIODIC", "inspeção periódica explícita")
        proposal.add_legacy("ipo", "yes")
    if _has(text, "sinistro", "acidente"):
        proposal.motives.append("claim")
    if _has(text, "lavagem", "ecolub", "sigou", "recolha e entrega", "pickup delivery"):
        proposal.auxiliary.append("non_technical_or_ancillary")
    return proposal


def legacy_service_matrix(value: str) -> dict[str, str]:
    proposal = classify_invoice_service_text(value)
    labels = {
        "maintenance": {"revision": "Revisão", "degradation": "Degradação"},
        "pads": {"undefined": "Por definir"},
        "discs": {"undefined": "Por definir"},
        "tyres": {"undefined": "Por definir", "puncture": "Furo"},
        "ipo": {"yes": "IPO"},
        "other": {"glass": "Vidros"},
    }
    return {
        category: " · ".join(labels.get(category, {}).get(code, code) for code in codes) or "-"
        for category, codes in proposal.legacy_projection.items()
    }
