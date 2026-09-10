from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.documents import (
    Document,
    DocumentEvent,
    DocumentWorkflowState,
    VehicleDocumentRecordTag,
)
from app.models.vehicles import Vehicle, VehicleIdentifier

EXPORT_CONTRACT_VERSION = "invoice-audit-readonly/1.1"
EXTRACTION_ACTIONS = {
    "invoice.ocr.extracted",
    "invoice.lines.extracted",
    "invoice.extracted",
}

DOCUMENT_COLUMNS = [
    "run_id",
    "document_id",
    "document_type",
    "classification",
    "status",
    "archived",
    "source",
    "entry_channel",
    "original_name",
    "file_name",
    "file_hash",
    "storage_provider",
    "storage_path",
    "storage_key",
    "folder_path",
    "external_url",
    "document_date_record",
    "document_date_extracted",
    "document_date_source",
    "document_number_record",
    "document_number_extracted",
    "document_number_source",
    "supplier_name_record",
    "supplier_name_extracted",
    "supplier_name_source",
    "supplier_group",
    "supplier_nif_extracted",
    "supplier_nif_source",
    "total_extracted",
    "total_source",
    "plate_record",
    "plate_extracted",
    "plate_source",
    "vin_extracted",
    "vin_source",
    "km_source",
    "work_order_source",
    "vehicle_id_associated",
    "association_confirmed",
    "vehicle_plate_associated",
    "vehicle_vin_associated",
    "vehicle_match_ids",
    "workflow_invoice_nature",
    "workflow_suggested_nature",
    "workflow_human_confirmed",
    "scope_document_nature",
    "scope_chain_id",
    "human_tags_json",
    "extraction_event_id",
    "extraction_event_at",
    "extraction_status_observed",
    "line_count",
    "technical_blocker",
    "human_protected",
    "human_protection_sources",
    "primary_queue",
    "eligible_for_service_proposal",
    "eligible_for_counting",
    "eligibility_reason",
    "duplicate_group_id",
    "duplicate_match_types",
    "issue_codes",
    "raw_extraction_json",
]

LINE_COLUMNS = [
    "run_id",
    "document_id",
    "source_line_id",
    "line_number",
    "description",
    "reference",
    "quantity",
    "unit_price",
    "line_total",
    "line_taxonomy_code",
    "line_role",
    "classification_rule",
    "classification_confidence",
    "raw_line_json",
]

SERVICE_COLUMNS = [
    "run_id",
    "document_id",
    "visit_id",
    "service_event_id",
    "parent_service_event_id",
    "event_taxonomy_code",
    "evidence_line_ids",
    "classification_rule",
    "confidence",
    "proposal_status",
    "eligible_for_counting",
    "eligibility_reason",
]

ISSUE_COLUMNS = [
    "run_id",
    "document_id",
    "issue_code",
    "severity",
    "source",
    "evidence",
    "recommended_queue",
]


@dataclass(slots=True)
class ExportBundle:
    documents: list[dict[str, Any]]
    lines: list[dict[str, Any]]
    services: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    manifest: dict[str, Any]


def _token(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "").strip().lower())
    return "".join(char for char in text if char.isalnum() and not unicodedata.combining(char))


def _digits(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "sim", "y"}


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in re.split(r"[;,|\n]", str(value)) if item.strip()]


def _payload(event: DocumentEvent | None) -> dict[str, Any]:
    if not event:
        return {}
    try:
        value = json.loads(event.new_value or "")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    if isinstance(value, list):
        return {"invoice_lines": value}
    return value if isinstance(value, dict) else {}


def _invoice_lines(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("invoice_lines") or payload.get("lines") or []
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if row.get(key) not in (None, ""):
            return row[key]
    return None


def _supplier_group(name: Any, nif: Any) -> str:
    normalized = _token(name)
    if ("baia" in normalized and "filho" in normalized) or (
        "cruz" in normalized and "allen" in normalized
    ):
        return "BAIA_FILHO_CRUZ_ALLEN"
    nif_digits = _digits(nif)
    return f"NIF:{nif_digits}" if nif_digits else normalized.upper()


def _normalize_plate(value: Any) -> str:
    token = _token(value).upper()
    return token if 5 <= len(token) <= 8 else ""


def _normalize_vin(value: Any) -> str:
    token = _token(value).upper()
    return token if len(token) == 17 else ""


def _classify_line(description: Any) -> tuple[str, str, str, float]:
    text = _token(description)
    rules = [
        ("LINE.NOISE", "LINE.NOISE", "noise_heading", 0.99, ("subtotal", "capitalsocial")),
        ("LINE.FEE", "LINE.FEE", "environmental_fee", 0.99, ("ecolub", "sigou")),
        (
            "TYRE.REPAIR",
            "LINE.LABOR",
            "puncture_explicit",
            0.99,
            ("reparacaodefuro", "repararfuro"),
        ),
        ("EMISSION.DPF", "LINE.PART", "dpf_explicit", 0.98, ("filtrodeparticulas", "fap", "dpf")),
        (
            "BRAKE.FLUID",
            "LINE.FLUID",
            "brake_fluid_explicit",
            0.99,
            ("fluidodetravoes", "oleodetravoes"),
        ),
        (
            "FILTER.CABIN",
            "LINE.PART",
            "cabin_filter_explicit",
            0.99,
            ("filtrodehabitaculo", "filtropolen"),
        ),
        (
            "FILTER.FUEL",
            "LINE.PART",
            "fuel_filter_explicit",
            0.99,
            ("filtrodecombustivel", "filtrogasoleo"),
        ),
        ("FILTER.AIR", "LINE.PART", "air_filter_explicit", 0.98, ("filtrodear",)),
        ("FILTER.OIL", "LINE.PART", "oil_filter_explicit", 0.99, ("filtrodeoleo",)),
        ("BRAKE.DISC", "LINE.PART", "brake_disc_explicit", 0.98, ("discotrav", "discosdetrav")),
        ("BRAKE.PAD", "LINE.PART", "brake_pad_explicit", 0.98, ("calcos", "pastilhastrav")),
        ("TYRE.REPLACE", "LINE.PART", "tyre_explicit", 0.96, ("pneu",)),
        (
            "FLUID.ENGINE_OIL",
            "LINE.FLUID",
            "engine_oil_explicit",
            0.96,
            ("oleomotor", "0w20", "0w30", "5w30", "5w40"),
        ),
        (
            "MAINT.PLAN.EXPLICIT",
            "LINE.LABOR",
            "maintenance_explicit",
            0.98,
            ("revisao", "manutencaoprogramada", "operacoessistematicas"),
        ),
    ]
    for code, role, rule, confidence, terms in rules:
        if any(term in text for term in terms):
            return code, role, rule, confidence
    if any(term in text for term in ("maodeobra", "mobra", "servico")):
        return "UNCLASSIFIED", "LINE.LABOR", "generic_labor", 0.50
    return "UNCLASSIFIED", "LINE.UNKNOWN", "no_rule", 0.0


def _service_proposals(
    run_id: str,
    document_id: int,
    classified_lines: list[dict[str, Any]],
    eligible: bool,
    eligibility_reason: str,
) -> list[dict[str, Any]]:
    by_code: dict[str, list[str]] = defaultdict(list)
    for row in classified_lines:
        code = str(row["line_taxonomy_code"])
        if code not in {"UNCLASSIFIED", "LINE.NOISE", "LINE.FEE"}:
            by_code[code].append(str(row["source_line_id"]))

    proposals: list[tuple[str, list[str], str, float, str]] = []
    periodic = {"FILTER.AIR", "FILTER.FUEL", "FILTER.CABIN", "BRAKE.FLUID"}
    has_oil_bundle = "FLUID.ENGINE_OIL" in by_code and "FILTER.OIL" in by_code
    if "MAINT.PLAN.EXPLICIT" in by_code or (has_oil_bundle and periodic.intersection(by_code)):
        evidence = []
        for code in ("MAINT.PLAN.EXPLICIT", "FLUID.ENGINE_OIL", "FILTER.OIL", *sorted(periodic)):
            evidence.extend(by_code.get(code, []))
        proposals.append(("MAINT.PLAN", evidence, "maintenance_plan_bundle_v1", 0.98, ""))
    elif has_oil_bundle:
        evidence = by_code["FLUID.ENGINE_OIL"] + by_code["FILTER.OIL"]
        proposals.append(("MAINT.OIL_INTERIM", evidence, "oil_filter_only_v1", 0.97, ""))

    for code in sorted(by_code):
        if code in {
            "MAINT.PLAN.EXPLICIT",
            "FLUID.ENGINE_OIL",
            "FILTER.OIL",
            "LINE.NOISE",
            "LINE.FEE",
        }:
            continue
        parent = (
            "MAINT.PLAN"
            if code in periodic and any(p[0] == "MAINT.PLAN" for p in proposals)
            else ""
        )
        confidence = min(
            float(row["classification_confidence"])
            for row in classified_lines
            if row["line_taxonomy_code"] == code
        )
        proposals.append((code, by_code[code], "line_evidence_v1", confidence, parent))

    result = []
    for index, (code, evidence, rule, confidence, parent_code) in enumerate(proposals, start=1):
        result.append(
            {
                "run_id": run_id,
                "document_id": document_id,
                "visit_id": f"VIS-{document_id}",
                "service_event_id": f"EV-{document_id}-{index:02d}",
                "parent_service_event_id": (
                    f"EV-{document_id}-01" if parent_code == "MAINT.PLAN" else ""
                ),
                "event_taxonomy_code": code,
                "evidence_line_ids": "|".join(evidence),
                "classification_rule": rule,
                "confidence": f"{confidence:.2f}",
                "proposal_status": "PROPOSED" if eligible else "PROVISIONAL_BLOCKED",
                "eligible_for_counting": eligible,
                "eligibility_reason": eligibility_reason,
            }
        )
    return result


def _issue(
    run_id: str,
    document_id: int,
    code: str,
    severity: str,
    source: str,
    evidence: str,
    queue: str,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "document_id": document_id,
        "issue_code": code,
        "severity": severity,
        "source": source,
        "evidence": evidence,
        "recommended_queue": queue,
    }


def build_readonly_export(
    db: Session,
    scope_rows: Iterable[dict[str, Any]],
    *,
    run_id: str,
    historical_plates: Iterable[str] = (),
    expected_documents: int | None = None,
    expected_blockers: int | None = None,
    expected_human_protected: int | None = None,
    source_revision: str = "unknown",
    taxonomy_version: str = "1.1.0-draft",
) -> ExportBundle:
    """Build an export using SELECTs only; this function never flushes or commits."""

    scope = {int(row["document_id"]): dict(row) for row in scope_rows}
    document_ids = sorted(scope)
    documents = (
        list(
            db.scalars(select(Document).where(Document.id.in_(document_ids)).order_by(Document.id))
        )
        if document_ids
        else []
    )
    found_ids = {document.id for document in documents}

    events_by_document: dict[int, list[DocumentEvent]] = defaultdict(list)
    workflows: dict[int, DocumentWorkflowState] = {}
    tags_by_document: dict[int, list[VehicleDocumentRecordTag]] = defaultdict(list)
    if document_ids:
        events = db.scalars(
            select(DocumentEvent)
            .where(DocumentEvent.document_id.in_(document_ids))
            .order_by(DocumentEvent.document_id, DocumentEvent.id.desc())
        ).all()
        for event in events:
            events_by_document[event.document_id].append(event)
        workflows = {
            row.document_id: row
            for row in db.scalars(
                select(DocumentWorkflowState).where(
                    DocumentWorkflowState.document_id.in_(document_ids)
                )
            ).all()
        }
        for tag in db.scalars(
            select(VehicleDocumentRecordTag).where(
                VehicleDocumentRecordTag.document_id.in_(document_ids)
            )
        ).all():
            tags_by_document[tag.document_id].append(tag)

    vehicles = db.scalars(select(Vehicle)).all()
    vehicle_by_id = {vehicle.id: vehicle for vehicle in vehicles}
    vehicle_ids_by_plate: dict[str, set[int]] = defaultdict(set)
    vehicle_ids_by_vin: dict[str, set[int]] = defaultdict(set)
    for vehicle in vehicles:
        if plate := _normalize_plate(vehicle.plate):
            vehicle_ids_by_plate[plate].add(vehicle.id)
        if vin := _normalize_vin(vehicle.vin):
            vehicle_ids_by_vin[vin].add(vehicle.id)
    for identifier in db.scalars(
        select(VehicleIdentifier).where(VehicleIdentifier.active.is_(True))
    ):
        if identifier.identifier_type == "plate" and (
            plate := _normalize_plate(identifier.identifier_value)
        ):
            vehicle_ids_by_plate[plate].add(identifier.vehicle_id)
        if identifier.identifier_type == "vin" and (
            vin := _normalize_vin(identifier.identifier_value)
        ):
            vehicle_ids_by_vin[vin].add(identifier.vehicle_id)
    historic = {_normalize_plate(value) for value in historical_plates if _normalize_plate(value)}

    document_rows: list[dict[str, Any]] = []
    line_rows: list[dict[str, Any]] = []
    issue_rows: list[dict[str, Any]] = []
    service_rows: list[dict[str, Any]] = []
    duplicate_keys: dict[tuple[str, str], list[int]] = defaultdict(list)

    for missing_id in sorted(set(document_ids) - found_ids):
        issue_rows.append(
            _issue(
                run_id,
                missing_id,
                "SCOPE_DOCUMENT_NOT_FOUND",
                "critical",
                "scope",
                "ID absent from documents",
                "BLOCKED",
            )
        )

    for document in documents:
        scope_row = scope[document.id]
        extraction_event = next(
            (
                event
                for event in events_by_document[document.id]
                if event.action in EXTRACTION_ACTIONS
            ),
            None,
        )
        payload = _payload(extraction_event)
        invoice_lines = _invoice_lines(payload)
        workflow = workflows.get(document.id)
        human_tags = [
            {
                "tag_id": tag.id,
                "category": tag.category,
                "value": tag.value,
                "free_text": tag.free_text,
                "source_kind": tag.source_kind,
            }
            for tag in sorted(tags_by_document[document.id], key=lambda item: item.id)
        ]

        number_extracted = _first(payload, "document_number", "invoice_number")
        number = number_extracted or document.contract_number
        supplier_name_extracted = _first(payload, "supplier_name", "supplier")
        supplier_name = supplier_name_extracted or document.supplier_name
        supplier_nif = _first(payload, "supplier_nif", "nif")
        total = _first(payload, "total_with_vat", "total_amount", "total")
        plate_extracted = _first(payload, "plate", "registration", "matricula")
        vin_extracted = _first(payload, "vin", "chassis", "chassis_number")
        plate_values = _as_list(plate_extracted or document.plate)
        vin_values = _as_list(vin_extracted)
        plates = sorted(
            {_normalize_plate(value) for value in plate_values if _normalize_plate(value)}
        )
        vins = sorted({_normalize_vin(value) for value in vin_values if _normalize_vin(value)})
        match_ids: set[int] = set()
        for plate in plates:
            match_ids.update(vehicle_ids_by_plate.get(plate, set()))
        for vin in vins:
            match_ids.update(vehicle_ids_by_vin.get(vin, set()))

        authoritative_blocker = _as_bool(scope_row.get("technical_blocker"))
        authoritative_human = _as_bool(scope_row.get("human_protected"))
        protection_sources = []
        if authoritative_human:
            protection_sources.append("official_scope_blocker_overlap")
        if workflow and workflow.human_confirmed:
            protection_sources.append("workflow_human_confirmed")
        automated_tag_sources = {"automatic", "auto", "system", "ai", "model"}
        if any(_token(tag.get("source_kind")) not in automated_tag_sources for tag in human_tags):
            protection_sources.append("human_record_tag")
        human_protected = bool(protection_sources)
        issue_codes = set(_as_list(scope_row.get("blocker_codes") or scope_row.get("issue_codes")))
        scope_nature = str(scope_row.get("document_nature") or "").strip().lower()
        chain_natures = {
            "credit",
            "credit_note",
            "estorno",
            "nota_credito",
            "refaturacao",
            "replacement",
            "substituta",
        }
        if scope_nature in chain_natures:
            issue_codes.add("DOCUMENT_CHAIN_UNRESOLVED")
            issue_rows.append(
                _issue(
                    run_id,
                    document.id,
                    "DOCUMENT_CHAIN_UNRESOLVED",
                    "critical",
                    "scope",
                    f"nature={scope_nature}",
                    "DUPLICATE_CHAIN",
                )
            )
        if not extraction_event or not payload:
            issue_codes.add("MISSING_EXTRACTION")
            issue_rows.append(
                _issue(
                    run_id,
                    document.id,
                    "MISSING_EXTRACTION",
                    "critical",
                    "observed",
                    "No valid extraction payload",
                    "REEXTRACT_PARSER",
                )
            )
        elif not invoice_lines:
            issue_codes.add("NO_EXTRACTED_LINES")
            issue_rows.append(
                _issue(
                    run_id,
                    document.id,
                    "NO_EXTRACTED_LINES",
                    "critical",
                    "observed",
                    "Extraction payload has no invoice lines",
                    "REEXTRACT_PARSER",
                )
            )
        if len(plates) > 1 or len(vins) > 1:
            issue_codes.add("MULTIPLE_VEHICLE_IDENTIFIERS")
            issue_rows.append(
                _issue(
                    run_id,
                    document.id,
                    "MULTIPLE_VEHICLE_IDENTIFIERS",
                    "critical",
                    "observed",
                    f"plates={plates}; vins={vins}",
                    "BLOCKED",
                )
            )
        if len(match_ids) > 1:
            issue_codes.add("VEHICLE_IDENTITY_CONFLICT")
            issue_rows.append(
                _issue(
                    run_id,
                    document.id,
                    "VEHICLE_IDENTITY_CONFLICT",
                    "critical",
                    "observed",
                    f"vehicle_ids={sorted(match_ids)}",
                    "BLOCKED",
                )
            )
        if plates and not any(
            plate in vehicle_ids_by_plate or plate in historic for plate in plates
        ):
            issue_codes.add("UNKNOWN_PLATE")
            issue_rows.append(
                _issue(
                    run_id,
                    document.id,
                    "UNKNOWN_PLATE",
                    "warning",
                    "observed",
                    f"plates={plates}",
                    "HUMAN_REVIEW",
                )
            )
        if vins and not plates:
            issue_codes.add("VIN_WITHOUT_PLATE")
            issue_rows.append(
                _issue(
                    run_id,
                    document.id,
                    "VIN_WITHOUT_PLATE",
                    "warning",
                    "observed",
                    f"vins={vins}",
                    "HUMAN_REVIEW",
                )
            )

        extracted_status = "usable" if payload and invoice_lines else "missing_or_empty"
        associated_vehicle = vehicle_by_id.get(document.vehicle_id)
        association_confirmed = bool(
            document.vehicle_id and workflow and workflow.association_status == "associated"
        )
        document_row = {
            "run_id": run_id,
            "document_id": document.id,
            "document_type": document.document_type or "",
            "classification": document.classification or "",
            "status": document.status or "",
            "archived": bool(document.archived),
            "source": document.source or "",
            "entry_channel": document.entry_channel or "",
            "original_name": document.original_name,
            "file_name": document.file_name,
            "file_hash": document.file_hash or "",
            "storage_provider": document.storage_provider,
            "storage_path": document.storage_path,
            "storage_key": document.storage_key or "",
            "folder_path": document.folder_path or "",
            "external_url": document.external_url or "",
            "document_date_record": document.document_date or "",
            "document_date_extracted": _first(payload, "document_date", "invoice_date") or "",
            "document_date_source": _first(payload, "document_date", "invoice_date")
            or document.document_date
            or "",
            "document_number_record": document.contract_number or "",
            "document_number_extracted": number_extracted or "",
            "document_number_source": number or "",
            "supplier_name_record": document.supplier_name or "",
            "supplier_name_extracted": supplier_name_extracted or "",
            "supplier_name_source": supplier_name or "",
            "supplier_group": _supplier_group(supplier_name, supplier_nif),
            "supplier_nif_extracted": supplier_nif or "",
            "supplier_nif_source": supplier_nif or "",
            "total_extracted": total or "",
            "total_source": total or "",
            "plate_record": document.plate or "",
            "plate_extracted": plate_extracted or "",
            "plate_source": "|".join(plates),
            "vin_extracted": vin_extracted or "",
            "vin_source": "|".join(vins),
            "km_source": _first(payload, "km", "odometer_km", "mileage") or "",
            "work_order_source": _first(
                payload, "work_order_reference", "repair_order_reference", "work_order"
            )
            or "",
            "vehicle_id_associated": document.vehicle_id or "",
            "association_confirmed": association_confirmed,
            "vehicle_plate_associated": associated_vehicle.plate if associated_vehicle else "",
            "vehicle_vin_associated": associated_vehicle.vin if associated_vehicle else "",
            "vehicle_match_ids": "|".join(str(value) for value in sorted(match_ids)),
            "workflow_invoice_nature": workflow.invoice_nature if workflow else "",
            "workflow_suggested_nature": workflow.suggested_invoice_nature if workflow else "",
            "workflow_human_confirmed": bool(workflow and workflow.human_confirmed),
            "scope_document_nature": scope_nature,
            "scope_chain_id": scope_row.get("chain_id") or "",
            "human_tags_json": _json(human_tags),
            "extraction_event_id": extraction_event.id if extraction_event else "",
            "extraction_event_at": extraction_event.created_at if extraction_event else "",
            "extraction_status_observed": extracted_status,
            "line_count": len(invoice_lines),
            "technical_blocker": authoritative_blocker,
            "human_protected": human_protected,
            "human_protection_sources": "|".join(protection_sources),
            "primary_queue": "",
            "eligible_for_service_proposal": False,
            "eligible_for_counting": False,
            "eligibility_reason": "",
            "duplicate_group_id": "",
            "duplicate_match_types": "",
            "issue_codes": "",
            "raw_extraction_json": _json(payload),
        }
        document_rows.append(document_row)

        if document.file_hash:
            duplicate_keys[("file_hash", _token(document.file_hash))].append(document.id)
        nif_number = f"{_digits(supplier_nif)}:{_token(number)}"
        if _digits(supplier_nif) and _token(number):
            duplicate_keys[("nif_number", nif_number)].append(document.id)
        fingerprint = ":".join(
            (
                _supplier_group(supplier_name, supplier_nif),
                _token(number),
                _token(document_row["document_date_source"]),
                _token(total),
            )
        )
        if (
            supplier_name
            and number
            and document_row["document_date_source"]
            and total not in (None, "")
        ):
            duplicate_keys[("economic_fingerprint", fingerprint)].append(document.id)

        classified_for_document = []
        for number_index, line in enumerate(invoice_lines, start=1):
            description = _first(line, "description", "descricao", "text") or ""
            code, role, rule, confidence = _classify_line(description)
            line_row = {
                "run_id": run_id,
                "document_id": document.id,
                "source_line_id": f"{document.id}:{number_index}",
                "line_number": number_index,
                "description": description,
                "reference": _first(line, "reference", "referencia", "code") or "",
                "quantity": _first(line, "quantity", "qtd") or "",
                "unit_price": _first(line, "unit_price", "preco_unitario", "price_unit", "pv_unit")
                or "",
                "line_total": _first(line, "line_total", "total", "amount", "value") or "",
                "line_taxonomy_code": code,
                "line_role": role,
                "classification_rule": rule,
                "classification_confidence": f"{confidence:.2f}",
                "raw_line_json": _json(line),
            }
            line_rows.append(line_row)
            classified_for_document.append(line_row)
        document_row["_classified_lines"] = classified_for_document
        document_row["_issue_codes"] = issue_codes

    duplicate_groups: dict[int, tuple[str, set[str]]] = {}
    group_number = 0
    grouped_sets: dict[frozenset[int], set[str]] = defaultdict(set)
    for (match_type, _), ids in duplicate_keys.items():
        unique_ids = frozenset(ids)
        if len(unique_ids) > 1:
            grouped_sets[unique_ids].add(match_type)
    for ids, match_types in sorted(grouped_sets.items(), key=lambda item: sorted(item[0])):
        group_number += 1
        group_id = f"DG-{run_id}-{group_number:04d}"
        for document_id in ids:
            previous = duplicate_groups.get(document_id)
            if previous:
                group_id = previous[0]
                previous[1].update(match_types)
            else:
                duplicate_groups[document_id] = (group_id, set(match_types))

    for row in document_rows:
        document_id = int(row["document_id"])
        issue_codes: set[str] = row.pop("_issue_codes")
        classified_lines = row.pop("_classified_lines")
        if document_id in duplicate_groups:
            group_id, match_types = duplicate_groups[document_id]
            row["duplicate_group_id"] = group_id
            row["duplicate_match_types"] = "|".join(sorted(match_types))
            issue_codes.add("DUPLICATE_CHAIN_UNRESOLVED")
            issue_rows.append(
                _issue(
                    run_id,
                    document_id,
                    "DUPLICATE_CHAIN_UNRESOLVED",
                    "critical",
                    "observed",
                    f"group={group_id}; match={sorted(match_types)}",
                    "DUPLICATE_CHAIN",
                )
            )

        observed_hard_block = bool(
            issue_codes.intersection(
                {
                    "MISSING_EXTRACTION",
                    "NO_EXTRACTED_LINES",
                    "MULTIPLE_VEHICLE_IDENTIFIERS",
                    "VEHICLE_IDENTITY_CONFLICT",
                }
            )
        )
        is_duplicate = "DUPLICATE_CHAIN_UNRESOLVED" in issue_codes
        if is_duplicate or "DOCUMENT_CHAIN_UNRESOLVED" in issue_codes:
            queue = "DUPLICATE_CHAIN"
        elif "MISSING_EXTRACTION" in issue_codes or "NO_EXTRACTED_LINES" in issue_codes:
            queue = "REEXTRACT_PARSER"
        elif row["technical_blocker"] or observed_hard_block:
            queue = "BLOCKED"
        elif issue_codes:
            queue = "HUMAN_REVIEW"
        else:
            queue = "AUTO_HIGH"
        eligible_for_proposal = bool(row["line_count"] and not observed_hard_block)
        eligibility_reasons = []
        if not row["association_confirmed"] or not row["vehicle_id_associated"]:
            eligibility_reasons.append("association_not_confirmed")
        if row["human_protected"]:
            eligibility_reasons.append("human_protected")
        if is_duplicate or "DOCUMENT_CHAIN_UNRESOLVED" in issue_codes:
            eligibility_reasons.append("duplicate_or_chain_blocked")
        if row["technical_blocker"] or observed_hard_block:
            eligibility_reasons.append("technical_blocker")
        if queue != "AUTO_HIGH" and not eligibility_reasons:
            eligibility_reasons.append("manual_review_required")
        eligibility_reason = "|".join(eligibility_reasons)
        eligible_for_counting = not eligibility_reasons
        row["primary_queue"] = queue
        row["eligible_for_service_proposal"] = eligible_for_proposal
        row["eligible_for_counting"] = eligible_for_counting
        row["eligibility_reason"] = eligibility_reason
        row["issue_codes"] = "|".join(sorted(issue_codes))
        if eligible_for_proposal:
            service_rows.extend(
                _service_proposals(
                    run_id,
                    document_id,
                    classified_lines,
                    eligible_for_counting,
                    eligibility_reason,
                )
            )

    counts = {
        "scope_documents": len(scope),
        "documents_exported": len(document_rows),
        "scope_documents_missing": len(set(document_ids) - found_ids),
        "lines_exported": len(line_rows),
        "services_proposed": len(service_rows),
        "technical_blockers": sum(_as_bool(row.get("technical_blocker")) for row in scope.values()),
        "human_protected": sum(_as_bool(row.get("human_protected")) for row in scope.values()),
        "human_protected_observed": sum(bool(row["human_protected"]) for row in document_rows),
    }
    expected = {
        "scope_documents": expected_documents,
        "technical_blockers": expected_blockers,
        "human_protected": expected_human_protected,
    }
    mismatches = {
        key: {"expected": expected_value, "actual": counts[key]}
        for key, expected_value in expected.items()
        if expected_value is not None and counts[key] != expected_value
    }
    manifest = {
        "contract_version": EXPORT_CONTRACT_VERSION,
        "run_id": run_id,
        "snapshot_at": datetime.now(UTC).isoformat(),
        "mode": "read_only",
        "source_revision": source_revision,
        "taxonomy_version": taxonomy_version,
        "scope_authority": "nominal_scope_csv",
        "counts": counts,
        "expected_counts": expected,
        "count_mismatches": mismatches,
        "acceptance_passed": not mismatches and counts["scope_documents_missing"] == 0,
        "columns": {
            "documents.csv": DOCUMENT_COLUMNS,
            "lines.csv": LINE_COLUMNS,
            "services.csv": SERVICE_COLUMNS,
            "issues.csv": ISSUE_COLUMNS,
        },
        "database_writes": 0,
    }
    manifest["content_sha256"] = hashlib.sha256(
        _json(
            {
                "documents": document_rows,
                "lines": line_rows,
                "services": service_rows,
                "issues": issue_rows,
            }
        ).encode("utf-8")
    ).hexdigest()
    return ExportBundle(document_rows, line_rows, service_rows, issue_rows, manifest)


def reconcile_scope_rows(
    old_rows: Iterable[dict[str, Any]], current_rows: Iterable[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Reconcile snapshots only by stable document_id; never infer a removal reason."""

    old = {int(row["document_id"]): dict(row) for row in old_rows}
    current = {int(row["document_id"]): dict(row) for row in current_rows}
    output = []
    for document_id in sorted(set(old) | set(current)):
        old_row = old.get(document_id)
        current_row = current.get(document_id)
        if old_row and current_row:
            state = "common"
        elif old_row:
            state = "old_only_reason_unproven"
        else:
            state = "current_only_reason_unproven"
        output.append(
            {
                "document_id": document_id,
                "reconciliation_state": state,
                "reason_code": "",
                "reason_evidence": "",
                "old_row_json": _json(old_row or {}),
                "current_row_json": _json(current_row or {}),
            }
        )
    common = len(set(old) & set(current))
    counts = {
        "old_total": len(old),
        "current_total": len(current),
        "common": common,
        "old_only": len(set(old) - set(current)),
        "current_only": len(set(current) - set(old)),
        "net_difference": len(old) - len(current),
    }
    assert counts["common"] + counts["old_only"] == counts["old_total"]
    assert counts["common"] + counts["current_only"] == counts["current_total"]
    assert counts["old_only"] - counts["current_only"] == counts["net_difference"]
    return output, counts
