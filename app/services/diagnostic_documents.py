from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.documents import DiagnosticDocument, Document
from app.models.vehicles import Vehicle

DIAGNOSTIC_TYPES = [
    ("vehicle_diagnostic_report", "Relatório de diagnóstico do veículo"),
    ("fault_codes_global_test", "Códigos de avaria / teste global"),
    ("maintenance_information_bsi", "Informações de manutenção / BSI"),
    ("engine_lubrication_information", "Informações de lubrificação do motor"),
    ("maintenance_reset", "Reset / reposição de manutenção"),
    ("diagnostic_summary", "Síntese de diagnóstico"),
    ("maintenance_threshold_plan", "Plano / limiar de manutenção"),
    ("ecu_identification", "Identificação de calculador"),
    ("particulate_filter_regeneration", "Filtro de partículas / regeneração"),
    ("manufacturer_technical_campaigns", "Campanhas técnicas do construtor"),
    ("battery_charging_system", "Bateria / sistema de carga"),
    ("manufacturer_maintenance_plan", "Plano de manutenção do construtor"),
    ("component_programming", "Programação / inicialização de componentes"),
    ("adblue_scr_system", "Sistema AdBlue / SCR"),
    ("lubricant_technical_sheet", "Ficha técnica de lubrificante"),
    ("technical_portal_check", "Verificação em portal técnico"),
    ("manufacturer_technical_documentation", "Documentação técnica do construtor"),
    ("diagnostic_video", "Vídeo de diagnóstico"),
    ("diagnostic_image", "Imagem de diagnóstico"),
    ("diagnostic_supporting_document", "Documento auxiliar de diagnóstico"),
    ("other_diagnostic", "Outro diagnóstico"),
]
DIAGNOSTIC_TYPE_LABELS = dict(DIAGNOSTIC_TYPES)

DIAGNOSTIC_STATUSES = [
    ("received", "Recebido"),
    ("processing", "Em tratamento"),
    ("ready_for_review", "Pronto para revisão"),
    ("completed", "Concluído"),
    ("archived", "Arquivado"),
    ("rejected", "Rejeitado"),
]
DIAGNOSTIC_STATUS_LABELS = dict(DIAGNOSTIC_STATUSES)

DIAGNOSTIC_ASSOCIATION_STATUSES = [
    ("unassociated", "Sem viatura"),
    ("automatic", "Associação automática"),
    ("manual", "Associação manual"),
    ("confirmed", "Associação confirmada"),
    ("conflict", "Conflito de identificação"),
]
DIAGNOSTIC_ASSOCIATION_STATUS_LABELS = dict(DIAGNOSTIC_ASSOCIATION_STATUSES)

DIAGNOSTIC_OCR_STATUSES = [
    ("not_requested", "Não solicitado"),
    ("pending", "Pendente"),
    ("processing", "Em processamento"),
    ("extracted", "Extraído"),
    ("failed", "Falhou"),
]
DIAGNOSTIC_OCR_STATUS_LABELS = dict(DIAGNOSTIC_OCR_STATUSES)

DIAGNOSTIC_VALIDATION_STATUSES = [
    ("pending", "Pendente"),
    ("needs_review", "Requer revisão"),
    ("validated", "Validado"),
    ("rejected", "Rejeitado"),
]
DIAGNOSTIC_VALIDATION_STATUS_LABELS = dict(DIAGNOSTIC_VALIDATION_STATUSES)

_TYPE_RULES = [
    (
        "engine_lubrication_information",
        (
            "informacoes lubrificacao motor",
            "diagnostico lubrificacao",
            "taxa de diluicao estimada do oleo",
            "taxa de carbono estimada no oleo",
        ),
    ),
    (
        "maintenance_reset",
        (
            "diagnostico reset reposicao",
            "reposicao a zero da manutencao",
            "reposicao a zero do numero de manutencao",
            "reajuste de oleo",
        ),
    ),
    (
        "maintenance_information_bsi",
        ("diagnostico manutencao bsi", "informacoes manutencao", "informacoes de manutencao"),
    ),
    (
        "maintenance_threshold_plan",
        (
            "limiar manutencao",
            "parametros de manutencao recuperados do veiculo",
            "manutencao gerida pela motorizacao",
        ),
    ),
    (
        "vehicle_diagnostic_report",
        (
            "relatorio de diagnostico do veiculo",
            "vehicle health report",
            "relatorio diagnostico veiculo",
        ),
    ),
    (
        "diagnostic_summary",
        ("synthesepe", "sintese do diagnostico", "sintese diagnostico"),
    ),
    (
        "ecu_identification",
        (
            "identificacao calculador",
            "referencia complementar do material",
            "referencia homologacao eobd",
        ),
    ),
    (
        "fault_codes_global_test",
        (
            "codigos de avaria",
            "codigos de erro",
            "leitura de defeitos",
            "teste global",
        ),
    ),
    (
        "component_programming",
        ("inicializacao apos remplacement", "programacao da sonda", "processo terminado"),
    ),
    (
        "manufacturer_maintenance_plan",
        ("planos de manutencao", "sintese de manutencao", "plano de manutencao"),
    ),
    (
        "manufacturer_technical_campaigns",
        ("campanhas tecnicas", "campanhas construtor", "diagnostico campanhas"),
    ),
    (
        "manufacturer_technical_documentation",
        ("documentacao tecnica", "fdz navigation par fonction"),
    ),
    (
        "lubricant_technical_sheet",
        ("ficha tecnica lubrificante", "tds totalenergies", "caracteristicas do produto"),
    ),
    (
        "particulate_filter_regeneration",
        ("filtro de particulas", "regeneracao do filtro", "diagnostico fap"),
    ),
    ("adblue_scr_system", ("adblue", "sistema scr", "ureia")),
    ("battery_charging_system", ("estado da bateria", "teste bateria", "sistema de carga")),
    (
        "technical_portal_check",
        ("verificacao portal tecnico", "aucun abonnement disponible", "inspecao rodoviaria"),
    ),
]

_UNIT_PATTERN = re.compile(r"\b(?:unit|unidade)\s*[#:_-]?\s*0*(\d+)\b", re.IGNORECASE)


def normalized_search_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def normalize_plate(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def normalize_vin(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper())


def find_vehicle_by_plate(db: Session, plate: str | None) -> Vehicle | None:
    clean_plate = normalize_plate(plate)
    if not clean_plate:
        return None
    matches = [
        vehicle
        for vehicle in db.scalars(select(Vehicle).where(Vehicle.plate.is_not(None))).all()
        if normalize_plate(vehicle.plate) == clean_plate
    ]
    return matches[0] if len(matches) == 1 else None


def document_vehicle_predicate(vehicle: Vehicle):
    predicates = [Document.vehicle_id == vehicle.id]
    clean_plate = normalize_plate(vehicle.plate)
    if clean_plate:
        normalized_db_plate = func.upper(
            func.replace(func.replace(func.replace(Document.plate, "-", ""), " ", ""), ".", "")
        )
        predicates.append(normalized_db_plate == clean_plate)
    return or_(*predicates)


def classify_diagnostic_type(*values: str | None, file_type: str | None = None) -> str:
    corpus = normalized_search_text(" ".join(value or "" for value in values))
    for diagnostic_type, terms in _TYPE_RULES:
        if any(term in corpus for term in terms):
            return diagnostic_type
    extension = (file_type or "").lower()
    if extension in {".mov", ".mp4", "video/quicktime", "video/mp4"}:
        return "diagnostic_video"
    if extension in {".png", ".jpg", ".jpeg", "image/png", "image/jpeg"}:
        return "diagnostic_image"
    return "other_diagnostic"


def diagnostic_document_text(document: Document) -> str:
    return " ".join(
        value or ""
        for value in (
            document.title,
            document.original_name,
            document.file_name,
            document.folder_path,
            document.storage_path,
            document.source_subject,
        )
    )


def looks_like_diagnostic(document: Document) -> bool:
    if document.document_type == "workshop_diagnostic":
        return True
    text = normalized_search_text(diagnostic_document_text(document))
    return "diagnost" in text and document.document_type not in {
        "workshop_supplier_invoice",
        "finance_supplier_invoice",
        "finance_credit_note",
        "finance_receipt",
        "finance_payment_proof",
    }


def find_vehicle_for_document(
    db: Session,
    document: Document,
    *,
    detected_plate: str | None = None,
    detected_vin: str | None = None,
) -> tuple[Vehicle | None, str]:
    if document.vehicle_id:
        vehicle = db.get(Vehicle, document.vehicle_id)
        if vehicle:
            return vehicle, "confirmed"

    clean_plate = normalize_plate(detected_plate or document.plate)
    if clean_plate:
        vehicle = find_vehicle_by_plate(db, clean_plate)
        if vehicle:
            return vehicle, "automatic"
        vehicles = db.scalars(select(Vehicle).where(Vehicle.plate.is_not(None))).all()
        if sum(normalize_plate(item.plate) == clean_plate for item in vehicles) > 1:
            return None, "conflict"

    clean_vin = normalize_vin(detected_vin)
    if clean_vin:
        vehicles = db.scalars(select(Vehicle).where(Vehicle.vin.is_not(None))).all()
        vin_matches = [vehicle for vehicle in vehicles if normalize_vin(vehicle.vin) == clean_vin]
        if len(vin_matches) == 1:
            return vin_matches[0], "automatic"
        if len(vin_matches) > 1:
            return None, "conflict"

    unit_matches = {
        match.group(1).lstrip("0") or "0"
        for match in _UNIT_PATTERN.finditer(diagnostic_document_text(document))
    }
    if len(unit_matches) == 1:
        unit_number = next(iter(unit_matches))
        vehicles = db.scalars(select(Vehicle).where(Vehicle.rentway_unit_nr.is_not(None))).all()
        matches = [
            vehicle
            for vehicle in vehicles
            if ((vehicle.rentway_unit_nr or "").strip().lstrip("0") or "0") == unit_number
        ]
        if len(matches) == 1:
            return matches[0], "automatic"
        if len(matches) > 1:
            return None, "conflict"

    return None, "unassociated"


def ensure_diagnostic_profile(
    db: Session,
    document: Document,
    *,
    diagnostic_type: str | None = None,
    association_status: str | None = None,
    detected_plate: str | None = None,
    detected_vin: str | None = None,
) -> DiagnosticDocument:
    profile = db.scalar(
        select(DiagnosticDocument).where(DiagnosticDocument.document_id == document.id)
    )
    profile_created = profile is None
    clean_type = diagnostic_type if diagnostic_type in DIAGNOSTIC_TYPE_LABELS else None
    if not profile:
        profile = DiagnosticDocument(
            document_id=document.id,
            diagnostic_type=clean_type
            or classify_diagnostic_type(
                diagnostic_document_text(document),
                file_type=document.file_type,
            ),
        )
        db.add(profile)
    elif clean_type:
        profile.diagnostic_type = clean_type

    document.classification = "workshop"
    document.document_type = "workshop_diagnostic"
    if detected_plate:
        profile.detected_plate = detected_plate.strip().upper() or None
    if detected_vin:
        profile.detected_vin = normalize_vin(detected_vin) or None

    if association_status in DIAGNOSTIC_ASSOCIATION_STATUS_LABELS:
        profile.association_status = association_status
    elif (
        profile_created
        or profile.association_status in {"unassociated", "conflict"}
        or bool(detected_plate or detected_vin)
    ):
        vehicle, resolved_status = find_vehicle_for_document(
            db,
            document,
            detected_plate=profile.detected_plate,
            detected_vin=profile.detected_vin,
        )
        profile.association_status = resolved_status
        if vehicle:
            document.vehicle_id = vehicle.id
            document.plate = vehicle.plate
    return profile


def backfill_legacy_diagnostics(
    db: Session,
    documents: Iterable[Document] | None = None,
) -> dict[str, int]:
    candidates = list(documents) if documents is not None else db.scalars(select(Document)).all()
    stats = {"scanned": len(candidates), "diagnostics": 0, "profiles_created": 0, "associated": 0}
    for document in candidates:
        if not looks_like_diagnostic(document):
            continue
        stats["diagnostics"] += 1
        existing = db.scalar(
            select(DiagnosticDocument).where(DiagnosticDocument.document_id == document.id)
        )
        profile = ensure_diagnostic_profile(db, document)
        if not existing:
            stats["profiles_created"] += 1
        if document.vehicle_id and profile.association_status != "unassociated":
            stats["associated"] += 1
    return stats
