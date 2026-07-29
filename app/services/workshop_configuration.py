from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.vehicles import Vehicle
from app.models.workshop_phased import (
    WorkshopDiagnosticCatalogItem,
    WorkshopDiagnosticSuggestion,
    WorkshopPhasedProcess,
    WorkshopPhasedProcessPhase,
    WorkshopPublicCounter,
    WorkshopTemplate,
    WorkshopTemplateVersion,
)

WORKSHOP_STOCK_STATUSES = {
    "unavailable",
    "requested",
    "partially_reserved",
    "reserved",
    "delivered",
    "applied",
    "returned",
}

BASE_PHASES = [
    {
        "code": "entrada",
        "name": "Entrada",
        "required": True,
        "required_fields": ["entry_reasons", "entry_km"],
        "optional_fields": ["expected_exit", "validation_notes"],
        "photo_requirements": ["dashboard", "vehicle_sides"],
        "document_requirements": [],
        "responsible_role": "workshop",
        "transition_rules": ["entry_km_present"],
        "substeps": ["motivo", "danos", "saida"],
        "material_points": [],
    },
    {
        "code": "validacao",
        "name": "Pedido e orientação de diagnóstico",
        "required": True,
        "required_fields": ["service_decisions", "diagnostic_orientation"],
        "optional_fields": ["validation_observation", "priority", "reservations"],
        "photo_requirements": [],
        "document_requirements": [],
        "responsible_role": "workshop_manager",
        "transition_rules": ["request_decided"],
        "substeps": ["prerequisitos", "pedido_orientacao"],
        "material_points": [],
    },
    {
        "code": "diagnostico",
        "name": "Diagnóstico técnico",
        "required": True,
        "required_fields": ["diagnostic_closed"],
        "optional_fields": ["diagnostic_conclusion", "diagnostic_reserve_reason"],
        "photo_requirements": [],
        "document_requirements": ["diagnostic_reports"],
        "responsible_role": "technician",
        "transition_rules": ["reports_validated_or_reserved"],
        "substeps": ["relatorios", "leituras", "problemas"],
        "material_points": ["diagnostic"],
    },
    {
        "code": "inspecao",
        "name": "Inspeção técnica",
        "required": False,
        "required_fields": ["inspection_closed"],
        "optional_fields": ["inspection_summary", "inspection_reserve_reason"],
        "photo_requirements": ["non_conformities"],
        "document_requirements": [],
        "responsible_role": "technician",
        "transition_rules": ["inspection_completed_or_reserved"],
        "substeps": ["checklist", "pneus-travoes", "oleo-niveis", "saida-inspecao"],
        "material_points": ["inspection"],
    },
    {
        "code": "auditoria",
        "name": "Auditoria e validação",
        "required": False,
        "required_fields": ["audit_decision_main"],
        "optional_fields": ["audit_decision_reason", "audit_reserve_reason"],
        "photo_requirements": [],
        "document_requirements": [],
        "responsible_role": "workshop_manager",
        "transition_rules": ["audit_decided"],
        "substeps": ["evidencias", "coerencia", "decisao"],
        "material_points": [],
    },
    {
        "code": "reparacao",
        "name": "Reparação",
        "required": False,
        "required_fields": ["repair_execution_status"],
        "optional_fields": ["repair_summary", "repair_reserve_reason"],
        "photo_requirements": ["repair_photos"],
        "document_requirements": ["work_order"],
        "responsible_role": "technician",
        "transition_rules": ["repair_completed_or_reserved"],
        "substeps": ["ordem-reparacao", "execucao", "evidencias-reparacao", "desvios"],
        "material_points": ["repair"],
    },
    {
        "code": "fecho",
        "name": "Validação e fecho",
        "required": True,
        "required_fields": ["closure_result", "closure_vehicle_validated"],
        "optional_fields": ["closure_final_note"],
        "photo_requirements": ["dashboard_exit"],
        "document_requirements": ["final_work_order"],
        "responsible_role": "workshop_manager",
        "transition_rules": ["closure_conditions_met"],
        "substeps": ["validacao-final", "documentos-fecho", "pendencias-fecho", "encerramento"],
        "material_points": [],
    },
]


def _phase_subset(*codes: str) -> list[dict[str, Any]]:
    selected = set(codes)
    return [deepcopy(phase) for phase in BASE_PHASES if phase["code"] in selected]


DEFAULT_WORKSHOP_TEMPLATES = [
    {
        "code": "general_minimum",
        "name": "Modelo geral mínimo",
        "reason": None,
        "description": "Fallback seguro quando nenhuma regra específica corresponde.",
        "phases": _phase_subset("entrada", "validacao", "diagnostico", "fecho"),
        "diagnostics": [],
    },
    {
        "code": "scheduled_maintenance",
        "name": "Manutenção programada",
        "reason": "maintenance",
        "description": "Revisão, óleo e manutenção por plano.",
        "phases": _phase_subset(
            "entrada", "validacao", "diagnostico", "inspecao", "auditoria", "reparacao", "fecho"
        ),
        "diagnostics": ["maintenance_information", "maintenance_plan"],
    },
    {
        "code": "tires",
        "name": "Pneus",
        "reason": "tires",
        "description": "Inspeção e intervenção em pneus.",
        "phases": _phase_subset("entrada", "validacao", "inspecao", "reparacao", "fecho"),
        "diagnostics": [],
    },
    {
        "code": "brakes",
        "name": "Travões",
        "reason": "brakes",
        "description": "Diagnóstico, inspeção e reparação do sistema de travagem.",
        "phases": _phase_subset(
            "entrada", "validacao", "diagnostico", "inspecao", "reparacao", "fecho"
        ),
        "diagnostics": ["fault_reading"],
    },
    {
        "code": "breakdown",
        "name": "Avaria",
        "reason": "breakdown",
        "description": "Avaria ou aviso técnico sem causa confirmada.",
        "phases": _phase_subset(
            "entrada", "validacao", "diagnostico", "inspecao", "auditoria", "reparacao", "fecho"
        ),
        "diagnostics": ["fault_reading"],
    },
    {
        "code": "claim",
        "name": "Sinistro",
        "reason": "claim",
        "description": "Danos/sinistro com validação e reparação.",
        "phases": _phase_subset(
            "entrada", "validacao", "inspecao", "auditoria", "reparacao", "fecho"
        ),
        "diagnostics": [],
    },
    {
        "code": "ipo",
        "name": "IPO",
        "reason": "ipo",
        "description": "Preparação, inspeção e fecho de IPO.",
        "phases": _phase_subset("entrada", "validacao", "inspecao", "reparacao", "fecho"),
        "diagnostics": [],
    },
    {
        "code": "external_repair",
        "name": "Reparação externa",
        "reason": "external_repair",
        "description": "Intervenção executada por oficina externa com aprovação e documentos.",
        "phases": _phase_subset("entrada", "validacao", "auditoria", "reparacao", "fecho"),
        "diagnostics": [],
    },
]

DEFAULT_DIAGNOSTIC_CATALOG = [
    {
        "code": "maintenance_information",
        "name": "Informações de manutenção",
        "family": "maintenance",
        "equipment": "Equipamento de diagnóstico compatível",
        "requirement": "conditional",
        "applicability": {"reasons": ["maintenance"]},
        "validity_days": 30,
        "expected_document_type": "maintenance_information",
        "fields": ["km_last_maintenance_reset", "km_before_next_maintenance", "maintenance_count"],
    },
    {
        "code": "maintenance_plan",
        "name": "Plano de manutenção aplicável",
        "family": "maintenance",
        "equipment": "Service Box / fonte técnica do fabricante",
        "requirement": "conditional",
        "applicability": {
            "reasons": ["maintenance"],
            "brands": ["PEUGEOT", "CITROEN", "OPEL", "DS"],
        },
        "validity_days": 90,
        "expected_document_type": "maintenance_plan_validation",
        "fields": ["servicebox_plan", "servicebox_interval_km", "servicebox_due_date"],
    },
    {
        "code": "fault_reading",
        "name": "Leitura de defeitos",
        "family": "faults",
        "equipment": "Máquina de diagnóstico",
        "requirement": "recommended",
        "applicability": {"reasons": ["breakdown", "brakes"]},
        "validity_days": 7,
        "expected_document_type": "fault_reading",
        "fields": ["faults_found", "faults"],
    },
]

REASON_ALIASES = {
    "revisão / degradação óleo": "maintenance",
    "verificação de rotina": "maintenance",
    "pneus": "tires",
    "travões": "brakes",
    "danos / sinistro": "claim",
    "avaria": "breakdown",
    "ipo": "ipo",
    "reparação externa": "external_repair",
}


def normalize_workshop_reasons(reasons: list[str] | tuple[str, ...] | None) -> list[str]:
    normalized: list[str] = []
    for reason in reasons or ():
        code = REASON_ALIASES.get(str(reason).strip().casefold())
        if code and code not in normalized:
            normalized.append(code)
    return normalized


def validate_workshop_template_config(config: object) -> dict[str, Any]:
    """Validate the administrable JSON contract before publishing a version."""

    if not isinstance(config, dict):
        raise ValueError("A configuração do modelo deve ser um objeto JSON.")
    phases = config.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ValueError("A configuração deve incluir uma lista não vazia de fases.")
    phase_codes: list[str] = []
    for index, phase in enumerate(phases, start=1):
        if not isinstance(phase, dict):
            raise ValueError(f"A fase {index} deve ser um objeto JSON.")
        code = str(phase.get("code") or "").strip()
        name = str(phase.get("name") or "").strip()
        if not code or not name:
            raise ValueError(f"A fase {index} precisa de código e nome.")
        if code in phase_codes:
            raise ValueError(f"O código de fase {code!r} está repetido.")
        phase_codes.append(code)
        for key in (
            "required_fields",
            "optional_fields",
            "photo_requirements",
            "document_requirements",
            "transition_rules",
            "substeps",
            "material_points",
        ):
            if key in phase and not isinstance(phase[key], list):
                raise ValueError(f"O campo {key!r} da fase {code!r} deve ser uma lista.")
    if "entrada" not in phase_codes or "fecho" not in phase_codes:
        raise ValueError("O modelo deve manter as fases entrada e fecho.")
    diagnostic_codes = config.get("diagnostic_catalog_codes", [])
    if not isinstance(diagnostic_codes, list):
        raise ValueError("diagnostic_catalog_codes deve ser uma lista.")
    rules = config.get("rules", {})
    if not isinstance(rules, dict):
        raise ValueError("rules deve ser um objeto JSON.")
    normalized = deepcopy(config)
    normalized.setdefault("schema_version", 1)
    normalized.setdefault("diagnostic_catalog_codes", [])
    normalized.setdefault("rules", {})
    return normalized


def allocate_workshop_public_reference(
    db: Session,
    opened_at: datetime | None = None,
) -> str:
    """Allocate an annual reference with one atomic database increment."""

    moment = opened_at or datetime.now(UTC)
    year = moment.year
    try:
        with db.begin_nested():
            db.add(WorkshopPublicCounter(year=year, last_value=0))
            db.flush()
    except IntegrityError:
        # Another transaction already created the annual counter.
        pass

    sequence = db.scalar(
        update(WorkshopPublicCounter)
        .where(WorkshopPublicCounter.year == year)
        .values(last_value=WorkshopPublicCounter.last_value + 1)
        .returning(WorkshopPublicCounter.last_value)
    )
    if sequence is None:
        raise RuntimeError(f"Não foi possível reservar a sequência de Oficina para {year}.")
    return f"OF-{year}-{int(sequence):04d}"


def ensure_workshop_configuration_defaults(db: Session) -> None:
    now = datetime.now(UTC)
    for default in DEFAULT_WORKSHOP_TEMPLATES:
        template = db.scalar(
            select(WorkshopTemplate).where(WorkshopTemplate.code == default["code"])
        )
        if not template:
            template = WorkshopTemplate(
                code=default["code"],
                name=default["name"],
                description=default["description"],
                entry_reason_code=default["reason"],
                active=True,
            )
            db.add(template)
            db.flush()
        version = db.scalar(
            select(WorkshopTemplateVersion).where(
                WorkshopTemplateVersion.template_id == template.id,
                WorkshopTemplateVersion.version_number == 1,
            )
        )
        if not version:
            db.add(
                WorkshopTemplateVersion(
                    template_id=template.id,
                    version_number=1,
                    status="published",
                    change_note="Versão inicial CarFast.",
                    config_json={
                        "schema_version": 1,
                        "phases": default["phases"],
                        "diagnostic_catalog_codes": default["diagnostics"],
                        "rules": {
                            "reason_codes": [default["reason"]] if default["reason"] else [],
                            "fallback": default["code"] == "general_minimum",
                        },
                    },
                    published_at=now,
                )
            )

    for default in DEFAULT_DIAGNOSTIC_CATALOG:
        item = db.scalar(
            select(WorkshopDiagnosticCatalogItem).where(
                WorkshopDiagnosticCatalogItem.code == default["code"]
            )
        )
        if item:
            continue
        db.add(
            WorkshopDiagnosticCatalogItem(
                code=default["code"],
                name=default["name"],
                family=default["family"],
                equipment=default["equipment"],
                applicability_json=default["applicability"],
                phase_code="diagnostico",
                requirement=default["requirement"],
                validity_days=default["validity_days"],
                history_rules_json={"prefer_recent_validated": True},
                expected_document_type=default["expected_document_type"],
                extraction_fields_json=default["fields"],
                active=True,
            )
        )
    db.flush()


def latest_published_template_version(
    db: Session,
    template: WorkshopTemplate,
) -> WorkshopTemplateVersion | None:
    return db.scalar(
        select(WorkshopTemplateVersion)
        .where(
            WorkshopTemplateVersion.template_id == template.id,
            WorkshopTemplateVersion.status == "published",
        )
        .order_by(WorkshopTemplateVersion.version_number.desc())
    )


def suggest_workshop_template(
    db: Session,
    reasons: list[str] | None,
    *,
    external_repair: bool = False,
) -> tuple[WorkshopTemplate, WorkshopTemplateVersion, str]:
    ensure_workshop_configuration_defaults(db)
    reason_codes = normalize_workshop_reasons(reasons)
    if external_repair:
        reason_codes.insert(0, "external_repair")

    template: WorkshopTemplate | None = None
    matched_reason: str | None = None
    for reason_code in reason_codes:
        template = db.scalar(
            select(WorkshopTemplate).where(
                WorkshopTemplate.active.is_(True),
                WorkshopTemplate.entry_reason_code == reason_code,
            )
        )
        if template:
            matched_reason = reason_code
            break
    if not template:
        template = db.scalar(
            select(WorkshopTemplate).where(
                WorkshopTemplate.code == "general_minimum",
                WorkshopTemplate.active.is_(True),
            )
        )
    if not template:
        raise RuntimeError("O modelo geral mínimo de Oficina não está configurado.")
    version = latest_published_template_version(db, template)
    if not version:
        raise RuntimeError(f"O modelo {template.name} não tem uma versão publicada.")
    explanation = (
        f"Modelo sugerido pelo motivo normalizado «{matched_reason}»."
        if matched_reason
        else "Modelo geral mínimo aplicado por ausência de correspondência."
    )
    return template, version, explanation


def workshop_template_snapshot(
    template: WorkshopTemplate,
    version: WorkshopTemplateVersion,
    *,
    explanation: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "template_id": template.id,
        "template_code": template.code,
        "template_name": template.name,
        "version_id": version.id,
        "version_number": version.version_number,
        "applied_at": datetime.now(UTC).isoformat(),
        "explanation": explanation,
        "config": deepcopy(version.config_json or {}),
        "stock_template": {
            "code": version.stock_template_code,
            "version": version.stock_template_version,
            "ownership": "stock",
        },
    }


def apply_workshop_template(
    db: Session,
    process: WorkshopPhasedProcess,
    template: WorkshopTemplate,
    version: WorkshopTemplateVersion,
    *,
    explanation: str,
    started_at: datetime | None = None,
) -> None:
    """Apply a version once; the stored snapshot remains immutable afterwards."""

    if process.template_snapshot_json:
        raise ValueError("O processo já tem um snapshot de modelo aplicado.")
    snapshot = workshop_template_snapshot(template, version, explanation=explanation)
    process.template_version_id = version.id
    process.template_snapshot_json = snapshot
    moment = started_at or process.opened_at or datetime.now(UTC)
    phases = snapshot.get("config", {}).get("phases", [])
    for index, phase in enumerate(phases, start=1):
        code = str(phase.get("code") or "").strip()
        if not code:
            continue
        db.add(
            WorkshopPhasedProcessPhase(
                process_id=process.id,
                phase_code=code,
                name=str(phase.get("name") or code.replace("_", " ").title()),
                status="pending_review" if index == 1 else "not_started",
                sort_order=index,
                started_at=moment if index == 1 else None,
                data_json={"template_phase_snapshot": deepcopy(phase)},
            )
        )
    db.flush()


def _catalog_item_matches(
    item: WorkshopDiagnosticCatalogItem,
    vehicle: Vehicle | None,
    reason_codes: list[str],
) -> tuple[bool, list[str]]:
    rules = item.applicability_json or {}
    explanations: list[str] = []
    rule_reasons = {str(value) for value in rules.get("reasons", [])}
    if rule_reasons:
        matches = sorted(rule_reasons.intersection(reason_codes))
        if not matches:
            return False, []
        explanations.append(f"motivo: {', '.join(matches)}")
    if vehicle:
        comparisons = {
            "brands": vehicle.brand,
            "models": vehicle.model,
            "variants": vehicle.version,
        }
        for rule_key, actual in comparisons.items():
            accepted = [str(value).casefold() for value in rules.get(rule_key, [])]
            if not accepted:
                continue
            actual_text = str(actual or "").casefold()
            if not any(value in actual_text for value in accepted):
                return False, []
            explanations.append(f"{rule_key[:-1]}: {actual}")
    return True, explanations


def generate_diagnostic_suggestions(
    db: Session,
    process: WorkshopPhasedProcess,
    *,
    reason_codes: list[str],
) -> list[WorkshopDiagnosticSuggestion]:
    ensure_workshop_configuration_defaults(db)
    vehicle = db.get(Vehicle, process.vehicle_id) if process.vehicle_id else None
    configured_codes = set(
        (process.template_snapshot_json or {}).get("config", {}).get("diagnostic_catalog_codes", [])
    )
    suggestions: list[WorkshopDiagnosticSuggestion] = []
    for item in db.scalars(
        select(WorkshopDiagnosticCatalogItem).where(WorkshopDiagnosticCatalogItem.active.is_(True))
    ).all():
        matches, explanation_parts = _catalog_item_matches(item, vehicle, reason_codes)
        if item.code in configured_codes:
            matches = True
            explanation_parts.insert(0, "modelo aplicado")
        if not matches:
            continue
        existing = db.scalar(
            select(WorkshopDiagnosticSuggestion).where(
                WorkshopDiagnosticSuggestion.process_id == process.id,
                WorkshopDiagnosticSuggestion.catalog_item_id == item.id,
            )
        )
        if existing:
            suggestions.append(existing)
            continue
        explanation_source = ", ".join(explanation_parts) or "regra de aplicabilidade"
        suggestion = WorkshopDiagnosticSuggestion(
            process_id=process.id,
            catalog_item_id=item.id,
            status="suggested",
            origin="rules_engine",
            explanation=f"Sugerido por {explanation_source}.",
            rule_context_json={
                "reason_codes": reason_codes,
                "vehicle": {
                    "brand": vehicle.brand if vehicle else None,
                    "model": vehicle.model if vehicle else None,
                    "variant": vehicle.version if vehicle else None,
                },
                "template_version_id": process.template_version_id,
            },
        )
        db.add(suggestion)
        suggestions.append(suggestion)
    db.flush()
    return suggestions


def clone_published_template_version(
    db: Session,
    template: WorkshopTemplate,
    *,
    user_id: int | None,
    change_note: str,
    config_json: dict[str, Any] | None = None,
) -> WorkshopTemplateVersion:
    current = latest_published_template_version(db, template)
    if not current:
        raise ValueError("O modelo não tem uma versão publicada para clonar.")
    next_version = (
        db.scalar(
            select(func.max(WorkshopTemplateVersion.version_number)).where(
                WorkshopTemplateVersion.template_id == template.id
            )
        )
        or 0
    ) + 1
    version = WorkshopTemplateVersion(
        template_id=template.id,
        version_number=next_version,
        status="published",
        change_note=change_note.strip() or f"Versão {next_version}",
        config_json=validate_workshop_template_config(
            config_json if config_json is not None else current.config_json or {}
        ),
        published_at=datetime.now(UTC),
        published_by_id=user_id,
        stock_template_code=current.stock_template_code,
        stock_template_version=current.stock_template_version,
    )
    db.add(version)
    db.flush()
    return version
