import csv
import hashlib
import io
import json
import shutil
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.imports import ImportBatch, ImportError, ImportFile, ImportRawRow
from app.models.management_center import (
    ClaimIncident,
    ClaimRefstroLine,
    ClaimRentwayAR,
    ManagementAction,
    ManagementHistory,
    ManagementProcess,
    ManagementProcessAssociation,
    ManagementProcessType,
    ManagementRule,
)
from app.services.audit import record_audit
from app.services.spreadsheets import (
    build_column_lookup,
    clean_text,
    excel_date_to_iso,
    first_row_value,
    iter_xlsx_rows,
    normalize_header,
)

MANAGEMENT_CENTER_TYPE_CODE = "claims_ar"
MANAGEMENT_CENTER_TYPE_NAME = "Sinistros / AR"
MANAGEMENT_CENTER_SOURCE_SYSTEM = "carfast_management_center"
AR_IMPORT_TYPE = "claims_ar_rentway_ar"
REFSTRO_IMPORT_TYPE = "claims_ar_refstro"
MANAGEMENT_STORAGE_DIR = Path("data/imports/management_center")

PROCESS_STATUS_LABELS = {
    "open": "Aberto",
    "waiting": "A aguardar",
    "information_request": "Pedido de informação",
    "analysis": "Em análise",
    "internal_closed": "Fechado internamente",
}

PROCESS_PHASE_LABELS = {
    "information_request": "Pedido de informação",
    "ar_missing": "AR em falta",
    "analysis": "Em análise",
    "rentway_closed_review": "Fechado Rentway em validação interna",
    "internal_closed": "Fechado internamente",
}

ACTION_STATUS_LABELS = {
    "open": "Aberta",
    "done": "Concluída",
    "cancelled": "Cancelada",
}

CLAIM_COMPONENT_ALIASES = {
    "rc": "RC",
    "responsabilidade civil": "RC",
    "dp": "DP",
    "danos proprios": "DP",
    "danos próprios": "DP",
    "ids credor": "IDS Credor",
    "ids": "IDS Credor",
    "vidros": "Vidros",
    "glass": "Vidros",
    "custos de gestao": "Custos de Gestão",
    "custos de gestão": "Custos de Gestão",
    "gestao": "Custos de Gestão",
    "gestão": "Custos de Gestão",
}

MANAGEMENT_RULE_DEFINITIONS = [
    (
        "internal_sin_reference",
        "Referência SIN obrigatória",
        "Cada sinistro acompanhado pela CarFast tem uma referência interna única independente do AR.",
        "info",
    ),
    (
        "missing_ar_action",
        "AR em falta exige ação",
        "Quando há sinistro identificado sem AR ativo associado, o processo fica em AR em falta e abre ação obrigatória.",
        "critical",
    ),
    (
        "status_uses_ar_status",
        "Status operacional usa Status",
        "O campo Status dos ARs alimenta a fase operacional; o campo state do export fica apenas como bruto.",
        "warning",
    ),
    (
        "rentway_closed_not_internal",
        "Fecho Rentway não fecha internamente",
        "Um AR fechado no Rentway passa a validação interna, mas não fecha automaticamente o processo CarFast.",
        "warning",
    ),
    (
        "same_plate_date_consolidates",
        "Matrícula e data consolidam",
        "Linhas REFSTRO com a mesma matrícula e data são consolidadas num único SIN com componentes separados.",
        "info",
    ),
    (
        "minimum_data_information_request",
        "Sem mínimos há pedido de informação",
        "Sem matrícula ou data suficientes não há alerta operacional; o processo fica como pedido de informação.",
        "info",
    ),
]


def normalize_plate(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return text.upper().replace(" ", "").replace("-", "")


def normalize_component(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    return CLAIM_COMPONENT_ALIASES.get(text.casefold(), text[:120])


def parse_date_value(value: Any) -> date | None:
    iso = excel_date_to_iso(value)
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


def parse_decimal_value(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)).quantize(Decimal("0.01"))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("€", "").replace(" ", "")
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    else:
        text = text.replace(",", ".")
    try:
        return Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def row_hash(raw: dict[str, Any]) -> str:
    raw_json = json.dumps(raw, ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha1(raw_json.encode("utf-8")).hexdigest()


def management_storage_root() -> Path:
    MANAGEMENT_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return MANAGEMENT_STORAGE_DIR


def store_management_upload(source_path: Path, original_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in original_name)[:120]
    target = management_storage_root() / "pending" / f"{timestamp}_{safe_name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target)
    return target


def iter_management_rows(path: str | Path):
    file_path = Path(path)
    if file_path.suffix.lower() == ".csv":
        raw_bytes = file_path.read_bytes()
        try:
            text = raw_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw_bytes.decode("cp1252")
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        for row_number, raw in enumerate(reader, start=2):
            row = tuple(raw.get(header) for header in headers)
            yield "CSV", headers, row_number, row, raw
        return
    yield from iter_xlsx_rows(file_path)


def mapped_value(row: tuple[Any, ...], col: dict[str, int], aliases: list[str]) -> Any:
    normalized_aliases = [normalize_header(alias) for alias in aliases]
    return first_row_value(row, col, [*aliases, *normalized_aliases])


def ensure_management_defaults(db: Session) -> ManagementProcessType:
    process_type = db.scalar(
        select(ManagementProcessType).where(ManagementProcessType.code == MANAGEMENT_CENTER_TYPE_CODE)
    )
    if not process_type:
        process_type = ManagementProcessType(
            code=MANAGEMENT_CENTER_TYPE_CODE,
            name=MANAGEMENT_CENTER_TYPE_NAME,
            description="Processos de acompanhamento de sinistros, ARs Rentway e REFSTROs.",
            active=True,
        )
        db.add(process_type)
        db.flush()
    existing_rules = {
        rule.code
        for rule in db.scalars(select(ManagementRule).where(ManagementRule.process_type_id == process_type.id))
    }
    for code, title, description, severity in MANAGEMENT_RULE_DEFINITIONS:
        if code not in existing_rules:
            db.add(
                ManagementRule(
                    process_type_id=process_type.id,
                    code=code,
                    title=title,
                    description=description,
                    severity=severity,
                    active=True,
                )
            )
    return process_type


def next_sin_reference(db: Session, reference_year: int) -> str:
    sequence = (
        db.scalar(
            select(func.count())
            .select_from(ClaimIncident)
            .where(ClaimIncident.sin_reference.like(f"SIN-{reference_year}-%"))
        )
        or 0
    ) + 1
    while True:
        reference = f"SIN-{reference_year}-{sequence:06d}"
        if not db.scalar(select(ClaimIncident).where(ClaimIncident.sin_reference == reference)):
            return reference
        sequence += 1


def add_history(
    db: Session,
    process_id: int,
    *,
    action: str,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    detail: str | None = None,
    user_id: int | None = None,
) -> None:
    db.add(
        ManagementHistory(
            process_id=process_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            old_value=old_value,
            new_value=new_value,
            detail=detail,
        )
    )


def find_claim_by_plate_date(db: Session, plate: str | None, accident_date: date | None) -> ClaimIncident | None:
    if not plate or not accident_date:
        return None
    return db.scalar(
        select(ClaimIncident).where(
            ClaimIncident.plate == plate,
            ClaimIncident.accident_date == accident_date,
        )
    )


def create_claim_process(
    db: Session,
    process_type: ManagementProcessType,
    *,
    plate: str | None,
    accident_date: date | None,
    customer_name: str | None = None,
    driver_name: str | None = None,
    document_reference: str | None = None,
    user_id: int | None = None,
) -> ClaimIncident:
    reference_year = (accident_date or date.today()).year
    sin_reference = next_sin_reference(db, reference_year)
    title_subject = plate or document_reference or "sem dados mínimos"
    process = ManagementProcess(
        process_type_id=process_type.id,
        internal_reference=sin_reference,
        title=f"Sinistro / AR {title_subject}",
        status="information_request" if not plate or not accident_date else "open",
        phase="information_request" if not plate or not accident_date else "analysis",
        priority="normal",
        plate=plate,
        document_reference=document_reference,
        customer_name=customer_name,
        driver_name=driver_name,
        pending_reason="missing_minimum_data" if not plate or not accident_date else None,
        pending_detail="Completar matrícula e data do sinistro." if not plate or not accident_date else None,
        opened_on=accident_date or date.today(),
        sla_due_on=(accident_date or date.today()) + timedelta(days=2),
    )
    db.add(process)
    db.flush()
    claim = ClaimIncident(
        process_id=process.id,
        sin_reference=sin_reference,
        accident_date=accident_date,
        plate=plate,
        operational_status=process.phase,
        has_missing_minimum_data=not bool(plate and accident_date),
        has_missing_ar=False,
        components_json={},
    )
    db.add(claim)
    db.flush()
    add_history(
        db,
        process.id,
        action="process.created",
        entity_type="claim_incident",
        entity_id=claim.id,
        new_value=sin_reference,
        detail="Processo SIN criado.",
        user_id=user_id,
    )
    return claim


def get_or_create_claim(
    db: Session,
    process_type: ManagementProcessType,
    *,
    plate: str | None,
    accident_date: date | None,
    customer_name: str | None = None,
    driver_name: str | None = None,
    document_reference: str | None = None,
    user_id: int | None = None,
) -> ClaimIncident:
    claim = find_claim_by_plate_date(db, plate, accident_date)
    if claim:
        process = db.get(ManagementProcess, claim.process_id)
        changed = False
        if process and customer_name and not process.customer_name:
            process.customer_name = customer_name
            changed = True
        if process and driver_name and not process.driver_name:
            process.driver_name = driver_name
            changed = True
        if process and document_reference and not process.document_reference:
            process.document_reference = document_reference
            changed = True
        if changed and process:
            add_history(
                db,
                process.id,
                action="process.enriched",
                entity_type="claim_incident",
                entity_id=claim.id,
                detail="Dados do processo enriquecidos por importação.",
                user_id=user_id,
            )
        return claim
    return create_claim_process(
        db,
        process_type,
        plate=plate,
        accident_date=accident_date,
        customer_name=customer_name,
        driver_name=driver_name,
        document_reference=document_reference,
        user_id=user_id,
    )


def active_association_exists(db: Session, process_id: int, entity_type: str, entity_id: int) -> bool:
    return bool(
        db.scalar(
            select(ManagementProcessAssociation).where(
                ManagementProcessAssociation.process_id == process_id,
                ManagementProcessAssociation.entity_type == entity_type,
                ManagementProcessAssociation.entity_id == entity_id,
                ManagementProcessAssociation.active.is_(True),
            )
        )
    )


def associate_to_process(
    db: Session,
    process_id: int,
    *,
    entity_type: str,
    entity_id: int,
    reason: str,
    user_id: int | None = None,
) -> None:
    if active_association_exists(db, process_id, entity_type, entity_id):
        return
    association = ManagementProcessAssociation(
        process_id=process_id,
        entity_type=entity_type,
        entity_id=entity_id,
        association_role="source",
        active=True,
        reason=reason,
        created_by_id=user_id,
    )
    db.add(association)
    db.flush()
    add_history(
        db,
        process_id,
        action="association.created",
        entity_type=entity_type,
        entity_id=entity_id,
        new_value="active",
        detail=reason,
        user_id=user_id,
    )


def end_association(
    db: Session,
    association: ManagementProcessAssociation,
    *,
    reason: str,
    user_id: int | None,
) -> None:
    association.active = False
    association.ended_at = datetime.now(UTC)
    association.ended_by_id = user_id
    association.reason = reason
    add_history(
        db,
        association.process_id,
        action="association.ended",
        entity_type=association.entity_type,
        entity_id=association.entity_id,
        old_value="active",
        new_value="inactive",
        detail=reason,
        user_id=user_id,
    )


def rule_by_code(db: Session, process_type_id: int, code: str) -> ManagementRule | None:
    return db.scalar(
        select(ManagementRule).where(
            ManagementRule.process_type_id == process_type_id,
            ManagementRule.code == code,
            ManagementRule.active.is_(True),
        )
    )


def ensure_action(
    db: Session,
    process: ManagementProcess,
    *,
    rule_code: str,
    title: str,
    description: str,
    mandatory: bool,
) -> None:
    rule = rule_by_code(db, process.process_type_id, rule_code)
    existing = db.scalar(
        select(ManagementAction).where(
            ManagementAction.process_id == process.id,
            ManagementAction.title == title,
            ManagementAction.status == "open",
        )
    )
    if existing:
        return
    db.add(
        ManagementAction(
            process_id=process.id,
            rule_id=rule.id if rule else None,
            title=title,
            description=description,
            status="open",
            mandatory=mandatory,
            due_on=date.today() + timedelta(days=1),
        )
    )
    add_history(
        db,
        process.id,
        action="action.created",
        entity_type="management_action",
        new_value=title,
        detail=description,
    )


def close_action_by_title(db: Session, process_id: int, title: str) -> None:
    actions = db.scalars(
        select(ManagementAction).where(
            ManagementAction.process_id == process_id,
            ManagementAction.title == title,
            ManagementAction.status == "open",
        )
    ).all()
    for action in actions:
        action.status = "done"
        action.completed_at = datetime.now(UTC)
        add_history(
            db,
            process_id,
            action="action.completed",
            entity_type="management_action",
            entity_id=action.id,
            old_value="open",
            new_value="done",
            detail=title,
        )


def refresh_claim_state(db: Session, claim: ClaimIncident) -> None:
    process = db.get(ManagementProcess, claim.process_id)
    if not process:
        return
    associations = db.scalars(
        select(ManagementProcessAssociation).where(
            ManagementProcessAssociation.process_id == process.id,
            ManagementProcessAssociation.active.is_(True),
        )
    ).all()
    ar_ids = [item.entity_id for item in associations if item.entity_type == "claim_rentway_ar"]
    refstro_ids = [item.entity_id for item in associations if item.entity_type == "claim_refstro_line"]
    ars = db.scalars(select(ClaimRentwayAR).where(ClaimRentwayAR.id.in_(ar_ids))).all() if ar_ids else []
    refstros = (
        db.scalars(select(ClaimRefstroLine).where(ClaimRefstroLine.id.in_(refstro_ids))).all()
        if refstro_ids
        else []
    )
    total_claim = sum((item.claim_value or Decimal("0.00")) for item in refstros)
    total_cost = sum((item.cost_value or Decimal("0.00")) for item in refstros)
    components = sorted({item.component for item in refstros if item.component})
    claim.components_json = {"components": components}
    claim.has_missing_minimum_data = not bool(claim.plate and claim.accident_date)
    claim.has_missing_ar = bool(not claim.has_missing_minimum_data and not ars)
    process.total_claim_value = total_claim
    process.total_cost_value = total_cost
    process.raw_summary_json = {
        "ar_count": len(ars),
        "refstro_count": len(refstros),
        "components": components,
    }

    if claim.has_missing_minimum_data:
        process.status = "information_request"
        process.phase = "information_request"
        process.pending_reason = "missing_minimum_data"
        process.pending_detail = "Completar matrícula e data do sinistro."
        claim.operational_status = "information_request"
        ensure_action(
            db,
            process,
            rule_code="minimum_data_information_request",
            title="Completar dados mínimos do sinistro",
            description="Pedir matrícula e data antes de criar alertas operacionais.",
            mandatory=False,
        )
    elif claim.has_missing_ar:
        process.status = "waiting"
        process.phase = "ar_missing"
        process.pending_reason = "missing_ar"
        process.pending_detail = "Criar ou associar AR Rentway ao SIN."
        claim.operational_status = "ar_missing"
        ensure_action(
            db,
            process,
            rule_code="missing_ar_action",
            title="Criar ou associar AR",
            description="Este sinistro tem dados mínimos, mas não tem AR associado.",
            mandatory=True,
        )
        close_action_by_title(db, process.id, "Completar dados mínimos do sinistro")
    else:
        latest_status = next((ar.status for ar in ars if ar.status), None)
        claim.rentway_status = latest_status
        claim.operational_status = "rentway_closed_review" if latest_status and "fech" in latest_status.casefold() else "analysis"
        process.status = "analysis"
        process.phase = claim.operational_status
        process.pending_reason = None
        process.pending_detail = None
        close_action_by_title(db, process.id, "Criar ou associar AR")
        close_action_by_title(db, process.id, "Completar dados mínimos do sinistro")


def build_ar_payload(
    row: tuple[Any, ...],
    col: dict[str, int],
    raw: dict[str, Any],
    *,
    source_file: str,
    row_number: int,
) -> dict[str, Any]:
    return {
        "ar_reference": clean_text(
            mapped_value(row, col, ["AR", "ar", "accidentReport", "accident_report", "reportNumber", "nrAR", "sinistro"])
        ),
        "status": clean_text(mapped_value(row, col, ["Status", "status"])),
        "raw_state": clean_text(mapped_value(row, col, ["state", "State"])),
        "request_date": parse_date_value(mapped_value(row, col, ["requestDate", "request_date", "data", "data AR", "Data AR"])),
        "plate": normalize_plate(mapped_value(row, col, ["matricula", "matrícula", "plate", "plateNr", "licensePlate"])),
        "vehicle_reference": clean_text(mapped_value(row, col, ["viatura", "vehicle", "unit", "unitNr", "rentwayUnitNr"])),
        "driver_name": clean_text(mapped_value(row, col, ["condutor", "driver", "driverName"])),
        "customer_name": clean_text(mapped_value(row, col, ["cliente", "customer", "customerName"])),
        "ra_reference": clean_text(mapped_value(row, col, ["RA", "ra", "rentalAgreement", "reservation"])),
        "impro_reference": clean_text(mapped_value(row, col, ["IMPRO", "impro"])),
        "daaa_reference": clean_text(mapped_value(row, col, ["DAAA", "daaa"])),
        "insurance_policy": clean_text(mapped_value(row, col, ["insurancePolicy", "insurance_policy", "apolice", "apólice"])),
        "rental_station_out": clean_text(mapped_value(row, col, ["rentalStationOut", "stationOut", "estacaoSaida"])),
        "created_by_rental_station": clean_text(
            mapped_value(row, col, ["createdByRentalSation", "createdByRentalStation", "created_by_rental_station"])
        ),
        "source_file": source_file,
        "source_row_number": row_number,
        "raw_json": raw,
    }


def build_refstro_payload(
    row: tuple[Any, ...],
    col: dict[str, int],
    raw: dict[str, Any],
    *,
    source_file: str,
    row_number: int,
) -> dict[str, Any]:
    return {
        "refstro_reference": clean_text(mapped_value(row, col, ["REFSTRO", "refstro", "referencia sinistro", "referência sinistro"])),
        "document_reference": clean_text(mapped_value(row, col, ["documento", "document", "doc", "fatura", "invoice"])),
        "plate": normalize_plate(mapped_value(row, col, ["matricula", "matrícula", "plate", "plateNr", "licensePlate"])),
        "accident_date": parse_date_value(
            mapped_value(row, col, ["data sinistro", "data_sinistro", "accidentDate", "data acidente", "data"])
        ),
        "component": normalize_component(mapped_value(row, col, ["componente", "component", "tipo", "rubrica"])),
        "status": clean_text(mapped_value(row, col, ["status", "estado", "situação", "situacao"])),
        "close_date": parse_date_value(mapped_value(row, col, ["data fecho", "closeDate", "closedAt", "encerramento"])),
        "customer_name": clean_text(mapped_value(row, col, ["cliente", "customer", "customerName"])),
        "driver_name": clean_text(mapped_value(row, col, ["condutor", "driver", "driverName"])),
        "claim_value": parse_decimal_value(mapped_value(row, col, ["valor", "claimValue", "valor sinistro", "montante"])),
        "cost_value": parse_decimal_value(mapped_value(row, col, ["custo", "cost", "custos", "valor custo"])),
        "source_file": source_file,
        "source_row_number": row_number,
        "raw_json": raw,
    }


def import_claims_file(
    db: Session,
    path: str | Path,
    original_name: str,
    *,
    import_kind: str,
    user_id: int | None,
) -> dict[str, Any]:
    process_type = ensure_management_defaults(db)
    import_type = AR_IMPORT_TYPE if import_kind == "ar" else REFSTRO_IMPORT_TYPE
    rows = list(iter_management_rows(path))
    batch = ImportBatch(
        source_system=MANAGEMENT_CENTER_SOURCE_SYSTEM,
        import_type=import_type,
        status="running",
        imported_by_id=user_id,
        total_rows=len(rows),
        detail=f"Importação Centro de Gestão: {MANAGEMENT_CENTER_TYPE_NAME}.",
    )
    db.add(batch)
    db.flush()

    stored_path = management_storage_root() / f"batch_{batch.id}_{Path(path).name}"
    shutil.copyfile(path, stored_path)
    headers = rows[0][1] if rows else []
    sheet_name = rows[0][0] if rows else None
    db.add(
        ImportFile(
            batch_id=batch.id,
            original_name=original_name,
            file_name=stored_path.name,
            storage_path=str(stored_path),
            sheet_name=sheet_name,
            columns_json=headers,
        )
    )

    created_rows = 0
    error_rows = 0
    touched_process_ids: set[int] = set()
    groups = Counter()
    for sheet_name, headers, row_number, row, raw in rows:
        col = build_column_lookup(headers)
        db.add(
            ImportRawRow(
                batch_id=batch.id,
                row_number=row_number,
                external_reference=clean_text(raw.get("REFSTRO") or raw.get("AR") or raw.get("Status")),
                raw_json=raw,
                row_hash=row_hash(raw),
            )
        )
        if import_kind == "ar":
            payload = build_ar_payload(row, col, raw, source_file=original_name, row_number=row_number)
            if not payload["ar_reference"] and not payload["plate"]:
                error_rows += 1
                db.add(
                    ImportError(
                        batch_id=batch.id,
                        row_number=row_number,
                        entity_type="claim_rentway_ar",
                        error_message="Linha AR sem referência nem matrícula.",
                        raw_json=raw,
                    )
                )
                continue
            ar = ClaimRentwayAR(**payload)
            db.add(ar)
            db.flush()
            claim = get_or_create_claim(
                db,
                process_type,
                plate=payload["plate"],
                accident_date=payload["request_date"],
                customer_name=payload["customer_name"],
                driver_name=payload["driver_name"],
                document_reference=payload["ar_reference"],
                user_id=user_id,
            )
            associate_to_process(
                db,
                claim.process_id,
                entity_type="claim_rentway_ar",
                entity_id=ar.id,
                reason=f"Associado por importação AR lote #{batch.id}.",
                user_id=user_id,
            )
            refresh_claim_state(db, claim)
            touched_process_ids.add(claim.process_id)
            groups[payload["status"] or "Sem Status"] += 1
            created_rows += 1
        else:
            payload = build_refstro_payload(row, col, raw, source_file=original_name, row_number=row_number)
            if not payload["plate"] and not payload["refstro_reference"]:
                error_rows += 1
                db.add(
                    ImportError(
                        batch_id=batch.id,
                        row_number=row_number,
                        entity_type="claim_refstro_line",
                        error_message="Linha REFSTRO sem matrícula nem REFSTRO.",
                        raw_json=raw,
                    )
                )
                continue
            refstro = ClaimRefstroLine(**payload)
            db.add(refstro)
            db.flush()
            claim = get_or_create_claim(
                db,
                process_type,
                plate=payload["plate"],
                accident_date=payload["accident_date"],
                customer_name=payload["customer_name"],
                driver_name=payload["driver_name"],
                document_reference=payload["document_reference"] or payload["refstro_reference"],
                user_id=user_id,
            )
            associate_to_process(
                db,
                claim.process_id,
                entity_type="claim_refstro_line",
                entity_id=refstro.id,
                reason=f"Associado por importação REFSTRO lote #{batch.id}.",
                user_id=user_id,
            )
            refresh_claim_state(db, claim)
            touched_process_ids.add(claim.process_id)
            groups[payload["component"] or "Sem componente"] += 1
            created_rows += 1

    batch.status = "completed" if error_rows == 0 else "completed_with_errors"
    batch.created_rows = created_rows
    batch.updated_rows = len(touched_process_ids)
    batch.error_rows = error_rows
    batch.finished_at = datetime.now(UTC)
    batch.detail = f"{created_rows} linhas guardadas; {len(touched_process_ids)} processos tocados."
    record_audit(
        db,
        action="management_center.import.completed",
        entity_type="import_batch",
        entity_id=batch.id,
        detail=batch.detail,
        after_json={
            "import_kind": import_kind,
            "process_ids": sorted(touched_process_ids),
            "groups": groups.most_common(),
        },
        user_id=user_id,
    )
    db.commit()
    return {
        "batch_id": batch.id,
        "created_rows": created_rows,
        "updated_rows": len(touched_process_ids),
        "error_rows": error_rows,
        "groups": groups.most_common(),
    }
