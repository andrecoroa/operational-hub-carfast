from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.documents import (
    Document,
    DocumentEvent,
    VehicleDocumentAlert,
    VehicleDocumentAuditField,
    VehicleDocumentPendingAction,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.models.management_center import ClaimIncident, ClaimRentwayAR
from app.models.vehicles import Vehicle, VehicleIdentifier, VehicleManualField
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

STRUCTURED_IMPORT_KIND_LABELS = {
    "work_orders": "Folhas de obra",
    "work_order_details": "Detalhes de folhas de obra",
    "impros": "Impros",
    "contracts": "Contratos",
}

STRUCTURED_RECORD_TYPES = {"structured", "legacy_structured"}
RENTWAY_TIMELINE_GROUPS = {"contracts", "impros"}

STRUCTURED_IMPORT_KIND_ALIASES = {
    "workorders": "work_orders",
    "workorder": "work_orders",
    "folhasdeobra": "work_orders",
    "folhadeobra": "work_orders",
    "ordemdereparo": "work_orders",
    "ordensdereparo": "work_orders",
    "ordemreparo": "work_orders",
    "fo": "work_orders",
    "workorderdetails": "work_order_details",
    "workordersdetails": "work_order_details",
    "detalhesfolhadeobra": "work_order_details",
    "detalhefolhadeobra": "work_order_details",
    "detalhesfo": "work_order_details",
    "detalhefo": "work_order_details",
    "impros": "impros",
    "impro": "impros",
    "contracts": "contracts",
    "contract": "contracts",
    "contratos": "contracts",
    "contrato": "contracts",
    "rentalagreements": "contracts",
    "rentalagreement": "contracts",
    "rental": "contracts",
    "alugueres": "contracts",
    "aluguer": "contracts",
}


def canonical_structured_import_kind(*values: Any) -> str:
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        head = text.partition(":")[0]
        for candidate in (head, text):
            key = normalize_header(candidate)
            if key in STRUCTURED_IMPORT_KIND_ALIASES:
                return STRUCTURED_IMPORT_KIND_ALIASES[key]
            for alias, kind in STRUCTURED_IMPORT_KIND_ALIASES.items():
                if alias and alias in key:
                    return kind
    return ""


def structured_import_kind_for_document(document: Document) -> str:
    return canonical_structured_import_kind(
        document.source_subject,
        document.original_name,
        document.file_name,
        document.title,
        document.folder_path,
    )


def is_structured_import_source(document: Document) -> bool:
    if document.entry_channel == "structured_import":
        return True
    import_kind = structured_import_kind_for_document(document)
    if not import_kind:
        return False
    subject = document.source_subject or ""
    subject_kind = normalize_header(subject.partition(":")[0])
    suffix = Path(document.original_name or document.file_name or "").suffix.lower()
    blob = normalize_header(
        " ".join(
            str(value or "")
            for value in (
                document.title,
                document.original_name,
                document.file_name,
                document.folder_path,
                document.document_type,
                document.classification,
                subject,
            )
        )
    )
    return bool(
        document.source == "v2_clean_manual"
        and (
            "importacao" in blob
            or "importacoesestruturadas" in blob
            or "listagem" in blob
            or "structuredimport" in blob
            or suffix in {".xlsx", ".xls", ".csv"}
            or (":" in subject and subject_kind in STRUCTURED_IMPORT_KIND_ALIASES)
        )
    )

V2_CLEAN_DOCUMENT_SOURCES = ("workshop_v2_clean", "v2_clean_manual")
V2_CLEAN_REMOVED_STATUSES = {"removed", "deleted"}


def is_removed_document_status(status: str | None) -> bool:
    return (status or "").strip().lower() in V2_CLEAN_REMOVED_STATUSES


def v2_clean_document_visible_condition():
    return or_(Document.status.is_(None), ~Document.status.in_(V2_CLEAN_REMOVED_STATUSES))


def v2_clean_record_visible_condition():
    return or_(VehicleDocumentRecord.status.is_(None), ~VehicleDocumentRecord.status.in_(V2_CLEAN_REMOVED_STATUSES))


def structured_import_source_condition():
    return or_(
        Document.entry_channel == "structured_import",
        Document.source_subject.ilike("%structured%"),
        Document.source_subject.ilike("%import%"),
        Document.source_subject.ilike("%listagem%"),
        Document.title.ilike("%import%"),
        Document.title.ilike("%listagem%"),
        Document.folder_path.ilike("%Importacoes_Estruturadas%"),
        Document.original_name.ilike("%.xlsx"),
        Document.original_name.ilike("%.xls"),
        Document.original_name.ilike("%.csv"),
        Document.file_name.ilike("%.xlsx"),
        Document.file_name.ilike("%.xls"),
        Document.file_name.ilike("%.csv"),
    )

DOCUMENT_HISTORY_COMPARISON_STATES = [
    ("coerente", "Coerente"),
    ("complementar", "Complementar"),
    ("divergente", "Divergente"),
    ("por_validar", "Por validar"),
    ("validado", "Validado"),
    ("imported_rentway", "Importado RW"),
]
DOCUMENT_HISTORY_COMPARISON_LABELS = dict(DOCUMENT_HISTORY_COMPARISON_STATES)

DOCUMENT_HISTORY_ALERT_SEVERITIES = [
    ("warning", "Aviso"),
    ("critical", "Crítico"),
    ("info", "Informativo"),
]
DOCUMENT_HISTORY_ALERT_LABELS = dict(DOCUMENT_HISTORY_ALERT_SEVERITIES)

DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS: dict[str, list[tuple[str, str]]] = {
    "maintenance": [("revision", "Revisão"), ("degradation", "Degradação"), ("undefined", "Por definir")],
    "pads": [("undefined", "Por definir"), ("front", "FR"), ("rear", "TR"), ("both", "FR + TR")],
    "discs": [("undefined", "Por definir"), ("front", "FR"), ("rear", "TR"), ("both", "FR + TR")],
    "tyres": [("undefined", "Por definir"), ("front", "FR"), ("rear", "TR"), ("both", "FR + TR"), ("puncture", "Furo")],
    "ipo": [("yes", "IPO"), ("undefined", "Por definir")],
    "fault": [("free_text", "Texto livre")],
    "services": [("telecharge", "Telecarregamento"), ("other", "Outro")],
    "repair": [("free_text", "Texto livre")],
    "other": [("free_text", "Texto livre")],
}
DOCUMENT_HISTORY_QUICK_CLASSIFICATION_LABELS = {
    "maintenance": "Manutenção",
    "pads": "Calços",
    "discs": "Discos",
    "tyres": "Pneus",
    "ipo": "IPO",
    "fault": "Avaria",
    "services": "Serviços",
    "repair": "Reparação",
    "other": "Outro",
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
    end_on: date | None = None
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


def _row_text(row: tuple[Any, ...], cols: dict[str, int], candidates: list[str]) -> str:
    return _normalize_text(first_row_value(row, cols, candidates))


def _row_date(row: tuple[Any, ...], cols: dict[str, int], candidates: list[str]) -> date | None:
    return _safe_date(first_row_value(row, cols, candidates))


RENTWAY_START_DATE_COLUMNS = [
    "Data início",
    "Data Inicio",
    "Data de início",
    "Data de Inicio",
    "Início",
    "Inicio",
    "Início contrato",
    "Inicio contrato",
    "Data início contrato",
    "Data inicio contrato",
    "Start Date",
    "Start",
    "Rental Start",
    "Rental_Start",
    "Contract Start",
    "Data contrato",
    "Date_Out",
    "date_out",
    "Checkout",
    "Checkout Date",
    "Checkout_Date",
    "Pick Up",
    "Pickup",
    "Pickup Date",
    "Data levantamento",
    "Data saída",
    "Data saida",
    "Saída",
    "Saida",
    "Data entrega",
    "Entrega",
    "Data inicial",
    "Data de",
    "De",
]

RENTWAY_END_DATE_COLUMNS = [
    "Data fim",
    "Data de fim",
    "Fim",
    "Fim contrato",
    "Data fim contrato",
    "End Date",
    "End",
    "Rental End",
    "Rental_End",
    "Contract End",
    "Data término",
    "Data Termino",
    "Date_In",
    "date_in",
    "Checkin",
    "Checkin Date",
    "Checkin_Date",
    "Check In",
    "Return",
    "Return Date",
    "Data retorno",
    "Data entrada",
    "Data devolução",
    "Data devolucao",
    "Devolução",
    "Devolucao",
    "Data final",
    "Data até",
    "Data ate",
    "Até",
    "Ate",
]


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
    identifiers = db.scalars(select(VehicleIdentifier).where(VehicleIdentifier.active == True)).all()  # noqa: E712
    vehicle_by_id = {vehicle.id: vehicle for vehicle in vehicles}
    for identifier in identifiers:
        vehicle = vehicle_by_id.get(identifier.vehicle_id)
        key = normalize_header(identifier.identifier_value or "")
        if not vehicle or not key:
            continue
        if identifier.identifier_type == "plate" and key not in by_plate:
            by_plate[key] = vehicle
        elif identifier.identifier_type == "vin" and key not in by_vin:
            by_vin[key] = vehicle
        elif identifier.identifier_type in {"unit", "rentway_unit_nr"} and key not in by_unit:
            by_unit[key] = vehicle
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
        # Imports launched from a vehicle file are intentionally scoped to that vehicle.
        # Global imports still resolve each row by plate, VIN or Rentway unit below.
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
    if main_group == "work_orders" and external_reference:
        return db.scalar(
            select(VehicleDocumentRecord)
            .where(
                VehicleDocumentRecord.main_group == main_group,
                VehicleDocumentRecord.external_reference == external_reference,
            )
            .limit(1)
        )
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
    comparison_state: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    source_document_id: int | None = None,
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
        record.vehicle_id = vehicle_id
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
        if comparison_state is not None:
            record.comparison_state = comparison_state
        existing_metadata = record.metadata_json if isinstance(record.metadata_json, dict) else {}
        incoming_metadata = metadata_json if isinstance(metadata_json, dict) else {}
        record.metadata_json = {**existing_metadata, **incoming_metadata}
        if source_document_id is not None:
            record.document_id = source_document_id
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
        comparison_state=comparison_state,
        metadata_json=metadata_json,
        document_id=source_document_id,
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


def import_work_orders_xlsx(
    db: Session,
    *,
    path: Path,
    vehicle: Vehicle | None = None,
    source_document: Document | None = None,
    user_id: int | None = None,
) -> int:
    imported = 0
    by_plate, by_vin, by_unit = _vehicle_lookup_maps(db)
    seen_work_order_numbers: set[str] = set()
    for _sheet, headers, _row_number, row, raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        plate = _normalize_text(first_row_value(row, cols, ["Matrícula", "Matricula", "PlateNr"]))
        title = _normalize_text(first_row_value(row, cols, ["Número", "Numero", "FO", "Folha de obra"]))
        external_reference = title or None
        if not external_reference:
            continue
        work_order_key = normalize_header(external_reference)
        if work_order_key in seen_work_order_numbers:
            continue
        seen_work_order_numbers.add(work_order_key)
        row_vehicle = _resolve_vehicle_for_import_row(
            fallback_vehicle=vehicle,
            by_plate=by_plate,
            by_vin=by_vin,
            by_unit=by_unit,
            plate=plate,
        )
        if not row_vehicle:
            continue
        document_date = _safe_date(first_row_value(row, cols, ["Data", "DocumentDate"]))
        supplier_name = _normalize_text(first_row_value(row, cols, ["Nome fornecedor", "Fornecedor", "Supplier"]))
        raw_description = _normalize_text(first_row_value(row, cols, ["Observações", "Observacoes", "Descrição", "Descricao"]))
        km = clean_int(first_row_value(row, cols, ["Kms", "KM", "Km", "Quilómetros", "Quilometros"]))
        upsert_structured_record(
            db,
            vehicle_id=row_vehicle.id,
            main_group="work_orders",
            title=title or "Folha de obra",
            external_reference=external_reference,
            document_date=document_date,
            supplier_name=supplier_name or None,
            raw_description=raw_description or None,
            km=km,
            source_system="work_order_import",
            plate=row_vehicle.plate,
            vin=row_vehicle.vin,
            metadata_json={**raw, "work_order_header": raw},
            source_document_id=source_document.id if source_document else None,
            user_id=user_id,
        )
        imported += 1
    return imported


def _work_order_reference(row: dict[str, Any], cols: dict[str, int]) -> str:
    return _normalize_text(
        first_row_value(
            row,
            cols,
            [
                "Folha de obra nº",
                "Folha de obra n.º",
                "Folha de obra",
                "Nº folha de obra",
                "Número folha de obra",
                "Numero folha de obra",
                "Número FO",
                "Numero FO",
                "Nº FO",
                "FO",
                "Ordem de reparo",
                "Ordem reparo",
                "Número",
                "Numero",
            ],
        )
    )


def _work_order_detail_item(
    row: dict[str, Any],
    cols: dict[str, int],
    raw: dict[str, Any],
    *,
    row_number: int,
) -> dict[str, Any]:
    description = _normalize_text(
        first_row_value(
            row,
            cols,
            [
                "Descrição",
                "Descricao",
                "Designação",
                "Designacao",
                "Serviço",
                "Servico",
                "Trabalho",
                "Observações",
                "Observacoes",
                "Texto",
            ],
        )
    )
    reference = _normalize_text(
        first_row_value(row, cols, ["Referência", "Referencia", "Código", "Codigo", "Artigo", "Item"])
    )
    quantity = first_row_value(row, cols, ["Quantidade", "Qtd", "Qty"])
    unit = _normalize_text(first_row_value(row, cols, ["Unidade", "Un", "Unit"]))
    unit_price = first_row_value(
        row,
        cols,
        ["Preço unitário", "Preco unitario", "Valor unitário", "Valor unitario", "Preço", "Preco"],
    )
    amount = first_row_value(row, cols, ["Total", "Valor total", "Montante", "Valor"])
    return {
        "row_number": row_number,
        "reference": reference or "-",
        "description": description or "-",
        "quantity": quantity if quantity not in (None, "") else "-",
        "unit": unit or "-",
        "unit_price": unit_price if unit_price not in (None, "") else "-",
        "amount": amount if amount not in (None, "") else "-",
        "raw": raw,
    }


def import_work_order_details_xlsx(
    db: Session,
    *,
    path: Path,
    source_document: Document | None = None,
    user_id: int | None = None,
) -> int:
    """Attach one or more detail lines to an existing work order by FO number."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    header_updates: dict[str, dict[str, Any]] = {}
    for _sheet, headers, row_number, row, raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        reference = _work_order_reference(row, cols)
        if not reference:
            continue
        key = normalize_header(reference)
        if not key:
            continue
        grouped.setdefault(key, []).append(_work_order_detail_item(row, cols, raw, row_number=row_number))
        header_updates[key] = {
            "reference": reference,
            "km": clean_int(first_row_value(row, cols, ["Kms", "KM", "Km", "Quilómetros", "Quilometros"])),
            "document_date": _safe_date(first_row_value(row, cols, ["Data", "DocumentDate"])),
            "supplier_name": _normalize_text(first_row_value(row, cols, ["Nome fornecedor", "Fornecedor", "Supplier"])),
        }

    candidate_records = db.scalars(
        select(VehicleDocumentRecord).where(
            VehicleDocumentRecord.main_group == "work_orders",
            VehicleDocumentRecord.external_reference.is_not(None),
        )
    ).all()
    records_by_reference = {
        normalize_header(item.external_reference or ""): item
        for item in candidate_records
        if normalize_header(item.external_reference or "")
    }
    attached_lines = 0
    for key, items in grouped.items():
        record = records_by_reference.get(key)
        if not record:
            continue
        metadata = dict(record.metadata_json) if isinstance(record.metadata_json, dict) else {}
        metadata["work_order_lines"] = items
        metadata["work_order_details_source_document_id"] = source_document.id if source_document else None
        record.metadata_json = metadata
        updates = header_updates.get(key, {})
        if updates.get("km") is not None:
            record.km = updates["km"]
        if updates.get("document_date") and record.document_date is None:
            record.document_date = updates["document_date"]
        if updates.get("supplier_name") and not record.supplier_name:
            record.supplier_name = updates["supplier_name"]
        record.updated_by_id = user_id
        attached_lines += len(items)
    return attached_lines


def detect_structured_import_vehicle_ids(db: Session, *, path: Path, import_kind: str) -> set[int]:
    vehicle_ids: set[int] = set()
    by_plate, by_vin, by_unit = _vehicle_lookup_maps(db)
    for _sheet, headers, _row_number, row, _raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        plate_candidates = ["Matrícula", "Matricula", "PlateNr"]
        vin = None
        unit = None
        if import_kind == "contracts":
            plate_candidates = ["Matrícula", "Matricula", "PlateNr", "Plate"]
            vin = _normalize_text(first_row_value(row, cols, ["Chassi", "VIN", "Vin", "Chassis"]))
            unit = _normalize_text(first_row_value(row, cols, ["Unit", "UnitNr", "Unit Nr", "Unit Rentway"]))
        plate = _normalize_text(first_row_value(row, cols, plate_candidates))
        row_vehicle = _resolve_vehicle_for_import_row(
            fallback_vehicle=None,
            by_plate=by_plate,
            by_vin=by_vin,
            by_unit=by_unit,
            plate=plate,
            vin=vin,
            unit=unit,
        )
        if row_vehicle:
            vehicle_ids.add(row_vehicle.id)
    return vehicle_ids


def import_impros_xlsx(
    db: Session,
    *,
    path: Path,
    vehicle: Vehicle | None = None,
    source_document: Document | None = None,
    user_id: int | None = None,
) -> int:
    imported = 0
    by_plate, by_vin, by_unit = _vehicle_lookup_maps(db)
    for _sheet, headers, _row_number, row, raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        plate = _row_text(row, cols, ["PlateNr", "Plate", "Matrícula", "Matricula"])
        row_vehicle = _resolve_vehicle_for_import_row(
            fallback_vehicle=vehicle,
            by_plate=by_plate,
            by_vin=by_vin,
            by_unit=by_unit,
            plate=plate,
        )
        if not row_vehicle:
            continue
        impro_number = _row_text(row, cols, ["Impro", "Impro Nr", "Impro Nº", "impro_number", "Número impro", "Numero impro"])
        status = _row_text(row, cols, ["Status", "Estado"])
        date_in = _row_date(row, cols, ["Date_In", "Data entrada", *RENTWAY_START_DATE_COLUMNS])
        date_out = _row_date(row, cols, ["Date_Out", "Data saída", "Data saida", *RENTWAY_END_DATE_COLUMNS])
        driven_kms = clean_int(first_row_value(row, cols, ["Driven_Kms", "Driven Kms", "Km", "Kms", "KM"]))
        title = impro_number or "Impro"
        description_parts = [
            _row_text(row, cols, ["Impro_Type_Description", "Impro Type Description", "Tipo impro", "Descrição", "Descricao"]),
            _row_text(row, cols, ["Garage", "Oficina", "Fornecedor"]),
            _row_text(row, cols, ["Driver_Name", "Driver Name", "Condutor"]),
        ]
        raw_description = " | ".join(part for part in description_parts if part) or None
        upsert_structured_record(
            db,
            vehicle_id=row_vehicle.id,
            main_group="impros",
            title=title,
            external_reference=impro_number,
            document_date=date_in,
            supplier_name=_row_text(row, cols, ["Garage", "Oficina", "Fornecedor"]) or None,
            raw_description=raw_description,
            km=driven_kms,
            source_system="impro_import",
            plate=row_vehicle.plate,
            vin=row_vehicle.vin,
            subtype=_row_text(row, cols, ["Impro_Type_Code", "Impro Type Code", "Tipo"]) or None,
            comparison_state="imported_rentway",
            metadata_json={
                **raw,
                "_status": status or None,
                "_start_date": date_in.isoformat() if date_in else None,
                "_date_out": date_out.isoformat() if date_out else None,
                "_period_source": "rentway",
            },
            source_document_id=source_document.id if source_document else None,
            user_id=user_id,
        )
        imported += 1
    return imported


def import_contracts_xlsx(
    db: Session,
    *,
    path: Path,
    vehicle: Vehicle | None = None,
    source_document: Document | None = None,
    user_id: int | None = None,
) -> int:
    imported = 0
    by_plate, by_vin, by_unit = _vehicle_lookup_maps(db)
    for _sheet, headers, _row_number, row, raw in iter_xlsx_rows(path):
        cols = build_column_lookup(headers)
        plate = _row_text(row, cols, ["Matrícula", "Matricula", "PlateNr", "Plate", "License Plate"])
        vin = _row_text(row, cols, ["Chassi", "VIN", "Vin", "Chassis"])
        unit = _row_text(row, cols, ["Unit", "UnitNr", "Unit Nr", "Unit Rentway"])
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
                [
                    "Contrato",
                    "Nº Contrato",
                    "No Contrato",
                    "Numero Contrato",
                    "Contract",
                    "Contract Number",
                    "Rental Agreement",
                    "Agreement",
                    "ra",
                    "RA",
                ],
            )
        )
        ra_reference = _row_text(row, cols, ["ra", "RA", "Rental Agreement", "Agreement"])
        supplier_name = _row_text(
            row,
            cols,
            [
                "Fornecedor",
                "Locadora",
                "Financeira",
                "Entidade",
                "Supplier",
                "customer_name",
                "Customer Name",
                "Cliente",
                "Client",
            ],
        )
        start_date = _row_date(row, cols, RENTWAY_START_DATE_COLUMNS)
        end_date = _row_date(row, cols, RENTWAY_END_DATE_COLUMNS)
        status = _row_text(row, cols, ["Estado", "Status"])
        monthly_value = _normalize_text(
            first_row_value(row, cols, ["Valor mensal", "Renda", "Mensalidade", "Monthly Value", "Valor", "invoiced_amount"])
        )
        notes = _row_text(row, cols, ["Observações", "Observacoes", "Descrição", "Descricao", "Notes"])
        station = _row_text(row, cols, ["station", "Estação", "Estacao", "Rental Station"])
        origin = _row_text(row, cols, ["origin", "Origem", "Source"])
        rate_code = _row_text(row, cols, ["rate_code", "Rate Code"])
        category = _row_text(row, cols, ["category", "Categoria", "Vehicle Category"])
        category_requested = _row_text(row, cols, ["category_requested", "Categoria pedida", "Requested Category"])
        ndays = _row_text(row, cols, ["ndays", "Dias", "Days"])
        creation_date = _row_date(row, cols, ["creation_date", "Data criação", "Data criacao", "Created At"])
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
            comparison_state="imported_rentway",
            metadata_json={
                **raw,
                "_station": station or None,
                "_origin": origin or None,
                "_rate_code": rate_code or None,
                "_category": category or None,
                "_category_requested": category_requested or None,
                "_status": status or None,
                "_start_date": start_date.isoformat() if start_date else None,
                "_creation_date": creation_date.isoformat() if creation_date else None,
                "_end_date": end_date.isoformat() if end_date else None,
                "_period_source": "rentway",
                "_monthly_value": monthly_value or None,
                "_cashier_amount": cashier_amount or None,
            },
            source_document_id=source_document.id if source_document else None,
            user_id=user_id,
        )
        imported += 1
    return imported


def _load_vehicle_documents(db: Session, vehicle: Vehicle) -> list[Document]:
    return db.scalars(
        select(Document)
        .where(
            or_(Document.vehicle_id == vehicle.id, Document.plate == vehicle.plate),
            Document.source.in_(V2_CLEAN_DOCUMENT_SOURCES),
            v2_clean_document_visible_condition(),
        )
        .order_by(Document.document_date.desc().nullslast(), Document.updated_at.desc(), Document.id.desc())
    ).all()


def _structured_import_expected_count(document: Document) -> int | None:
    subject = document.source_subject or ""
    _kind, _separator, count_text = subject.partition(":")
    try:
        return int((count_text or "").strip())
    except ValueError:
        return None


def _materialize_structured_import_source(
    db: Session,
    *,
    document: Document,
    user_id: int | None = None,
) -> int:
    import_kind = structured_import_kind_for_document(document)
    if import_kind not in STRUCTURED_IMPORT_KIND_LABELS:
        return 0
    source_path = Path(document.storage_path or "")
    if not source_path.exists():
        return 0
    vehicle = db.get(Vehicle, document.vehicle_id) if document.vehicle_id else None
    if import_kind == "work_orders":
        imported_count = import_work_orders_xlsx(
            db,
            path=source_path,
            vehicle=vehicle,
            source_document=document,
            user_id=user_id,
        )
    elif import_kind == "impros":
        imported_count = import_impros_xlsx(
            db,
            path=source_path,
            vehicle=vehicle,
            source_document=document,
            user_id=user_id,
        )
    elif import_kind == "contracts":
        imported_count = import_contracts_xlsx(
            db,
            path=source_path,
            vehicle=vehicle,
            source_document=document,
            user_id=user_id,
        )
    else:
        imported_count = 0

    document.document_type = "general_fleet"
    document.classification = "fleet"
    document.source = "v2_clean_manual"
    document.entry_channel = "structured_import"
    document.source_subject = f"{import_kind}:{imported_count}"
    document.status = "archived"
    document.archived = True
    return imported_count


def _structured_import_is_already_materialized(
    *,
    expected_count: int | None,
    linked_count: int,
) -> bool:
    if expected_count is None:
        return False
    if expected_count <= 0:
        return linked_count > 0
    return linked_count == expected_count


def _ensure_structured_sources_materialized(
    db: Session,
    *,
    vehicle: Vehicle,
    documents: list[Document],
) -> bool:
    changed = False
    for document in documents:
        if not is_structured_import_source(document):
            continue
        import_kind = structured_import_kind_for_document(document)
        if import_kind not in STRUCTURED_IMPORT_KIND_LABELS:
            continue
        linked_count = len(
            db.scalars(
                select(VehicleDocumentRecord.id).where(
                    VehicleDocumentRecord.vehicle_id == vehicle.id,
                    VehicleDocumentRecord.source_record_type.in_(STRUCTURED_RECORD_TYPES),
                    VehicleDocumentRecord.main_group == import_kind,
                    VehicleDocumentRecord.document_id == document.id,
                    v2_clean_record_visible_condition(),
                )
            ).all()
        )
        expected_count = _structured_import_expected_count(document)
        if _structured_import_is_already_materialized(expected_count=expected_count, linked_count=linked_count):
            continue
        if _materialize_structured_import_source(db, document=document):
            changed = True
    return changed


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


def _service_value_label(category: str, value: str | None, free_text: str | None = None) -> str:
    if free_text:
        return free_text
    if not value:
        return "Por definir"
    option_labels = dict(DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS.get(category, []))
    return option_labels.get(value, value)


def _service_matrix_from_text_and_tags(
    text: str,
    tags: list[VehicleDocumentRecordTag],
) -> dict[str, str]:
    matrix = {
        "maintenance": "-",
        "pads": "-",
        "discs": "-",
        "tyres": "-",
        "ipo": "-",
        "other": "-",
    }
    values_by_category: dict[str, list[str]] = {key: [] for key in matrix}
    for tag in tags:
        target = tag.category if tag.category in matrix else "other" if tag.category in {"fault", "services", "repair"} else ""
        if not target:
            continue
        label = _service_value_label(tag.category, tag.value, tag.free_text)
        if label and label not in values_by_category[target]:
            values_by_category[target].append(label)
    for category, values in values_by_category.items():
        if values:
            matrix[category] = " · ".join(values)
    normalized = normalize_header(text or "")
    if matrix["maintenance"] == "-":
        if "degrad" in normalized and ("oleo" in normalized or "oil" in normalized):
            matrix["maintenance"] = "Degradação"
        elif "revis" in normalized or "manutenc" in normalized:
            matrix["maintenance"] = "Revisão"
    if matrix["pads"] == "-" and ("calco" in normalized or "pastilha" in normalized or "travo" in normalized):
        matrix["pads"] = "Por definir"
    if matrix["discs"] == "-" and "disco" in normalized:
        matrix["discs"] = "Por definir"
    if matrix["tyres"] == "-" and "furo" in normalized:
        matrix["tyres"] = "Furo"
    elif matrix["tyres"] == "-" and ("pneu" in normalized or "roda" in normalized):
        matrix["tyres"] = "Por definir"
    if matrix["ipo"] == "-" and ("ipo" in normalized or "inspec" in normalized):
        matrix["ipo"] = "IPO"
    return matrix


def _service_matrix_codes_from_tags(tags: list[VehicleDocumentRecordTag]) -> dict[str, list[str]]:
    matrix: dict[str, list[str]] = {key: [] for key in ("maintenance", "pads", "discs", "tyres", "ipo", "other")}
    for tag in tags:
        code = tag.value or ("free_text" if tag.free_text else "")
        target = tag.category if tag.category in matrix else "other" if tag.category in {"fault", "services", "repair"} else ""
        if target and code and code not in matrix[target]:
            matrix[target].append(code)
    return matrix


def _work_order_line_items(metadata: dict[str, Any] | list | str | int | float | bool | None) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []
    candidates = metadata.get("work_order_lines")
    if not isinstance(candidates, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            rows.append({"index": index, "reference": "-", "description": str(item), "quantity": "-", "unit": "-", "unit_price": "-", "amount": "-"})
            continue
        rows.append(
            {
                "index": index,
                "reference": item.get("reference") or "-",
                "description": item.get("description") or "-",
                "quantity": item.get("quantity") if item.get("quantity") not in (None, "") else "-",
                "unit": item.get("unit") or "-",
                "unit_price": item.get("unit_price") if item.get("unit_price") not in (None, "") else "-",
                "amount": item.get("amount") if item.get("amount") not in (None, "") else "-",
            }
        )
    return rows


def _service_summary(matrix: dict[str, str]) -> list[str]:
    labels = []
    category_labels = {
        "maintenance": "Manutenção",
        "pads": "Calços",
        "discs": "Discos",
        "tyres": "Pneus",
        "ipo": "IPO",
        "other": "Outro",
    }
    for category, label in category_labels.items():
        value = matrix.get(category, "-")
        if value not in ("", "-", "Por definir"):
            labels.append(f"{label}: {value}" if category != "ipo" else value)
    return labels


def _custom_service_values(tags: list[VehicleDocumentRecordTag]) -> list[str]:
    return list(
        dict.fromkeys(
            tag.free_text.strip()
            for tag in tags
            if tag.category in {"other", "services", "repair", "fault"} and tag.free_text and tag.free_text.strip()
        )
    )


def _invoice_line_items(metadata: dict[str, Any] | list | str | int | float | bool | None) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []
    candidates = (
        metadata.get("invoice_lines")
        or metadata.get("line_items")
        or metadata.get("lines")
        or metadata.get("items")
        or metadata.get("linhas")
    )
    if not isinstance(candidates, list):
        return []
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(candidates, start=1):
        if isinstance(item, dict):
            reference = item.get("reference") or item.get("referencia") or item.get("code") or item.get("codigo") or ""
            description = item.get("description") or item.get("descricao") or item.get("text") or item.get("linha") or ""
            quantity = item.get("quantity") or item.get("qty") or item.get("quantidade") or ""
            unit = item.get("unit") or item.get("un") or item.get("unidade") or ""
            unit_price = item.get("unit_price") or item.get("preco_unitario") or item.get("preço_unitário") or ""
            tax = item.get("tax") or item.get("iva") or item.get("vat") or ""
            amount = item.get("amount") or item.get("total") or item.get("value") or item.get("valor") or ""
            service = item.get("service") or item.get("servico") or item.get("classification") or "Por classificar"
            service_detail = item.get("service_detail") or item.get("detail") or item.get("detalhe") or ""
        else:
            reference = ""
            description = str(item)
            quantity = ""
            unit = ""
            unit_price = ""
            tax = ""
            amount = ""
            service = "Por classificar"
            service_detail = ""
        rows.append(
            {
                "index": index,
                "reference": reference or "-",
                "description": description or "-",
                "quantity": quantity or "-",
                "unit": unit or "-",
                "unit_price": unit_price or "-",
                "tax": tax or "-",
                "amount": amount or "-",
                "service": f"{service}: {service_detail}" if service_detail and service not in ("", "Por classificar") else (service or "Por classificar"),
            }
        )
    return rows


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


def _metadata_date(metadata: dict[str, Any] | None, key: str) -> date | None:
    value = (metadata or {}).get(key)
    if not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _metadata_date_from_candidates(metadata: dict[str, Any] | None, candidates: list[str]) -> date | None:
    if not isinstance(metadata, dict):
        return None
    by_header = {normalize_header(key): value for key, value in metadata.items() if key}
    for candidate in candidates:
        value = by_header.get(normalize_header(candidate))
        parsed = _safe_date(value)
        if parsed:
            return parsed
    return None


def _timeline_period_dates(row: VehicleDocumentRecord) -> tuple[date | None, date | None]:
    metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
    start = (
        _metadata_date(metadata, "_start_date")
        or _metadata_date_from_candidates(metadata, RENTWAY_START_DATE_COLUMNS)
        or row.document_date
    )
    if row.main_group == "contracts":
        end = _metadata_date(metadata, "_end_date") or _metadata_date_from_candidates(metadata, RENTWAY_END_DATE_COLUMNS)
    elif row.main_group == "impros":
        end = (
            _metadata_date(metadata, "_date_out")
            or _metadata_date(metadata, "_end_date")
            or _metadata_date_from_candidates(metadata, RENTWAY_END_DATE_COLUMNS)
        )
    else:
        end = None
    return start, end


def _structured_comparison_state(row: VehicleDocumentRecord) -> str:
    if row.comparison_state:
        return row.comparison_state
    if row.main_group in RENTWAY_TIMELINE_GROUPS:
        return "imported_rentway"
    return "por_validar"


def _structured_comparison_label(row: VehicleDocumentRecord) -> str:
    state = _structured_comparison_state(row)
    return DOCUMENT_HISTORY_COMPARISON_LABELS.get(state, state)


def _period_display(start: date | None, end: date | None) -> str:
    if start and end:
        return f"{_display_date(start)} a {_display_date(end)}"
    if start:
        return f"desde {_display_date(start)}"
    if end:
        return f"até {_display_date(end)}"
    return "-"


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
            VehicleDocumentRecord.source_record_type.in_(STRUCTURED_RECORD_TYPES),
            VehicleDocumentRecord.main_group.in_([code for code, _ in DOCUMENT_HISTORY_STRUCTURED_GROUPS]),
            v2_clean_record_visible_condition(),
        )
        .order_by(VehicleDocumentRecord.document_date.desc().nullslast(), VehicleDocumentRecord.id.desc())
    ).all()

    rows = []
    for row in persisted_rows:
        tags = record_tags.get(row.id, [])
        service_text = " ".join(part for part in [row.title, row.raw_description, row.external_reference] if part)
        service_matrix = _service_matrix_from_text_and_tags(service_text, tags)
        period_start, period_end = _timeline_period_dates(row)
        display_date = period_start or row.document_date
        comparison_state = _structured_comparison_state(row)
        rows.append(
            {
                "kind": "record",
                "id": row.id,
                "main_group": row.main_group,
                "group_label": DOCUMENT_HISTORY_STRUCTURED_GROUP_LABELS.get(row.main_group, row.main_group),
                "date": display_date,
                "date_display": _display_date(display_date),
                "title": row.title or row.external_reference or row.main_group,
                "supplier_name": row.supplier_name or "-",
                "km": row.km,
                "status": row.status,
                "comparison_state": comparison_state,
                "comparison_label": _structured_comparison_label(row),
                "process_reference": row.process_reference or "-",
                "description": row.raw_description or "",
                "external_reference": row.external_reference or "-",
                "service_matrix": service_matrix,
                "service_matrix_codes": _service_matrix_codes_from_tags(tags),
                "invoice_lines": _invoice_line_items(row.metadata_json),
                "work_order_lines": _work_order_line_items(row.metadata_json),
                "service_summary": _service_summary(service_matrix),
                "custom_services": _custom_service_values(tags),
                "period_start": period_start,
                "period_end": period_end,
                "period_display": _period_display(period_start, period_end),
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
    extraction_metadata: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    extraction_metadata = extraction_metadata or {}
    rows: list[dict[str, Any]] = []
    for document in documents:
        if is_structured_import_source(document):
            continue
        metadata = extraction_metadata.get(document.id) or {}
        archive_group = _document_archive_group(document)
        tags = document_tags.get(document.id, [])
        service_text = " ".join(
            part
            for part in [document.title, document.original_name, document.supplier_name, document.contract_number, document.reservation_number]
            if part
        )
        service_matrix = _service_matrix_from_text_and_tags(service_text, tags)
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
                "km": clean_int(metadata.get("km")),
                "total_with_vat": metadata.get("total_with_vat") or metadata.get("invoice_total_with_vat") or "",
                "work_order_reference": metadata.get("work_order_reference") or metadata.get("repair_order_reference") or "",
                "status": document.status,
                "extraction_state": "validado" if tags or document.status == "classified" else "por_validar",
                "comparison_state": "validado" if tags or document.status == "classified" else "por_validar",
                "comparison_label": "Validado" if tags or document.status == "classified" else "Por validar",
                "document_type": document.document_type or "-",
                "process_reference": f"Oficina #{document.workshop_process_id}" if document.workshop_process_id else "-",
                "document_number": document.contract_number or document.reservation_number or str(document.id),
                "open_href": f"/v2-clean/documents/{document.id}",
                "tags": [_format_tag(tag) for tag in tags],
                "service_matrix": service_matrix,
                "service_matrix_codes": _service_matrix_codes_from_tags(tags),
                "invoice_lines": _invoice_line_items(metadata),
                "work_order_lines": [],
                "service_summary": _service_summary(service_matrix),
                "custom_services": _custom_service_values(tags),
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
                "service_matrix": _service_matrix_from_text_and_tags(record.title or record.raw_description or "", []),
                "service_matrix_codes": _service_matrix_codes_from_tags([]),
                "invoice_lines": [],
                "work_order_lines": [],
                "service_summary": _service_summary(
                    _service_matrix_from_text_and_tags(record.title or record.raw_description or "", [])
                ),
                "custom_services": [],
            }
        )
    rows.sort(key=lambda row: (row["date"] or date.min, row["title"]), reverse=True)
    return rows


def _document_extraction_metadata(db: Session, document_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not document_ids:
        return {}
    supported_actions = {
        "invoice.ocr.extracted",
        "invoice.ocr.reprocessed",
        "invoice.lines.extracted",
        "invoice.extracted",
        "document.ocr.extracted",
        "ocr.extracted",
    }
    events = db.scalars(
        select(DocumentEvent)
        .where(
            DocumentEvent.document_id.in_(document_ids),
            DocumentEvent.action.in_(supported_actions),
        )
        .order_by(DocumentEvent.id)
    ).all()
    metadata: dict[int, dict[str, Any]] = {}
    for event in events:
        try:
            parsed = json.loads(event.new_value or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, list):
            parsed = {"invoice_lines": parsed}
        if isinstance(parsed, dict):
            metadata.setdefault(event.document_id, {}).update(parsed)
    return metadata


def _build_import_rows(documents: list[Document]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for document in documents:
        if not is_structured_import_source(document):
            continue
        subject = document.source_subject or ""
        _raw_kind, _, count_text = subject.partition(":")
        import_kind = structured_import_kind_for_document(document) or "structured"
        rows.append(
            {
                "id": document.id,
                "title": _display_title(document),
                "date": document.document_date,
                "date_display": _display_date(document.document_date or document.created_at),
                "import_kind": import_kind,
                "import_label": STRUCTURED_IMPORT_KIND_LABELS.get(import_kind, import_kind or "Listagem"),
                "imported_count": count_text or "-",
                "file_name": document.original_name or document.file_name or "-",
                "status": document.status or "-",
                "open_href": f"/v2-clean/documents/{document.id}",
            }
        )
    rows.sort(key=lambda row: (row["date"] or date.min, row["id"]), reverse=True)
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
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
        period = _period_display(event.occurred_on, event.end_on) if event.group in {"contracts", "impros"} else ""
        return {
            "group": event.group,
            "group_label": event.label,
            "title": event.title,
            "secondary": event.secondary or "-",
            "period": period,
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

    def make_free_card() -> dict[str, Any]:
        return {
            "group": "free",
            "group_label": "Sem utilização",
            "title": "Sem utilização",
            "secondary": "Sem contrato ou impro ativo nesta data.",
            "period": "",
            "km": "",
            "state": "info",
            "is_grouped": False,
            "items": [],
        }

    def period_contains(event: TimelineEvent, value: date | None) -> bool:
        if value is None or event.group not in {"contracts", "impros"} or event.occurred_on is None:
            return False
        if event.end_on:
            return event.occurred_on <= value <= event.end_on
        return event.occurred_on <= value

    def period_overlaps(event: TimelineEvent, start: date, end: date) -> bool:
        if event.group not in {"contracts", "impros"} or event.occurred_on is None:
            return False
        period_end = event.end_on or event.occurred_on
        return event.occurred_on <= end and period_end >= start

    def week_start(value: date) -> date:
        return value.fromordinal(value.toordinal() - value.weekday())

    def make_marker(event: TimelineEvent) -> dict[str, Any]:
        return {
            "group": event.group,
            "group_label": event.label,
            "title": event.title,
            "secondary": event.secondary or "-",
            "date": event.occurred_on.strftime("%d/%m/%Y") if event.occurred_on else "-",
            "km": format_km(event.km) if event.km is not None else "",
        }

    def make_weekly_board(raw_events: list[TimelineEvent]) -> dict[str, Any]:
        dated = [event for event in raw_events if event.occurred_on is not None]
        if not dated:
            return {"weeks": [], "event_count": 0}
        period_ends = [event.end_on for event in dated if event.end_on is not None]
        min_date = min([event.occurred_on for event in dated if event.occurred_on] + period_ends)
        max_date = max([event.occurred_on for event in dated if event.occurred_on] + period_ends)
        start = week_start(min_date)
        end = week_start(max_date)
        period_items = sorted(
            [event for event in dated if event.group in {"contracts", "impros"}],
            key=lambda event: (event.occurred_on or date.min, side_rank(event.group), event.title),
        )
        markers = [event for event in dated if event.group not in {"contracts", "impros"}]
        weeks: list[dict[str, Any]] = []
        current = start
        previous_state_key: tuple[str, str] | None = None
        while current <= end:
            week_end = date.fromordinal(current.toordinal() + 6)
            active_impro = next((event for event in period_items if event.group == "impros" and period_overlaps(event, current, week_end)), None)
            active_contract = next((event for event in period_items if event.group == "contracts" and period_overlaps(event, current, week_end)), None)
            active = active_impro or active_contract
            if active:
                state = {
                    "group": active.group,
                    "group_label": active.label,
                    "title": active.title,
                    "period": _period_display(active.occurred_on, active.end_on),
                }
            else:
                state = {
                    "group": "free",
                    "group_label": "Sem utilização",
                    "title": "Sem utilização",
                    "period": f"{current.strftime('%d/%m/%Y')} a {week_end.strftime('%d/%m/%Y')}",
                }
            state_key = (state["group"], state["title"])
            state["is_start"] = state_key != previous_state_key
            previous_state_key = state_key
            week_markers = [
                make_marker(event)
                for event in markers
                if event.occurred_on and current <= event.occurred_on <= week_end
            ]
            week_markers.sort(key=lambda item: (side_rank(item["group"]), item["date"], item["title"]))
            weeks.append(
                {
                    "date_iso": current.isoformat(),
                    "label": current.strftime("%d/%m"),
                    "range": f"{current.strftime('%d/%m')} - {week_end.strftime('%d/%m')}",
                    "state": state,
                    "markers": week_markers,
                }
            )
            current = date.fromordinal(current.toordinal() + 7)
        return {"weeks": weeks, "event_count": len(markers)}

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
                end_on=row.get("period_end"),
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
    period_events = sorted(
        [
            event
            for event in events
            if event.group in {"contracts", "impros"} and event.occurred_on is not None
        ],
        key=lambda event: event.occurred_on or date.min,
        reverse=True,
    )
    last_km = None
    rows_by_date: dict[date | None, dict[str, Any]] = {}
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

    rendered: list[dict[str, Any]] = []
    sorted_dates = sorted(rows_by_date.keys(), key=lambda value: (value is not None, value or date.min), reverse=True)
    for occurred_on in sorted_dates:
        bucket = rows_by_date[occurred_on]
        if bucket["diagnostics_raw"]:
            bucket["right"].append(make_grouped_diagnostics(bucket["diagnostics_raw"]))
        if not bucket["center"]:
            active_period = next(
                (event for event in period_events if period_contains(event, occurred_on)),
                None,
            )
            bucket["center"].append(make_card(active_period) if active_period else make_free_card())
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

    if not rendered:
        rendered.insert(
            0,
            {
                "date": "-",
                "date_iso": "",
                "left": [],
                "center": [make_free_card()],
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
    board = make_weekly_board(events)
    return rendered, ticks, segments, board


def vehicle_document_module_context(
    db: Session,
    vehicle: Vehicle,
    *,
    materialize_sources: bool = True,
) -> dict[str, Any]:
    documents = _load_vehicle_documents(db, vehicle)
    if materialize_sources and _ensure_structured_sources_materialized(db, vehicle=vehicle, documents=documents):
        db.flush()
        documents = _load_vehicle_documents(db, vehicle)
    record_tags, document_tags = _tag_maps(db, vehicle.id)
    persisted_records = db.scalars(
        select(VehicleDocumentRecord)
        .where(VehicleDocumentRecord.vehicle_id == vehicle.id)
        .where(v2_clean_record_visible_condition())
        .order_by(VehicleDocumentRecord.document_date.desc().nullslast(), VehicleDocumentRecord.id.desc())
    ).all()
    pending_archive_records = [record for record in persisted_records if record.main_group in {"invoices", "diagnostics"}]
    pending_archive_records = [
        record
        for record in pending_archive_records
        if record.source_record_type == "archive_pending"
    ]
    structured_rows = _build_structured_rows(db, vehicle.id, record_tags)
    extraction_metadata = _document_extraction_metadata(db, [document.id for document in documents])
    archive_rows = _build_archive_rows(documents, document_tags, pending_archive_records, extraction_metadata)
    import_rows = _build_import_rows(documents)
    comparison_rows = _build_comparison_rows(structured_rows, archive_rows, record_tags, document_tags)
    timeline_events, timeline_ticks, timeline_segments, timeline_board = _build_timeline(structured_rows, archive_rows)
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
            event_title = "-"
            for side in ("left", "center", "right"):
                if event.get(side):
                    event_title = event[side][0].get("title") or event[side][0].get("group_label") or "-"
                    break
            alerts.append(
                {
                    "title": "KM regressivo",
                    "detail": f"{event_title} apresenta km inferior ao documento anterior.",
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
        if not is_structured_import_source(document)
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
        "import_rows": import_rows,
        "comparison_rows": comparison_rows,
        "timeline_events": timeline_events,
        "timeline_ticks": timeline_ticks,
        "timeline_segments": timeline_segments,
        "timeline_board": timeline_board,
        "alerts": alerts,
        "pendings": pendings,
        "audit_fields": audit_fields,
        "document_options": document_options,
        "record_tags": record_tags,
        "document_tags": document_tags,
        "archive_documents_count": len(archive_rows),
        "structured_documents_count": len(structured_rows),
        "structured_imports_count": len(import_rows),
    }


def _load_structured_import_sources(
    db: Session,
    vehicle: Vehicle | None = None,
    *,
    limit: int | None = None,
) -> list[Document]:
    query = select(Document).where(Document.source.in_(V2_CLEAN_DOCUMENT_SOURCES))
    query = query.where(v2_clean_document_visible_condition())
    query = query.where(structured_import_source_condition())
    if vehicle is not None:
        query = query.where(or_(Document.vehicle_id == vehicle.id, Document.vehicle_id.is_(None), Document.plate == vehicle.plate))
    query = query.order_by(Document.updated_at.desc(), Document.id.desc())
    if limit is not None:
        query = query.limit(limit)
    documents = db.scalars(query).all()
    return [document for document in documents if is_structured_import_source(document)]


def ensure_structured_import_sources_materialized(
    db: Session,
    *,
    vehicle: Vehicle | None = None,
    user_id: int | None = None,
) -> bool:
    changed = False
    for document in _load_structured_import_sources(db, vehicle):
        import_kind = structured_import_kind_for_document(document)
        if import_kind not in STRUCTURED_IMPORT_KIND_LABELS:
            continue
        if import_kind == "work_order_details":
            continue
        record_query = select(VehicleDocumentRecord.id).where(
            VehicleDocumentRecord.source_record_type.in_(STRUCTURED_RECORD_TYPES),
            VehicleDocumentRecord.main_group == import_kind,
            VehicleDocumentRecord.document_id == document.id,
            v2_clean_record_visible_condition(),
        )
        if vehicle is not None:
            record_query = record_query.where(VehicleDocumentRecord.vehicle_id == vehicle.id)
        linked_count = len(db.scalars(record_query).all())
        expected_count = _structured_import_expected_count(document)
        if _structured_import_is_already_materialized(expected_count=expected_count, linked_count=linked_count):
            continue
        if _materialize_structured_import_source(db, document=document, user_id=user_id):
            changed = True
    return changed


def _global_structured_record_conditions(
    *,
    main_group: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> list[Any]:
    conditions: list[Any] = [
        VehicleDocumentRecord.source_record_type.in_(STRUCTURED_RECORD_TYPES),
        VehicleDocumentRecord.main_group.in_([code for code, _ in DOCUMENT_HISTORY_STRUCTURED_GROUPS]),
        v2_clean_record_visible_condition(),
    ]
    if main_group:
        conditions.append(VehicleDocumentRecord.main_group == main_group)
    if status:
        if status == "por_validar":
            conditions.append(
                or_(
                    VehicleDocumentRecord.status == status,
                    VehicleDocumentRecord.comparison_state == status,
                    and_(
                        VehicleDocumentRecord.comparison_state.is_(None),
                        ~VehicleDocumentRecord.main_group.in_(list(RENTWAY_TIMELINE_GROUPS)),
                    ),
                )
            )
        elif status == "imported_rentway":
            conditions.append(
                or_(
                    VehicleDocumentRecord.comparison_state == status,
                    and_(
                        VehicleDocumentRecord.comparison_state.is_(None),
                        VehicleDocumentRecord.main_group.in_(list(RENTWAY_TIMELINE_GROUPS)),
                    ),
                )
            )
        else:
            conditions.append(
                or_(
                    VehicleDocumentRecord.status == status,
                    VehicleDocumentRecord.comparison_state == status,
                )
            )
    if search:
        token = f"%{search}%"
        conditions.append(
            or_(
                VehicleDocumentRecord.plate.ilike(token),
                VehicleDocumentRecord.vin.ilike(token),
                VehicleDocumentRecord.title.ilike(token),
                VehicleDocumentRecord.supplier_name.ilike(token),
                VehicleDocumentRecord.external_reference.ilike(token),
                VehicleDocumentRecord.process_reference.ilike(token),
                VehicleDocumentRecord.raw_description.ilike(token),
            )
        )
    return conditions


def count_global_structured_rows(
    db: Session,
    *,
    main_group: str | None = None,
    status: str | None = None,
    search: str | None = None,
) -> int:
    query = select(func.count()).select_from(VehicleDocumentRecord).where(
        *_global_structured_record_conditions(main_group=main_group, status=status, search=search)
    )
    return int(db.scalar(query) or 0)


def count_global_structured_rows_by_group(db: Session) -> dict[str, int]:
    counts = {code: 0 for code, _ in DOCUMENT_HISTORY_STRUCTURED_GROUPS}
    result = db.execute(
        select(VehicleDocumentRecord.main_group, func.count())
        .where(*_global_structured_record_conditions())
        .group_by(VehicleDocumentRecord.main_group)
    ).all()
    for code, count in result:
        counts[str(code)] = int(count or 0)
    return counts


def _build_global_structured_rows(
    db: Session,
    *,
    main_group: str | None = None,
    status: str | None = None,
    search: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    query = (
        select(VehicleDocumentRecord)
        .where(*_global_structured_record_conditions(main_group=main_group, status=status, search=search))
        .order_by(VehicleDocumentRecord.document_date.desc().nullslast(), VehicleDocumentRecord.id.desc())
    )
    if limit is not None:
        query = query.limit(limit)
    persisted_rows = db.scalars(query).all()
    vehicles = {
        vehicle.id: vehicle
        for vehicle in db.scalars(
            select(Vehicle).where(Vehicle.id.in_({row.vehicle_id for row in persisted_rows}))
        ).all()
    } if persisted_rows else {}
    tags_by_record: dict[int, list[VehicleDocumentRecordTag]] = {}
    if persisted_rows:
        for tag in db.scalars(
            select(VehicleDocumentRecordTag)
            .where(VehicleDocumentRecordTag.record_id.in_([row.id for row in persisted_rows]))
            .order_by(VehicleDocumentRecordTag.created_at.asc(), VehicleDocumentRecordTag.id.asc())
        ).all():
            if tag.record_id:
                tags_by_record.setdefault(tag.record_id, []).append(tag)

    rows: list[dict[str, Any]] = []
    for row in persisted_rows:
        vehicle = vehicles.get(row.vehicle_id)
        period_start, period_end = _timeline_period_dates(row)
        display_date = period_start or row.document_date
        comparison_state = _structured_comparison_state(row)
        rows.append(
            {
                "kind": "record",
                "id": row.id,
                "vehicle_id": row.vehicle_id,
                "vehicle_plate": vehicle.plate if vehicle else row.plate or "-",
                "vehicle_label": (
                    f"{vehicle.plate} · {vehicle.brand or ''} {vehicle.model or ''}".strip()
                    if vehicle
                    else row.plate or "-"
                ),
                "vehicle_href": f"/v2-clean/fleet/{row.vehicle_id}/documents",
                "main_group": row.main_group,
                "group_label": DOCUMENT_HISTORY_STRUCTURED_GROUP_LABELS.get(row.main_group, row.main_group),
                "date": display_date,
                "date_display": _display_date(display_date),
                "title": row.title or row.external_reference or row.main_group,
                "supplier_name": row.supplier_name or "-",
                "km": row.km,
                "status": row.status,
                "comparison_state": comparison_state,
                "comparison_label": _structured_comparison_label(row),
                "process_reference": row.process_reference or "-",
                "description": row.raw_description or "",
                "external_reference": row.external_reference or "-",
                "period_start": period_start,
                "period_end": period_end,
                "period_display": _period_display(period_start, period_end),
                "tags": [_format_tag(tag) for tag in tags_by_record.get(row.id, [])],
            }
        )
    return rows


def document_center_module_context(
    db: Session,
    *,
    user_id: int | None = None,
    materialize_sources: bool = True,
    include_structured_preview: bool = True,
) -> dict[str, Any]:
    if materialize_sources and ensure_structured_import_sources_materialized(db, user_id=user_id):
        db.flush()

    import_sources = _load_structured_import_sources(db, limit=20)
    structured_counts = count_global_structured_rows_by_group(db)
    pending_structured_count = count_global_structured_rows(db, status="por_validar")
    structured_rows_preview = _build_global_structured_rows(db, limit=50) if include_structured_preview else []
    structured_sections_preview = []
    for code, label in DOCUMENT_HISTORY_STRUCTURED_GROUPS:
        structured_sections_preview.append(
            {
                "code": code,
                "label": label,
                "rows": [row for row in structured_rows_preview if row["main_group"] == code],
            }
        )
    archive_documents_count = db.scalar(
        select(func.count())
        .select_from(Document)
        .where(Document.source.in_(V2_CLEAN_DOCUMENT_SOURCES))
        .where(v2_clean_document_visible_condition())
        .where(or_(Document.entry_channel.is_(None), Document.entry_channel != "structured_import"))
    )
    vehicle_count = db.scalar(select(func.count()).select_from(Vehicle))
    return {
        "structured_groups": DOCUMENT_HISTORY_STRUCTURED_GROUPS,
        "structured_counts": structured_counts,
        "structured_rows": structured_rows_preview,
        "structured_sections": structured_sections_preview,
        "import_rows": _build_import_rows(import_sources),
        "vehicle_count": int(vehicle_count or 0),
        "archive_documents_count": int(archive_documents_count or 0),
        "pending_structured_count": pending_structured_count,
    }


def save_uploaded_spreadsheet(upload) -> Path:
    suffix = Path(upload.filename or "upload.xlsx").suffix or ".xlsx"
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(upload.file.read())
        return Path(tmp.name)
