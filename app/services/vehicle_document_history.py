from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.documents import (
    Document,
    VehicleDocumentAlert,
    VehicleDocumentAuditField,
    VehicleDocumentPendingAction,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.models.management_center import ClaimIncident, ClaimRentwayAR
from app.models.vehicles import Vehicle, VehicleManualField
from app.services.spreadsheets import (
    build_column_lookup,
    clean_int,
    clean_text,
    excel_date_to_iso,
    first_row_value,
    iter_xlsx_rows,
    normalize_header,
)


DOCUMENT_HISTORY_MAIN_GROUPS = [
    ("work_orders", "Folhas de obra"),
    ("ars", "AR's"),
    ("claims", "Sinistros"),
    ("contracts", "Contratos"),
    ("impros", "Impros"),
    ("invoices", "Faturas"),
    ("diagnostics", "Diagnósticos"),
]
DOCUMENT_HISTORY_MAIN_GROUP_LABELS = dict(DOCUMENT_HISTORY_MAIN_GROUPS)

DOCUMENT_HISTORY_ARCHIVE_GROUPS = [
    ("invoices", "Faturas"),
    ("credit_notes", "Notas de crédito"),
    ("payment_proofs", "Comprovativos"),
    ("diagnostics", "Diagnósticos"),
    ("servicebox_tsb", "Service Box / TSB"),
    ("evidence", "Fotos / evidências"),
    ("base_vehicle", "Documentação base"),
]
DOCUMENT_HISTORY_ARCHIVE_GROUP_LABELS = dict(DOCUMENT_HISTORY_ARCHIVE_GROUPS)

DOCUMENT_HISTORY_STRUCTURED_GROUPS = [
    ("work_orders", "Folhas de obra"),
    ("ars", "AR's"),
    ("claims", "Sinistros"),
    ("contracts", "Contratos"),
    ("impros", "Impros"),
]
DOCUMENT_HISTORY_STRUCTURED_GROUP_LABELS = dict(DOCUMENT_HISTORY_STRUCTURED_GROUPS)

DOCUMENT_HISTORY_COMPARISON_STATES = [
    ("coerente", "Coerente"),
    ("complementar", "Complementar"),
    ("divergente", "Divergente"),
    ("por_validar", "Por validar"),
]
DOCUMENT_HISTORY_COMPARISON_LABELS = dict(DOCUMENT_HISTORY_COMPARISON_STATES)

DOCUMENT_HISTORY_ALERT_SEVERITIES = [
    ("warning", "Aviso"),
    ("critical", "Crítico"),
    ("info", "Informativo"),
]
DOCUMENT_HISTORY_ALERT_LABELS = dict(DOCUMENT_HISTORY_ALERT_SEVERITIES)

DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS: dict[str, list[tuple[str, str]]] = {
    "maintenance": [("revision", "Revisão"), ("degradation", "Degradação"), ("other", "Outro")],
    "pads": [("front", "Frente"), ("rear", "Trás"), ("other", "Outro")],
    "discs": [("front", "Frente"), ("rear", "Trás"), ("other", "Outro")],
    "tyres": [("front", "Frente"), ("rear", "Trás"), ("other", "Outro")],
    "fault": [("free_text", "Texto livre")],
    "services": [("telecharge", "Telecarregamento"), ("other", "Outro")],
    "repair": [("free_text", "Texto livre")],
}
DOCUMENT_HISTORY_QUICK_CLASSIFICATION_LABELS = {
    "maintenance": "Manutenção",
    "pads": "Calços",
    "discs": "Discos",
    "tyres": "Pneus",
    "fault": "Avaria",
    "services": "Serviços",
    "repair": "Reparação",
}

DOCUMENT_HISTORY_AUDIT_FIELDS = [
    ("real_start_date", "Início real"),
    ("effective_maintenance_count", "Nº de manutenções efetivas até à data X"),
]
DOCUMENT_HISTORY_AUDIT_FIELD_LABELS = dict(DOCUMENT_HISTORY_AUDIT_FIELDS)


@dataclass(slots=True)
class TimelineEvent:
    group: str
    label: str
    title: str
    secondary: str
    occurred_on: date | None
    km: int | None
    state: str
    record_id: int | None = None
    document_id: int | None = None
    source_kind: str = "record"


def _safe_date(value: Any) -> date | None:
    iso = excel_date_to_iso(value)
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


def _normalize_text(value: Any) -> str:
    return clean_text(value) or ""


def _vehicle_lookup_maps(db: Session) -> tuple[dict[str, Vehicle], dict[str, Vehicle], dict[str, Vehicle]]:
    vehicles = db.scalars(select(Vehicle)).all()
    by_plate: dict[str, Vehicle] = {}
    by_vin: dict[str, Vehicle] = {}
    by_unit: dict[str, Vehicle] = {}
    for vehicle in vehicles:
        plate_key = normalize_header(vehicle.plate or "")
        vin_key = normalize_header(vehicle.vin or "")
        unit_key = normalize_header(vehicle.rentway_unit_nr or "")
        if plate_key and plate_key not in by_plate:
            by_plate[plate_key] = vehicle
        if vin_key and vin_key not in by_vin:
            by_vin[vin_key] = vehicle
        if unit_key and unit_key not in by_unit:
            by_unit[unit_key] = vehicle
    return by_plate, by_vin, by_unit


def _resolve_vehicle_for_import_row(
    *,
    fallback_vehicle: Vehicle | None,
    by_plate: dict[str, Vehicle],
    by_vin: dict[str, Vehicle],
    by_unit: dict[str, Vehicle],
    plate: str | None = None,
    vin: str | None = None,
    unit: str | None = None,
) -> Vehicle | None:
    if fallback_vehicle is not None:
        fallback_plate = normalize_header(fallback_vehicle.plate or "")
        fallback_vin = normalize_header(fallback_vehicle.vin or "")
        fallback_unit = normalize_header(fallback_vehicle.rentway_unit_nr or "")
        row_plate = normalize_header(plate or "")
        row_vin = normalize_header(vin or "")
        row_unit = normalize_header(unit or "")
        if any([row_plate, row_vin, row_unit]) and not any(
            [
                row_plate and row_plate == fallback_plate,
                row_vin and row_vin == fallback_vin,
                row_unit and row_unit == fallback_unit,
            ]
        ):
            return None
        return fallback_vehicle

    row_plate = normalize_header(plate or "")
    row_vin = normalize_header(vin or "")
    row_unit = normalize_header(unit or "")
    if row_plate and row_plate in by_plate:
        return by_plate[row_plate]
    if row_vin and row_vin in by_vin:
        return by_vin[row_vin]
    if row_unit and row_unit in by_unit:
        return by_unit[row_unit]
    return None


def _document_archive_group(document: Document) -> str:
    doc_type = normalize_header(document.document_type or "")
    title_blob = " ".join(
        str(part or "") for part in [document.title, document.original_name, document.source_subject, document.supplier_name]
    )
    title = normalize_header(title_blob)
    if doc_type in {"workshopsupplierinvoice", "financesupplierinvoice"} or "fatura" in title or "factura" in title:
        return "invoices"
    if doc_type == "financecreditnote" or "nota credito" in title or "nota de credito" in title:
        return "credit_notes"
    if doc_type in {"financepaymentproof", "financereceipt"} or any(
        token in title for token in ["comprovativo", "recibo", "payment proof"]
    ):
        return "payment_proofs"
    if doc_type in {"workshopreport", "workshopdiagnostic", "workshopbsi"} or any(
        token in title for token in ["diagn", "relatorio", "relat", "bsi", "autel", "stellantis"]
    ):
        return "diagnostics"
    if "servicebox" in title or "servicebox" in doc_type or "tsb" in title or "boletim" in title:
        return "servicebox_tsb"
    if any(token in title for token in ["foto", "image", "imagem", "evidencia", "evidence"]):
        return "evidence"
    return "base_vehicle"


def _document_timeline_group(document: Document) -> str | None:
    archive_group = _document_archive_group(document)
    if archive_group in {"invoices", "diagnostics"}:
        return archive_group
    return None


def _display_title(document: Document) -> str:
    return document.title or document.original_name or document.file_name or f"Documento #{document.id}"


def _match_existing_record(
    db: Session,
    *,
    vehicle_id: int,
    main_group: str,
    external_reference: str | None,
    document_date: date | None,
    supplier_name: str | None,
) -> VehicleDocumentRecord | None:
    stmt = select(VehicleDocumentRecord).where(
        VehicleDocumentRecord.vehicle_id == vehicle_id,
        VehicleDocumentRecord.main_group == main_group,
    )
    if external_reference:
        stmt = stmt.where(VehicleDocumentRecord.external_reference == external_reference)
    elif supplier_name and document_date:
        stmt = stmt.where(
            VehicleDocumentRecord.supplier_name == supplier_name,
            VehicleDocumentRecord.document_date == document_date,
        )
    else:
        return None
    return db.scalar(stmt.limit(1))


def upsert_structured_record(
    db: Session,
    *,
    vehicle_id: int,
    main_group: str,
    title: str,
    external_reference: str | None,
    document_date: date | None,
    supplier_name: str | None,
    raw_description: str | None,
    km: int | None,
    source_system: str,
    process_reference: str | None = None,
    plate: str | None = None,
    vin: str | None = None,
    subtype: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    user_id: int | None = None,
) -> VehicleDocumentRecord:
    record = _match_existing_record(
        db,
        vehicle_id=vehicle_id,
        main_group=main_group,
        external_reference=external_reference,
        document_date=document_date,
        supplier_name=supplier_name,
    )
    if record:
        record.title = title
        record.document_date = document_date
        record.supplier_name = supplier_name
        record.raw_description = raw_description
        record.km = km
        record.source_system = source_system
        record.process_reference = process_reference
        record.plate = plate
        record.vin = vin
        record.subtype = subtype
        record.metadata_json = metadata_json
        record.updated_by_id = user_id
        return record
    record = VehicleDocumentRecord(
        vehicle_id=vehicle_id,
        source_record_type="structured",
        main_group=main_group,
        title=title,
        external_reference=external_reference,
        document_date=document_date,
        supplier_name=supplier_name,
        raw_description=raw_description,
        km=km,
        source_system=source_system,
        process_reference=process_reference,
        plate=plate,
        vin=vin,
        subtype=subtype,
        metadata_json=metadata_json,
        status="structured",
        has_physical_file=False,
        created_by_id=user_id,
        updated_by_id=user_id,
    )
    db.add(record)
    db.flush()
    return record


def create_archive_placeholder(
    db: Session,
    *,
    vehicle_id: int,
    main_group: str,
    title: str,
    document_date: date | None,
    supplier_name: str | None,
    raw_description: str | None,
    process_reference: str | None,
    user_id: int | None,
) -> VehicleDocumentRecord:
    record = VehicleDocumentRecord(
        vehicle_id=vehicle_id,
        source_record_type="archive_pending",
        main_group=main_group,
        title=title,
        document_date=document_date,
        supplier_name=supplier_name,
        raw_description=raw_description,
        process_reference=process_reference,
        has_physical_file=False,
        status="pending",
        created_by_id=user_id,
        updated_by_id=user_id,
    )
    db.add(record)
    db.flush()
    return record


def attach_document_to_record(db: Session, record: VehicleDocumentRecord, document_id: int, user_id: int | None) -> None:
    record.document_id = document_id
    record.has_physical_file = True
    record.status = "associated"
    record.updated_by_id = user_id


def add_quick_classification(
    db: Session,
    *,
    vehicle_id: int,
    category: str,
    value: str | None,
    free_text: str | None,
    record_id: int | None = None,
    document_id: int | None = None,
    user_id: int | None = None,
) -> VehicleDocumentRecordTag:
    tag = VehicleDocumentRecordTag(
        vehicle_id=vehicle_id,
        record_id=record_id,
        document_id=document_id,
        category=category,
        value=value,
        free_text=free_text,
        created_by_id=user_id,
    )
    db.add(tag)
    db.flush()
    return tag


def upsert_audit_field(
    db: Session,
    *,
    vehicle_id: int,
    field_code: str,
    value: Any,
    audited_on: date | None,
    observation: str | None,
    document_basis: str | None,
    user_id: int | None,
) -> VehicleDocumentAuditField:
    field = db.scalar(
        select(VehicleDocumentAuditField).where(
            VehicleDocumentAuditField.vehicle_id == vehicle_id,
            VehicleDocumentAuditField.field_code == field_code,
        )
    )
    if field:
        field.value_json = value
        field.audited_on = audited_on
        field.observation = observation
        field.document_basis = document_basis
        field.updated_by_id = user_id
        return field
    field = VehicleDocumentAuditField(
        vehicle_id=vehicle_id,
        field_code=field_code,
        value_json=value,
        audited_on=audited_on,
        observation=observation,
        document_basis=document_basis,
        created_by_id=user_id,
        updated_by_id=user_id,
    )
    db.add(field)
    db.flush()
    return field


def sync_real_start_manual_field(db: Session, vehicle_id: int, value: str | None, user_id: int | None) -> None:
    field = db.scalar(
        select(VehicleManualField).where(
            VehicleManualField.vehicle_id == vehicle_id,
            VehicleManualField.field_code == "real_start_date",
        )
    )
    if field:
        field.value_json = value
        field.updated_by_id = user_id
        return
    db.add(
        VehicleManualField(
            vehicle_id=vehicle_id,
            field_code="real_start_date",
            value_json=value,
            updated_by_id=user_id,
        )
    )


def import_work_orders_xlsx(db: Session, *, path: Path, vehicle: Vehicle | None = None, user_id: int | None = None) -> int:
    imported = 0
    by_plate, by_vin, by_unit = _vehicle_lookup_maps(db)
    for _sheet, headers, _row_number, row, raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        plate = _normalize_text(first_row_value(row, cols, ["Matrícula", "Matricula", "PlateNr"]))
        row_vehicle = _resolve_vehicle_for_import_row(
            fallback_vehicle=vehicle,
            by_plate=by_plate,
            by_vin=by_vin,
            by_unit=by_unit,
            plate=plate,
        )
        if not row_vehicle:
            continue
        title = _normalize_text(first_row_value(row, cols, ["Número", "Numero", "FO", "Folha de obra"]))
        external_reference = title or None
        document_date = _safe_date(first_row_value(row, cols, ["Data", "DocumentDate"]))
        supplier_name = _normalize_text(first_row_value(row, cols, ["Nome fornecedor", "Fornecedor", "Supplier"]))
        raw_description = _normalize_text(first_row_value(row, cols, ["Observações", "Observacoes", "Descrição", "Descricao"]))
        upsert_structured_record(
            db,
            vehicle_id=row_vehicle.id,
            main_group="work_orders",
            title=title or "Folha de obra",
            external_reference=external_reference,
            document_date=document_date,
            supplier_name=supplier_name or None,
            raw_description=raw_description or None,
            km=None,
            source_system="work_order_import",
            plate=row_vehicle.plate,
            vin=row_vehicle.vin,
            metadata_json=raw,
            user_id=user_id,
        )
        imported += 1
    return imported


def import_impros_xlsx(db: Session, *, path: Path, vehicle: Vehicle | None = None, user_id: int | None = None) -> int:
    imported = 0
    by_plate, by_vin, by_unit = _vehicle_lookup_maps(db)
    for _sheet, headers, _row_number, row, raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        plate = _normalize_text(first_row_value(row, cols, ["PlateNr", "Matrícula", "Matricula"]))
        row_vehicle = _resolve_vehicle_for_import_row(
            fallback_vehicle=vehicle,
            by_plate=by_plate,
            by_vin=by_vin,
            by_unit=by_unit,
            plate=plate,
        )
        if not row_vehicle:
            continue
        impro_number = _normalize_text(first_row_value(row, cols, ["Impro", "impro_number"]))
        status = _normalize_text(first_row_value(row, cols, ["Status"]))
        date_in = _safe_date(first_row_value(row, cols, ["Date_In", "Data entrada"]))
        date_out = _safe_date(first_row_value(row, cols, ["Date_Out", "Data saída"]))
        driven_kms = clean_int(first_row_value(row, cols, ["Driven_Kms", "Km"]))
        title = impro_number or "Impro"
        description_parts = [
            _normalize_text(first_row_value(row, cols, ["Impro_Type_Description"])),
            _normalize_text(first_row_value(row, cols, ["Garage"])),
            _normalize_text(first_row_value(row, cols, ["Driver_Name"])),
        ]
        raw_description = " | ".join(part for part in description_parts if part) or None
        upsert_structured_record(
            db,
            vehicle_id=row_vehicle.id,
            main_group="impros",
            title=title,
            external_reference=impro_number,
            document_date=date_in,
            supplier_name=_normalize_text(first_row_value(row, cols, ["Garage"])) or None,
            raw_description=raw_description,
            km=driven_kms,
            source_system="impro_import",
            plate=row_vehicle.plate,
            vin=row_vehicle.vin,
            subtype=_normalize_text(first_row_value(row, cols, ["Impro_Type_Code"])) or None,
            metadata_json={**raw, "_status": status, "_date_out": date_out.isoformat() if date_out else None},
            user_id=user_id,
        )
        imported += 1
    return imported


def import_contracts_xlsx(db: Session, *, path: Path, vehicle: Vehicle | None = None, user_id: int | None = None) -> int:
    imported = 0
    by_plate, by_vin, by_unit = _vehicle_lookup_maps(db)
    for _sheet, headers, _row_number, row, raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        plate = _normalize_text(first_row_value(row, cols, ["Matrícula", "Matricula", "PlateNr", "Plate"]))
        vin = _normalize_text(first_row_value(row, cols, ["Chassi", "VIN", "Vin", "Chassis"]))
        unit = _normalize_text(first_row_value(row, cols, ["Unit", "UnitNr", "Unit Nr", "Unit Rentway"]))
        row_vehicle = _resolve_vehicle_for_import_row(
            fallback_vehicle=vehicle,
            by_plate=by_plate,
            by_vin=by_vin,
            by_unit=by_unit,
            plate=plate,
            vin=vin,
            unit=unit,
        )
        if not row_vehicle:
            continue

        contract_number = _normalize_text(
            first_row_value(
                row,
                cols,
                ["Contrato", "Nº Contrato", "No Contrato", "Numero Contrato", "Contract", "Contract Number", "ra", "RA"],
            )
        )
        ra_reference = _normalize_text(first_row_value(row, cols, ["ra", "RA"]))
        supplier_name = _normalize_text(
            first_row_value(row, cols, ["Fornecedor", "Locadora", "Financeira", "Entidade", "Supplier", "customer_name"])
        )
        start_date = _safe_date(
            first_row_value(row, cols, ["Data início", "Data Inicio", "Start Date", "Data contrato", "date_out"])
        )
        end_date = _safe_date(first_row_value(row, cols, ["Data fim", "End Date", "Data término", "Data Termino", "date_in"]))
        status = _normalize_text(first_row_value(row, cols, ["Estado", "Status", "salesperson"]))
        monthly_value = _normalize_text(
            first_row_value(row, cols, ["Valor mensal", "Renda", "Mensalidade", "Monthly Value", "Valor", "invoiced_amount"])
        )
        notes = _normalize_text(
            first_row_value(row, cols, ["Observações", "Observacoes", "Descrição", "Descricao", "Notes"])
        )
        station = _normalize_text(first_row_value(row, cols, ["station", "Estação", "Estacao"]))
        origin = _normalize_text(first_row_value(row, cols, ["origin", "Origem"]))
        rate_code = _normalize_text(first_row_value(row, cols, ["rate_code", "Rate Code"]))
        category = _normalize_text(first_row_value(row, cols, ["category", "Categoria"]))
        category_requested = _normalize_text(first_row_value(row, cols, ["category_requested", "Categoria pedida"]))
        ndays = _normalize_text(first_row_value(row, cols, ["ndays", "Dias"]))
        creation_date = _safe_date(first_row_value(row, cols, ["creation_date", "Data criação", "Data criacao"]))
        cashier_amount = _normalize_text(first_row_value(row, cols, ["cashier_amount", "Valor caixa"]))

        description_parts = []
        if status:
            description_parts.append(f"Estado: {status}")
        if station:
            description_parts.append(f"Estação: {station}")
        if origin:
            description_parts.append(f"Origem: {origin}")
        if rate_code:
            description_parts.append(f"Rate code: {rate_code}")
        if category:
            description_parts.append(f"Categoria: {category}")
        if category_requested and category_requested != category:
            description_parts.append(f"Categoria pedida: {category_requested}")
        if ndays:
            description_parts.append(f"Dias: {ndays}")
        if creation_date:
            description_parts.append(f"Criado em: {creation_date.strftime('%d/%m/%Y')}")
        if end_date:
            description_parts.append(f"Fim: {end_date.strftime('%d/%m/%Y')}")
        if monthly_value:
            description_parts.append(f"Valor: {monthly_value}")
        if cashier_amount:
            description_parts.append(f"Valor caixa: {cashier_amount}")
        if notes:
            description_parts.append(notes)

        upsert_structured_record(
            db,
            vehicle_id=row_vehicle.id,
            main_group="contracts",
            title=(f"RA {contract_number}" if ra_reference and contract_number and not contract_number.upper().startswith("RA") else contract_number)
            or supplier_name
            or "Contrato",
            external_reference=contract_number or None,
            document_date=start_date,
            supplier_name=supplier_name or None,
            raw_description=" | ".join(part for part in description_parts if part) or None,
            km=None,
            source_system="contract_import",
            plate=row_vehicle.plate,
            vin=row_vehicle.vin,
            subtype=status or None,
            metadata_json={
                **raw,
                "_station": station or None,
                "_origin": origin or None,
                "_rate_code": rate_code or None,
                "_category": category or None,
                "_category_requested": category_requested or None,
                "_creation_date": creation_date.isoformat() if creation_date else None,
                "_end_date": end_date.isoformat() if end_date else None,
                "_monthly_value": monthly_value or None,
                "_cashier_amount": cashier_amount or None,
            },
            user_id=user_id,
        )
        imported += 1
    return imported


def _load_vehicle_documents(db: Session, vehicle: Vehicle) -> list[Document]:
    return db.scalars(
        select(Document)
        .where(or_(Document.vehicle_id == vehicle.id, Document.plate == vehicle.plate))
        .order_by(Document.document_date.desc().nullslast(), Document.updated_at.desc(), Document.id.desc())
    ).all()


def _tag_maps(
    db: Session,
    vehicle_id: int,
) -> tuple[dict[int, list[VehicleDocumentRecordTag]], dict[int, list[VehicleDocumentRecordTag]]]:
    tags = db.scalars(
        select(VehicleDocumentRecordTag)
        .where(VehicleDocumentRecordTag.vehicle_id == vehicle_id)
        .order_by(VehicleDocumentRecordTag.created_at.asc(), VehicleDocumentRecordTag.id.asc())
    ).all()
    by_record: dict[int, list[VehicleDocumentRecordTag]] = {}
    by_document: dict[int, list[VehicleDocumentRecordTag]] = {}
    for tag in tags:
        if tag.record_id:
            by_record.setdefault(tag.record_id, []).append(tag)
        if tag.document_id:
            by_document.setdefault(tag.document_id, []).append(tag)
    return by_record, by_document


def _alert_rows(db: Session, vehicle_id: int) -> list[dict[str, Any]]:
    rows = []
    alerts = db.scalars(
        select(VehicleDocumentAlert)
        .where(VehicleDocumentAlert.vehicle_id == vehicle_id)
        .order_by(VehicleDocumentAlert.created_at.desc(), VehicleDocumentAlert.id.desc())
    ).all()
    for alert in alerts:
        rows.append(
            {
                "title": alert.title,
                "detail": alert.detail or "",
                "severity": alert.severity,
                "severity_label": DOCUMENT_HISTORY_ALERT_LABELS.get(alert.severity, alert.severity),
                "source": "manual",
            }
        )
    return rows


def _pending_rows(db: Session, vehicle_id: int) -> list[dict[str, Any]]:
    rows = []
    pendings = db.scalars(
        select(VehicleDocumentPendingAction)
        .where(VehicleDocumentPendingAction.vehicle_id == vehicle_id)
        .order_by(VehicleDocumentPendingAction.created_at.desc(), VehicleDocumentPendingAction.id.desc())
    ).all()
    for pending in pendings:
        rows.append(
            {
                "title": pending.title,
                "detail": pending.detail or "",
                "status": pending.status,
                "source": "manual",
                "action_type": pending.action_type,
            }
        )
    return rows


def _format_tag(tag: VehicleDocumentRecordTag) -> str:
    category = DOCUMENT_HISTORY_QUICK_CLASSIFICATION_LABELS.get(tag.category, tag.category)
    if tag.free_text:
        return f"{category}: {tag.free_text}"
    if tag.value:
        option_labels = dict(DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS.get(tag.category, []))
        return f"{category}: {option_labels.get(tag.value, tag.value)}"
    return category


def _display_date(value: Any) -> str:
    if value in (None, ""):
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")
    text = str(value).strip()
    if not text:
        return "-"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return text


def _signature_from_tags(tags: list[VehicleDocumentRecordTag]) -> set[str]:
    signature: set[str] = set()
    for tag in tags:
        value = tag.free_text or tag.value or ""
        signature.add(f"{tag.category}:{normalize_header(value)}")
    return signature


def _build_structured_rows(
    db: Session,
    vehicle_id: int,
    record_tags: dict[int, list[VehicleDocumentRecordTag]],
) -> list[dict[str, Any]]:
    vehicle_plate = db.scalar(select(Vehicle.plate).where(Vehicle.id == vehicle_id))
    persisted_rows = db.scalars(
        select(VehicleDocumentRecord)
        .where(
            VehicleDocumentRecord.vehicle_id == vehicle_id,
            VehicleDocumentRecord.source_record_type == "structured",
            VehicleDocumentRecord.main_group.in_([code for code, _ in DOCUMENT_HISTORY_STRUCTURED_GROUPS]),
        )
        .order_by(VehicleDocumentRecord.document_date.desc().nullslast(), VehicleDocumentRecord.id.desc())
    ).all()

    rows = []
    for row in persisted_rows:
        tags = record_tags.get(row.id, [])
        rows.append(
            {
                "kind": "record",
                "id": row.id,
                "main_group": row.main_group,
                "group_label": DOCUMENT_HISTORY_STRUCTURED_GROUP_LABELS.get(row.main_group, row.main_group),
                "date": row.document_date,
                "date_display": _display_date(row.document_date),
                "title": row.title or row.external_reference or row.main_group,
                "supplier_name": row.supplier_name or "-",
                "km": row.km,
                "status": row.status,
                "comparison_state": row.comparison_state or "por_validar",
                "comparison_label": DOCUMENT_HISTORY_COMPARISON_LABELS.get(row.comparison_state or "por_validar", "Por validar"),
                "process_reference": row.process_reference or "-",
                "description": row.raw_description or "",
                "external_reference": row.external_reference or "-",
                "tags": [_format_tag(tag) for tag in tags],
            }
        )

    # AR's e sinistros já existentes noutras tabelas entram como consulta estruturada mesmo sem import dedicado.
    ars = db.scalars(
        select(ClaimRentwayAR)
        .where(ClaimRentwayAR.plate == vehicle_plate)
        .order_by(ClaimRentwayAR.request_date.desc().nullslast(), ClaimRentwayAR.id.desc())
    ).all()
    for ar in ars:
        rows.append(
            {
                "kind": "ar",
                "id": ar.id,
                "main_group": "ars",
                "group_label": "AR's",
                "date": ar.request_date,
                "date_display": _display_date(ar.request_date),
                "title": ar.ar_reference or f"AR #{ar.id}",
                "supplier_name": ar.customer_name or ar.created_by_rental_station or "-",
                "km": None,
                "status": ar.status or "structured",
                "comparison_state": "por_validar",
                "comparison_label": "Por validar",
                "process_reference": ar.ra_reference or ar.impro_reference or ar.daaa_reference or "-",
                "description": ar.driver_name or "",
                "external_reference": ar.ar_reference or "-",
                "tags": [],
            }
        )

    claims = db.scalars(
        select(ClaimIncident)
        .where(ClaimIncident.plate == vehicle_plate)
        .order_by(ClaimIncident.accident_date.desc().nullslast(), ClaimIncident.id.desc())
    ).all()
    for claim in claims:
        rows.append(
            {
                "kind": "claim",
                "id": claim.id,
                "main_group": "claims",
                "group_label": "Sinistros",
                "date": claim.accident_date,
                "date_display": _display_date(claim.accident_date),
                "title": claim.sin_reference or f"Sinistro #{claim.id}",
                "supplier_name": claim.rentway_status or "-",
                "km": None,
                "status": claim.status or "structured",
                "comparison_state": "por_validar",
                "comparison_label": "Por validar",
                "process_reference": str(claim.process_id) if claim.process_id else "-",
                "description": claim.notes or "",
                "external_reference": claim.sin_reference or "-",
                "tags": [],
            }
        )
    rows.sort(key=lambda row: (row["date"] or date.min, row["km"] or -1, str(row["title"])), reverse=True)
    return rows


def _build_archive_rows(
    documents: list[Document],
    document_tags: dict[int, list[VehicleDocumentRecordTag]],
    pending_records: list[VehicleDocumentRecord],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        archive_group = _document_archive_group(document)
        tags = document_tags.get(document.id, [])
        rows.append(
            {
                "kind": "document",
                "id": document.id,
                "archive_group": archive_group,
                "archive_label": DOCUMENT_HISTORY_ARCHIVE_GROUP_LABELS.get(archive_group, archive_group),
                "main_group": _document_timeline_group(document),
                "title": _display_title(document),
                "date": document.document_date,
                "date_display": _display_date(document.document_date),
                "supplier_name": document.supplier_name or document.source or "-",
                "status": document.status,
                "extraction_state": "validado" if archive_group == "diagnostics" and tags else "por_validar",
                "comparison_state": "por_validar",
                "document_type": document.document_type or "-",
                "process_reference": f"Oficina #{document.workshop_process_id}" if document.workshop_process_id else "-",
                "document_number": document.contract_number or document.reservation_number or str(document.id),
                "open_href": f"/documents/{document.id}",
                "tags": [_format_tag(tag) for tag in tags],
            }
        )
    for record in pending_records:
        rows.append(
            {
                "kind": "pending_record",
                "id": record.id,
                "archive_group": record.main_group,
                "archive_label": DOCUMENT_HISTORY_ARCHIVE_GROUP_LABELS.get(record.main_group, record.main_group),
                "main_group": record.main_group,
                "title": record.title or f"Pendente #{record.id}",
                "date": record.document_date,
                "date_display": _display_date(record.document_date),
                "supplier_name": record.supplier_name or "-",
                "status": record.status,
                "extraction_state": "pendente",
                "comparison_state": record.comparison_state or "por_validar",
                "document_type": "pendente",
                "process_reference": record.process_reference or "-",
                "document_number": record.external_reference or f"PEND-{record.id}",
                "open_href": "",
                "tags": [],
            }
        )
    rows.sort(key=lambda row: (row["date"] or date.min, row["title"]), reverse=True)
    return rows


def _build_comparison_rows(
    structured_rows: list[dict[str, Any]],
    archive_rows: list[dict[str, Any]],
    record_tags: dict[int, list[VehicleDocumentRecordTag]],
    document_tags: dict[int, list[VehicleDocumentRecordTag]],
) -> list[dict[str, Any]]:
    work_orders = [row for row in structured_rows if row["main_group"] == "work_orders"]
    invoices = [row for row in archive_rows if row["archive_group"] == "invoices"]
    comparison_rows: list[dict[str, Any]] = []
    for work_order in work_orders:
        best_invoice = None
        best_score = None
        for invoice in invoices:
            date_gap = abs(((work_order["date"] or date.min) - (invoice["date"] or date.min)).days)
            if best_score is None or date_gap < best_score:
                best_score = date_gap
                best_invoice = invoice
        state = "por_validar"
        work_order_signature = _signature_from_tags(record_tags.get(work_order["id"], [])) if work_order["kind"] == "record" else set()
        invoice_signature = (
            _signature_from_tags(document_tags.get(best_invoice["id"], []))
            if best_invoice and best_invoice["kind"] == "document"
            else set()
        )
        if best_invoice and work_order_signature and invoice_signature:
            if work_order_signature == invoice_signature:
                state = "coerente"
            elif work_order_signature.issubset(invoice_signature) or invoice_signature.issubset(work_order_signature):
                state = "complementar"
            else:
                state = "divergente"
        elif best_invoice:
            state = "por_validar"
        comparison_rows.append(
            {
                "work_order": work_order,
                "invoice": best_invoice,
                "state": state,
                "state_label": DOCUMENT_HISTORY_COMPARISON_LABELS.get(state, state),
            }
        )
    return comparison_rows


def _build_timeline(
    structured_rows: list[dict[str, Any]],
    archive_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    def timeline_side(group: str) -> str | None:
        if group in {"contracts", "impros"}:
            return "center"
        if group in {"invoices", "claims"}:
            return "left"
        if group in {"work_orders", "ars", "diagnostics"}:
            return "right"
        return None

    def side_rank(group: str) -> int:
        order = {
            "invoices": 10,
            "claims": 20,
            "contracts": 10,
            "impros": 20,
            "work_orders": 10,
            "ars": 20,
            "diagnostics": 30,
        }
        return order.get(group, 999)

    def format_km(value: int | None) -> str:
        return f"{value:,}".replace(",", " ") if value is not None else "-"

    def make_card(event: TimelineEvent) -> dict[str, Any]:
        return {
            "group": event.group,
            "group_label": event.label,
            "title": event.title,
            "secondary": event.secondary or "-",
            "km": format_km(event.km) if event.km is not None else "",
            "state": event.state,
            "is_grouped": False,
            "items": [],
        }

    def make_grouped_diagnostics(events_for_day: list[TimelineEvent]) -> dict[str, Any]:
        count = len(events_for_day)
        suffix = "relatório" if count == 1 else "relatórios"
        ordered_items = sorted(events_for_day, key=lambda item: (item.title or "", item.secondary or ""))
        return {
            "group": "diagnostics",
            "group_label": DOCUMENT_HISTORY_MAIN_GROUP_LABELS["diagnostics"],
            "title": f"Diagnósticos - {count} {suffix}",
            "secondary": "Grupo diário",
            "km": "",
            "state": "grouped",
            "is_grouped": True,
            "items": [
                {
                    "title": item.title,
                    "secondary": item.secondary or "-",
                    "km": format_km(item.km) if item.km is not None else "",
                }
                for item in ordered_items
            ],
        }

    events: list[TimelineEvent] = []
    for row in structured_rows:
        if row["main_group"] not in DOCUMENT_HISTORY_MAIN_GROUP_LABELS:
            continue
        if timeline_side(row["main_group"]) is None:
            continue
        events.append(
            TimelineEvent(
                group=row["main_group"],
                label=DOCUMENT_HISTORY_MAIN_GROUP_LABELS.get(row["main_group"], row["main_group"]),
                title=row["title"],
                secondary=row["supplier_name"],
                occurred_on=row["date"],
                km=row["km"],
                state=row.get("status") or "structured",
                record_id=row["id"],
                source_kind=row["kind"],
            )
        )
    for row in archive_rows:
        if row["kind"] != "document":
            continue
        if row["main_group"] not in {"invoices", "diagnostics"}:
            continue
        if timeline_side(row["main_group"]) is None:
            continue
        events.append(
            TimelineEvent(
                group=row["main_group"],
                label=DOCUMENT_HISTORY_MAIN_GROUP_LABELS.get(row["main_group"], row["main_group"]),
                title=row["title"],
                secondary=row["supplier_name"],
                occurred_on=row["date"],
                km=None,
                state=row["status"],
                document_id=row["id"],
                source_kind="document",
            )
        )

    events.sort(key=lambda event: (event.occurred_on or date.min, event.km or -1, event.title))
    last_km = None
    rows_by_date: dict[date | None, dict[str, Any]] = {}
    has_center_content = False
    for event in events:
        km_regressive = bool(last_km is not None and event.km is not None and event.km < last_km)
        if event.km is not None:
            last_km = event.km
        bucket = rows_by_date.setdefault(
            event.occurred_on,
            {
                "occurred_on": event.occurred_on,
                "date": event.occurred_on.strftime("%d/%m/%Y") if event.occurred_on else "-",
                "date_iso": event.occurred_on.isoformat() if event.occurred_on else "",
                "left": [],
                "center": [],
                "right": [],
                "diagnostics_raw": [],
                "km_regressive": False,
            },
        )
        bucket["km_regressive"] = bucket["km_regressive"] or km_regressive
        side = timeline_side(event.group)
        if side == "right" and event.group == "diagnostics":
            bucket["diagnostics_raw"].append(event)
        elif side:
            bucket[side].append(make_card(event))
            if side == "center":
                has_center_content = True

    rendered: list[dict[str, Any]] = []
    sorted_dates = sorted(rows_by_date.keys(), key=lambda value: (value is not None, value or date.min), reverse=True)
    for occurred_on in sorted_dates:
        bucket = rows_by_date[occurred_on]
        if bucket["diagnostics_raw"]:
            bucket["right"].append(make_grouped_diagnostics(bucket["diagnostics_raw"]))
        bucket["left"].sort(key=lambda item: side_rank(item["group"]))
        bucket["center"].sort(key=lambda item: side_rank(item["group"]))
        bucket["right"].sort(key=lambda item: side_rank(item["group"]))
        rendered.append(
            {
                "date": bucket["date"],
                "date_iso": bucket["date_iso"],
                "left": bucket["left"],
                "center": bucket["center"],
                "right": bucket["right"],
                "km_regressive": bucket["km_regressive"],
            }
        )

    if not has_center_content:
        rendered.insert(
            0,
            {
                "date": "-",
                "date_iso": "",
                "left": [],
                "center": [
                    {
                        "group": "free",
                        "group_label": "Sem utilização",
                        "title": "Sem utilização",
                        "secondary": "Sem contratos ou impros associados nesta timeline.",
                        "km": "",
                        "state": "info",
                        "is_grouped": False,
                        "items": [],
                    }
                ],
                "right": [],
                "km_regressive": False,
            },
        )

    segments = [
        {"css": "contract", "label": "Contrato", "left": 0, "width": 33},
        {"css": "impro", "label": "Impro", "left": 33, "width": 33},
        {"css": "free", "label": "Sem utilização", "left": 66, "width": 34},
    ]
    ticks = rendered
    return rendered, ticks, segments


def vehicle_document_module_context(db: Session, vehicle: Vehicle) -> dict[str, Any]:
    documents = _load_vehicle_documents(db, vehicle)
    record_tags, document_tags = _tag_maps(db, vehicle.id)
    persisted_records = db.scalars(
        select(VehicleDocumentRecord)
        .where(VehicleDocumentRecord.vehicle_id == vehicle.id)
        .order_by(VehicleDocumentRecord.document_date.desc().nullslast(), VehicleDocumentRecord.id.desc())
    ).all()
    pending_archive_records = [record for record in persisted_records if record.main_group in {"invoices", "diagnostics"}]
    pending_archive_records = [
        record
        for record in pending_archive_records
        if record.source_record_type == "archive_pending"
    ]
    structured_rows = _build_structured_rows(db, vehicle.id, record_tags)
    archive_rows = _build_archive_rows(documents, document_tags, pending_archive_records)
    comparison_rows = _build_comparison_rows(structured_rows, archive_rows, record_tags, document_tags)
    timeline_events, timeline_ticks, timeline_segments = _build_timeline(structured_rows, archive_rows)
    alerts = _alert_rows(db, vehicle.id)
    pendings = _pending_rows(db, vehicle.id)

    # Alertas computados automáticos.
    for row in archive_rows:
        if row["kind"] == "pending_record" and row["archive_group"] == "invoices":
            alerts.append(
                {
                    "title": "Fatura sem PDF associado",
                    "detail": f"{row['title']} continua pendente de associação ao documento real.",
                    "severity": "warning",
                    "severity_label": "Aviso",
                    "source": "computed",
                }
            )
            pendings.append(
                {
                    "title": "Associar PDF em falta",
                    "detail": f"Ligar documento real à entrada pendente {row['document_number']}.",
                    "status": "open",
                    "source": "computed",
                    "action_type": "associate_document",
                }
            )
    for compare_row in comparison_rows:
        if compare_row["state"] == "divergente":
            work_order = compare_row["work_order"]["title"]
            invoice = compare_row["invoice"]["title"] if compare_row["invoice"] else "sem fatura"
            alerts.append(
                {
                    "title": "Divergência documental",
                    "detail": f"{work_order} não coincide com {invoice}.",
                    "severity": "warning",
                    "severity_label": "Aviso",
                    "source": "computed",
                }
            )
    for event in timeline_events:
        if event["km_regressive"]:
            alerts.append(
                {
                    "title": "KM regressivo",
                    "detail": f"{event['title']} apresenta km inferior ao documento anterior.",
                    "severity": "critical",
                    "severity_label": "Crítico",
                    "source": "computed",
                }
            )

    audit_fields = {
        field.field_code: field
        for field in db.scalars(
            select(VehicleDocumentAuditField)
            .where(VehicleDocumentAuditField.vehicle_id == vehicle.id)
            .order_by(VehicleDocumentAuditField.id.asc())
        ).all()
    }
    document_options = [
        {
            "id": document.id,
            "label": f"{_display_title(document)} ({_display_date(document.document_date) if document.document_date else 's/data'})",
        }
        for document in documents[:200]
    ]
    group_counts = {code: 0 for code, _ in DOCUMENT_HISTORY_MAIN_GROUPS}
    for row in structured_rows:
        group_counts[row["main_group"]] = group_counts.get(row["main_group"], 0) + 1
    for row in archive_rows:
        if row["kind"] == "document" and row["main_group"] in {"invoices", "diagnostics"}:
            group_counts[row["main_group"]] = group_counts.get(row["main_group"], 0) + 1

    return {
        "group_counts": group_counts,
        "archive_rows": archive_rows,
        "structured_rows": structured_rows,
        "comparison_rows": comparison_rows,
        "timeline_events": timeline_events,
        "timeline_ticks": timeline_ticks,
        "timeline_segments": timeline_segments,
        "alerts": alerts,
        "pendings": pendings,
        "audit_fields": audit_fields,
        "document_options": document_options,
        "record_tags": record_tags,
        "document_tags": document_tags,
        "archive_documents_count": len(archive_rows),
        "structured_documents_count": len(structured_rows),
    }


def save_uploaded_spreadsheet(upload) -> Path:
    suffix = Path(upload.filename or "upload.xlsx").suffix or ".xlsx"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.file.read())
        return Path(tmp.name)
