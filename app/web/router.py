import csv
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
import hashlib
import io
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from tempfile import NamedTemporaryFile
from time import monotonic
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.change_notice import (
    CHANGE_NOTICE_SECTIONS,
    CHANGE_NOTICE_SESSION_KEY,
    CHANGE_NOTICE_TITLE,
    CHANGE_NOTICE_VERSION,
)
from app.core.database import SessionLocal
from app.core.security import verify_password
from app.models.admin import Permission, Role, RolePermission, User, UserRole
from app.models.documents import (
    Document,
    DocumentEvent,
    DocumentLink,
    VehicleDocumentAuditField,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.models.integrations import EmailIntake, EmailIntakeAttachment
from app.models.imports import ImportBatch, ImportError, ImportFile, ImportRawRow
from app.models.incidents import Incident, IncidentEvent, IncidentEvidence
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
from app.models.organization import OrganizationalUnit, Team, UserOrganizationalUnit
from app.models.pilot import PilotFeedback
from app.models.tasks import (
    QuickRecord,
    Task,
    TaskComment,
    TaskGuidedFlowRun,
    TaskGuidedFlowStepRun,
    TaskHistory,
)
from app.models.vehicles import Vehicle, VehicleExternalSnapshot, VehicleManualField, VehicleOperationalStatusEvent
from app.models.vehicle_history_audit import (
    VehicleHistoryAudit,
    VehicleHistoryAuditDocument,
    VehicleHistoryAuditIssue,
    VehicleHistoryAuditReading,
    VehicleHistoryAuditRule,
    VehicleHistoryAuditService,
    VehicleHistoryAuditTruth,
)
from app.models.workshop import (
    WorkshopProcess,
    WorkshopProcessEvidence,
    WorkshopProcessNote,
    WorkshopProcessService,
    WorkshopTechnicalReading,
)
from app.models.workshop_phased import (
    WorkshopPhasedProcess,
    WorkshopPhasedProcessAlert,
    WorkshopPhasedProcessPhase,
    WorkshopPhasedProcessService,
    WorkshopPhasedTechnicalReport,
)
from app.services.rentway_fleet_importer import import_rentway_fleet_xlsx
from app.services.management_center import (
    ACTION_STATUS_LABELS,
    AR_IMPORT_TYPE,
    CRAR_PER_VEHICLE_IMPORT_TYPE,
    PROCESS_PHASE_LABELS,
    PROCESS_STATUS_LABELS,
    REFSTRO_IMPORT_TYPE,
    add_history,
    associate_to_process,
    create_claim_process,
    end_association,
    ensure_management_defaults,
    preview_claims_file,
    refresh_claim_state,
)
from app.services.task_bulk_importer import (
    TASK_BULK_FIELDS,
    TASK_BULK_IMPORT_TYPE,
    create_tasks_from_bulk_import,
    preview_task_bulk_import,
    store_task_bulk_upload,
)
from app.services.trade_debt_importer import (
    TRADE_DEBT_IMPORT_TYPE,
    apply_trade_debt_import,
    preview_trade_debt_import,
    store_trade_debt_upload,
)
from app.services.workshop_history_importer import (
    TECHNICAL_HISTORY_IMPORT_COLUMNS,
    import_workshop_technical_history_file,
    technical_history_template_csv,
)
from app.services.vehicle_document_history import (
    DOCUMENT_HISTORY_AUDIT_FIELDS,
    DOCUMENT_HISTORY_AUDIT_FIELD_LABELS,
    DOCUMENT_HISTORY_COMPARISON_LABELS,
    DOCUMENT_HISTORY_MAIN_GROUPS,
    DOCUMENT_HISTORY_MAIN_GROUP_LABELS,
    DOCUMENT_HISTORY_QUICK_CLASSIFICATION_LABELS,
    DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS,
    DOCUMENT_HISTORY_STRUCTURED_GROUPS,
    add_quick_classification,
    attach_document_to_record,
    create_archive_placeholder,
    import_contracts_xlsx,
    import_impros_xlsx,
    import_work_orders_xlsx,
    save_uploaded_spreadsheet,
    sync_real_start_manual_field,
    upsert_audit_field,
    vehicle_document_module_context,
)
from app.services.workshop_report_extractor import (
    classify_workshop_report_from_bytes,
    extract_workshop_report_values_from_bytes,
)
from app.services.workshop_templates import STELLANTIS_REPORTS
from app.services.audit import record_audit
from app.services.authorization import get_user_authorized_unit_codes, get_user_permission_codes
from app.services.users import create_user
from app.services.vehicles import normalize_identifier

templates = Jinja2Templates(directory="app/templates")
web_router = APIRouter(include_in_schema=False)
APP_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def rentway_unit_sort_key(vehicle: Vehicle) -> tuple[int, int, str]:
    unit = (vehicle.rentway_unit_nr or "").strip()
    match = re.search(r"\d+", unit)
    if match:
        return (1, int(match.group(0)), unit)
    return (0, 0, unit)


def snapshot_value(data: dict | None, candidates: list[str]) -> str | None:
    if not data or not isinstance(data, dict):
        return None
    normalized_candidates = {re.sub(r"[^a-z0-9]", "", candidate.lower()) for candidate in candidates}
    for key, value in data.items():
        normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if normalized_key in normalized_candidates and value not in (None, ""):
            if isinstance(value, (date, datetime)):
                return value.strftime("%Y-%m-%d")
            text_value = str(value).strip()
            iso_date_match = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[T\s].*)?$", text_value)
            if iso_date_match:
                return iso_date_match.group(1)
            return text_value
    return None


def snapshot_data(snapshot: VehicleExternalSnapshot | None) -> dict:
    data = snapshot.data_json if snapshot else None
    return data if isinstance(data, dict) else {}


def rentway_vehicle_context(snapshot: VehicleExternalSnapshot | None) -> dict[str, str | None]:
    data = snapshot_data(snapshot)
    return {
        "groupid": snapshot_value(data, ["groupid", "group_id", "categoria_grupo", "grupo"]),
        "category": snapshot_value(data, ["category", "categoria", "tipo_categoria"]),
        "seats": snapshot_value(data, ["seats", "lugares", "passageiros"]),
        "colour": snapshot_value(data, ["colour", "color", "cor"]),
        "fuel": snapshot_value(data, ["fuel", "combustivel"]),
        "plate_date": snapshot_value(data, ["plate_date", "platedate", "data_matricula", "registration_date"]),
        "purchase_date": snapshot_value(data, ["purchase_date", "purchase_dat", "purchasedate", "data_compra"]),
        "inspection_date": snapshot_value(data, ["inspection_date", "inspectiondate", "data_ipo"]),
        "last_service_done": snapshot_value(
            data,
            ["last_service_done", "lastservicedone", "last_service_date", "last_service", "ultimo_servico"],
        ),
        "next_service_date": snapshot_value(
            data,
            [
                "next_service_date",
                "nextservicedate",
                "next_maintenance_date",
                "proxima_manutencao_data",
                "proxima_revisao_data",
            ],
        ),
        "next_service": snapshot_value(data, ["next_service", "nextservice", "next_service_date", "proximo_servico"]),
        "last_service": snapshot_value(data, ["last_service", "lastservice", "ultimo_servico_km"]),
        "last_service_km": snapshot_value(data, ["last_service_km", "lastservicekm"]),
        "next_service_km": snapshot_value(data, ["next_service_km", "nextservicekm"]),
    }


def rentway_commercial_context(snapshot: VehicleExternalSnapshot | None) -> dict[str, str | None]:
    data = snapshot_data(snapshot)
    return {
        "current_status": snapshot_value(data, ["CurrentStatus", "current_status", "current_status_rentway"]),
        "document_nr": snapshot_value(data, ["DocumentNr", "document_nr", "document_number", "contractnr"]),
        "client": snapshot_value(data, ["Client", "client", "customer", "customer_name"]),
        "driver": snapshot_value(data, ["Driver", "driver", "driver_name"]),
        "rental_station": snapshot_value(data, ["rental_station", "rentalstation", "station", "location"]),
        "return_date": snapshot_value(data, ["return_date", "returndate"]),
        "value_with_tax": snapshot_value(data, ["value_with_tax", "valuewithtax", "valor_com_iva", "valor_aquisicao"]),
        "purchase_supplier": snapshot_value(
            data,
            [
                "supplier",
                "supplier_name",
                "fornecedor",
                "fornecedor_compra",
                "purchase_supplier",
                "purchasesupplier",
                "purchase_vendor",
                "purchasevendor",
                "seller",
                "vendor",
                "dealer",
                "entidade_vendedora",
                "vendedor",
            ],
        ),
        "purchase_date": snapshot_value(data, ["purchase_date", "purchase_dat", "purchasedate", "data_compra"]),
        "km": snapshot_value(data, ["km", "kms", "odometer", "odometer_km", "current_km", "quilometros"]),
        "category": snapshot_value(data, ["category", "categoria", "grupo", "vehicle_category", "fleet"]),
        "finance_entity": snapshot_value(
            data,
            [
                "financial_supplier",
                "financeira",
                "entidade_financeira",
                "financial_entity",
                "finance_entity",
                "entidade_divida",
            ],
        ),
    }


CARFAST_MANAGEMENT_FIELD_CODES = {
    "real_start_date",
    "rule_category",
    "maintenance_interval_km",
    "maintenance_interval_months",
    "maintenance_last_valid_km",
    "maintenance_last_valid_date",
    "sale_blocked",
    "sale_block_reason",
    "sale_block_reason_other",
    "finance_entity",
    "debt_value",
    "trade_list_state",
    "trade_pending_items",
    "trade_decision",
    "trade_decision_reason",
    "trade_responsible",
    "trade_selected_for_sale",
    "trade_sale_price",
}

TRADE_LIST_STATES = [
    ("candidata", "Candidata"),
    ("em_analise", "Em análise"),
    ("aprovada", "Aprovada"),
    ("excluida", "Excluída"),
    ("adiada", "Adiada"),
    ("pendente_informacao", "Pendente de informação"),
]
TRADE_LIST_STATE_LABELS = dict(TRADE_LIST_STATES)

TRADE_DECISIONS = [
    ("", "Sem decisão"),
    ("incluir", "Incluir"),
    ("excluir", "Excluir"),
    ("adiar", "Adiar"),
    ("pedir_info", "Pedir informação"),
]
TRADE_DECISION_LABELS = dict(TRADE_DECISIONS)

SALE_BLOCK_REASONS = [
    ("", "Sem bloqueio"),
    ("documentacao", "Documentação"),
    ("financeiro", "Financeiro"),
    ("oficina", "Oficina"),
    ("operacional", "Operacional"),
    ("outro", "Outro"),
]
SALE_BLOCK_REASON_LABELS = dict(SALE_BLOCK_REASONS)


def finance_entity_options(db, current: str | None = None) -> list[str]:
    values = {
        str(field.value_json).strip()
        for field in db.scalars(
            select(VehicleManualField).where(
                VehicleManualField.field_code == "finance_entity",
                VehicleManualField.value_json.is_not(None),
            )
        ).all()
        if str(field.value_json or "").strip()
    }
    if current and current.strip():
        values.add(current.strip())
    return sorted(values, key=str.casefold)


def vehicle_manual_values(db, vehicle_id: int) -> dict[str, object]:
    fields = db.scalars(
        select(VehicleManualField).where(
            VehicleManualField.vehicle_id == vehicle_id,
            VehicleManualField.field_code.in_(CARFAST_MANAGEMENT_FIELD_CODES),
        )
    ).all()
    return {field.field_code: field.value_json for field in fields}


def upsert_vehicle_manual_field(db, vehicle_id: int, field_code: str, value, user_id: int | None) -> None:
    field = db.scalar(
        select(VehicleManualField).where(
            VehicleManualField.vehicle_id == vehicle_id,
            VehicleManualField.field_code == field_code,
        )
    )
    if field:
        field.value_json = value
        field.updated_by_id = user_id
        return
    db.add(
        VehicleManualField(
            vehicle_id=vehicle_id,
            field_code=field_code,
            value_json=value,
            updated_by_id=user_id,
        )
    )


def parse_decimal_text(value: str | int | float | None) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "").replace("\u00a0", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-]", "", text)
    try:
        return float(text)
    except ValueError:
        return None


def parse_iso_or_dmy_date(value: str | None) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def amortization_month(purchase_date: date | None, reference_date: date | None = None) -> int | None:
    if not purchase_date:
        return None
    reference = reference_date or date.today()
    months = (reference.year - purchase_date.year) * 12 + (reference.month - purchase_date.month) + 1
    return max(1, min(96, months))


def current_cost_from_snapshot(snapshot: VehicleExternalSnapshot | None) -> dict[str, float | int | str | None]:
    context = rentway_commercial_context(snapshot)
    initial_cost = parse_decimal_text(context.get("value_with_tax"))
    purchase = parse_iso_or_dmy_date(context.get("purchase_date"))
    month = amortization_month(purchase)
    if initial_cost is None or month is None:
        return {
            "initial_cost": initial_cost,
            "purchase_date": context.get("purchase_date"),
            "amortization_month": month,
            "current_cost": None,
        }
    current_cost = max(0, initial_cost - ((initial_cost / 96) * month))
    return {
        "initial_cost": initial_cost,
        "purchase_date": context.get("purchase_date"),
        "amortization_month": month,
        "current_cost": current_cost,
    }


VEHICLE_RULE_CATEGORIES = [
    ("", "Por confirmar"),
    ("passenger", "Passageiros"),
    ("commercial", "Comercial"),
]
VEHICLE_RULE_CATEGORY_LABELS = dict(VEHICLE_RULE_CATEGORIES)


def add_years(base_date: date, years: int) -> date:
    try:
        return base_date.replace(year=base_date.year + years)
    except ValueError:
        return base_date.replace(year=base_date.year + years, day=28)


def add_months(base_date: date, months: int) -> date:
    month_index = (base_date.month - 1) + months
    year = base_date.year + month_index // 12
    month = (month_index % 12) + 1
    days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(year, month, min(base_date.day, days_in_month[month - 1]))


def inferred_rule_category(snapshot: VehicleExternalSnapshot | None, manual: dict[str, object]) -> str:
    manual_category = str(manual.get("rule_category") or "").strip()
    if manual_category and manual_category in VEHICLE_RULE_CATEGORY_LABELS:
        return manual_category
    context = rentway_vehicle_context(snapshot)
    category = str(context.get("category") or "").strip().upper()
    if "COMERC" in category:
        return "commercial"
    if "LIGEIRO" in category:
        return "passenger"
    return ""


def calculated_next_ipo(registration_date: date | None, rule_category: str, reference: date | None = None) -> date | None:
    if not registration_date or rule_category not in {"passenger", "commercial"}:
        return None
    today = reference or date.today()
    fixed_years = [4, 6, 8] if rule_category == "passenger" else [2]
    for years in fixed_years:
        due = add_years(registration_date, years)
        if due >= today:
            return due
    years = fixed_years[-1] + 1
    while years < 80:
        due = add_years(registration_date, years)
        if due >= today:
            return due
        years += 1
    return None


def ipo_dates_compatible(calculated_ipo: date, rentway_ipo: date) -> bool:
    """Accept Rentway dates up to seven days before the calculated due date."""
    days_early = (calculated_ipo - rentway_ipo).days
    return 0 <= days_early <= 7


def vehicle_rule_context(snapshot: VehicleExternalSnapshot | None, manual: dict[str, object]) -> dict[str, object]:
    context = rentway_vehicle_context(snapshot)
    rule_category = inferred_rule_category(snapshot, manual)
    registration_date = parse_iso_or_dmy_date(context.get("plate_date"))
    rentway_ipo = parse_iso_or_dmy_date(context.get("inspection_date"))
    calculated_ipo = calculated_next_ipo(registration_date, rule_category)
    ipo_status = "Por confirmar"
    if calculated_ipo and rentway_ipo:
        ipo_status = "OK" if ipo_dates_compatible(calculated_ipo, rentway_ipo) else "Divergente"
    elif calculated_ipo:
        ipo_status = "Calculada"

    last_km = parse_decimal_text(manual.get("maintenance_last_valid_km"))
    interval_km = parse_decimal_text(manual.get("maintenance_interval_km"))
    last_date = parse_iso_or_dmy_date(str(manual.get("maintenance_last_valid_date") or ""))
    interval_months = parse_decimal_text(manual.get("maintenance_interval_months"))
    calculated_service_km = int(last_km + interval_km) if last_km is not None and interval_km is not None else None
    calculated_service_date = add_months(last_date, int(interval_months)) if last_date and interval_months else None
    rentway_next_service_km = parse_decimal_text(context.get("next_service"))
    maintenance_status = "Por configurar"
    if calculated_service_km is not None and rentway_next_service_km is not None:
        maintenance_status = "OK" if int(rentway_next_service_km) == calculated_service_km else "Divergente"
    elif calculated_service_km is not None or calculated_service_date:
        maintenance_status = "Calculada"

    return {
        "source_category": context.get("category"),
        "groupid": context.get("groupid"),
        "seats": context.get("seats"),
        "fuel": context.get("fuel"),
        "rule_category": rule_category,
        "rule_category_label": VEHICLE_RULE_CATEGORY_LABELS.get(rule_category, "Por confirmar"),
        "registration_date": registration_date,
        "rentway_ipo": rentway_ipo,
        "calculated_ipo": calculated_ipo,
        "ipo_status": ipo_status,
        "maintenance_last_valid_km": manual.get("maintenance_last_valid_km") or "",
        "maintenance_last_valid_date": manual.get("maintenance_last_valid_date") or "",
        "maintenance_interval_km": manual.get("maintenance_interval_km") or "",
        "maintenance_interval_months": manual.get("maintenance_interval_months") or "",
        "rentway_last_service_km": context.get("last_service"),
        "rentway_next_service_km": context.get("next_service"),
        "rentway_next_service_date": context.get("next_service_date") or context.get("last_service_done"),
        "calculated_service_km": calculated_service_km,
        "calculated_service_date": calculated_service_date,
        "maintenance_status": maintenance_status,
    }


def format_eur(value: str | int | float | None) -> str:
    number = parse_decimal_text(value)
    if number is None:
        return "-"
    text = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text} €"


def can_manage_carfast_fleet(request: Request) -> bool:
    return has_any_web_permission(request, "fleet.commerce.manage", "vehicles.write", "admin.manage")


def can_view_fleet(request: Request) -> bool:
    return has_any_web_permission(request, "vehicles.read", "vehicles.write", "admin.manage")


def ensure_history_audit_process_type(db) -> ManagementProcessType:
    process_type = db.scalar(
        select(ManagementProcessType).where(ManagementProcessType.code == "vehicle_history_audit")
    )
    if process_type:
        process_type.name = "Auditoria Técnica da Viatura"
        process_type.description = "Memória técnica/histórica da viatura para decisões futuras."
        return process_type
    process_type = ManagementProcessType(
        code="vehicle_history_audit",
        name="Auditoria Técnica da Viatura",
        description="Memória técnica/histórica da viatura para decisões futuras.",
        active=True,
    )
    db.add(process_type)
    db.flush()
    return process_type


def next_history_audit_reference(db) -> str:
    reference_year = date.today().year
    sequence = (
        db.scalar(
            select(func.count(ManagementProcess.id)).where(
                ManagementProcess.internal_reference.like(f"AUD-{reference_year}-%")
            )
        )
        or 0
    ) + 1
    while True:
        reference = f"AUD-{reference_year}-{sequence:06d}"
        if not db.scalar(select(ManagementProcess).where(ManagementProcess.internal_reference == reference)):
            return reference
        sequence += 1


def compact_reading_label(reading: WorkshopTechnicalReading) -> str:
    if reading.reading_date:
        label = reading.reading_date.strftime("%Y-%m-%d")
    elif reading.created_at:
        label = reading.created_at.strftime("%Y-%m-%d")
    else:
        label = f"Leitura #{reading.id}"
    data = reading.data_json or {}
    document_time = data.get("document_time")
    if document_time:
        label = f"{label} {document_time}"
    return label


def technical_history_tabs(readings: list[WorkshopTechnicalReading]) -> list[dict[str, str | int]]:
    counts = {code: 0 for code, _ in WORKSHOP_READING_TYPES}
    legacy_codes = [code for code, _ in WORKSHOP_LEGACY_READING_TYPES]
    for code in legacy_codes:
        counts.setdefault(code, 0)
    for reading in readings:
        counts[reading.reading_type] = counts.get(reading.reading_type, 0) + 1

    tabs = []
    ordered_codes = [code for code, _ in WORKSHOP_READING_TYPES] + legacy_codes
    for code in ordered_codes:
        total = counts.get(code, 0)
        if total:
            tabs.append({"code": code, "label": WORKSHOP_READING_TYPE_LABELS.get(code, code), "count": total})
    return tabs


TECHNICAL_HISTORY_METADATA_FIELDS = {
    "record_origin",
    "import_batch_id",
    "import_status",
    "import_key",
    "duplicate_candidate",
    "chronological_order",
    "copied_to_archive",
    "archive_file",
    "source_file",
    "file_sha1",
    "source_report_type",
    "module_name",
    "import_note",
    "work_order_reference",
    "document_time",
    "document_datetime",
    "source_created_by",
    "source_created_at",
}


TECHNICAL_HISTORY_BASE_FIELDS = [
    "machine_source",
    "odometer_km",
    "battery_voltage",
]


def technical_history_matrix(
    readings: list[WorkshopTechnicalReading],
    reading_type: str,
) -> dict[str, list[dict] | list[WorkshopTechnicalReading]]:
    selected = [item for item in readings if item.reading_type == reading_type]
    selected.sort(key=lambda item: (item.reading_date or date.min, item.created_at.isoformat() if item.created_at else "", item.id))
    fields = [
        field
        for field in TECHNICAL_HISTORY_BASE_FIELDS
        + TECHNICAL_HISTORY_FIELD_GROUPS.get(reading_type, TECHNICAL_HISTORY_FIELD_GROUPS["other"])
        if field not in TECHNICAL_HISTORY_METADATA_FIELDS
    ]

    rows = []
    for field in fields:
        values = []
        previous_value = None
        has_value = False
        changed = False
        for reading in selected:
            value = (reading.data_json or {}).get(field)
            if value in (None, ""):
                value = "-"
            else:
                if field == "flow_phase":
                    value = WORKSHOP_READING_PHASE_DISPLAY_LABELS.get(value, value)
                has_value = True
            if previous_value not in (None, value, "-") and value != "-":
                changed = True
            if value != "-":
                previous_value = value
            values.append({"reading_id": reading.id, "value": value})
        if has_value:
            rows.append(
                {
                    "key": field,
                    "label": TECHNICAL_READING_COMPARE_LABELS.get(field, field.replace("_", " ").capitalize()),
                    "values": values,
                    "changed": changed,
                }
            )
    return {"readings": selected, "rows": rows}


WORKSHOP_OPENING_TYPES = [
    ("walk_in", "Entrada imediata"),
    ("appointment", "Marcação"),
]

WORKSHOP_STATUSES = [
    ("opening", "Abertura"),
    ("reception", "Receção"),
    ("history_check", "Verificar histórico"),
    ("stellantis_service_box", "Revisão Stellantis / Service Box"),
    ("bsi_initial", "Registo de leitura técnica / BSI inicial"),
    ("diagnosis", "Diagnóstico"),
    ("technical_info", "Registo de informação técnica"),
    ("systematic_checks", "Verificações sistemáticas"),
    ("service_quote", "Serviços a executar / orçamento"),
    ("decision", "Decisão"),
    ("waiting_analysis", "Aguardar análise"),
    ("waiting_parts", "Aguardar material"),
    ("in_progress", "Em execução"),
    ("bsi_final", "Registo de leitura técnica / BSI final"),
    ("technical_close", "Fecho técnico"),
    ("administrative_close", "Fecho administrativo"),
    ("validation", "Validação"),
    ("closed", "Fechado"),
]

WORKSHOP_DECISIONS = [
    ("repair", "Reparar"),
    ("wait_analysis", "Aguardar análise"),
    ("order_parts", "Encomendar material"),
    ("send_to_brand", "Enviar para marca"),
    ("request_quote", "Pedir orçamento"),
    ("no_action_needed", "Sem intervenção necessária"),
]

WORKSHOP_SERVICE_FAMILIES = [
    ("revision", "Revisão"),
    ("tyres", "Pneus"),
    ("brakes", "Travões"),
    ("dashboard_light", "Luz / avaria no painel"),
    ("abnormal_noise", "Ruído anormal"),
    ("accident_damage", "Acidente / dano"),
    ("battery", "Bateria"),
    ("periodic_check", "Verificação periódica"),
    ("other", "Outro"),
]

WORKSHOP_SERVICE_DETAILS = [
    ("brake_pads", "Calços", "brakes"),
    ("brake_discs", "Discos", "brakes"),
    ("brake_pads_discs", "Calços + discos", "brakes"),
    ("brake_diagnosis", "Diagnóstico travões", "brakes"),
    ("tyre_replacement", "Substituição", "tyres"),
    ("tyre_puncture", "Furo", "tyres"),
    ("tyre_wear", "Desgaste", "tyres"),
    ("tyre_pressure", "Pressão", "tyres"),
    ("tyre_alignment", "Alinhamento", "tyres"),
    ("other", "Outro", "any"),
]

WORKSHOP_SERVICE_AXES = [
    ("not_defined", "Não definido"),
    ("front", "Frente"),
    ("rear", "Trás"),
    ("front_rear", "Frente + trás"),
]

WORKSHOP_SERVICE_STATUSES = [
    ("to_assess", "Por avaliar"),
    ("diagnosis", "Em diagnóstico"),
    ("execution", "Em execução"),
    ("completed", "Concluído"),
    ("no_action_needed", "Sem intervenção"),
]

WORKSHOP_EVIDENCE_TYPES = [
    ("photo", "Foto"),
    ("video", "Vídeo"),
    ("document", "Documento"),
    ("note", "Nota técnica"),
]

WORKSHOP_EVIDENCE_CATEGORIES = [
    ("noise", "Ruído anormal"),
    ("visible_damage", "Dano visível"),
    ("warning_light", "Luz de avaria"),
    ("wear", "Desgaste irregular"),
    ("leak", "Fuga"),
    ("broken_part", "Peça partida"),
    ("intermittent_failure", "Falha intermitente"),
    ("mileage_inconsistency", "KM incoerentes"),
    ("safety", "Segurança"),
    ("other", "Outra anomalia"),
]

WORKSHOP_EVIDENCE_STATUSES = [
    ("registered", "Registada"),
    ("reviewed", "Analisada"),
    ("resolved", "Resolvida"),
    ("no_action_needed", "Sem intervenção necessária"),
]

WORKSHOP_READING_TYPES = [
    ("maintenance_info", "Informações manutenção"),
    ("maintenance_program", "Programação manutenção"),
    ("lubrication_info", "Informações lubrificação motor"),
    ("fault_reading", "Leitura de defeitos"),
    ("software_identification", "Identificação / telecarregamento"),
    ("other", "Outra leitura"),
]

WORKSHOP_LEGACY_READING_TYPES = [
    ("technical", "Leitura técnica"),
    ("bsi", "Leitura BSI"),
    ("diagnostic", "Diagnóstico eletrónico"),
    ("maintenance", "Manutenção"),
]

WORKSHOP_OPENING_LABELS = dict(WORKSHOP_OPENING_TYPES)
WORKSHOP_STATUS_LABELS = dict(WORKSHOP_STATUSES)
WORKSHOP_DECISION_LABELS = dict(WORKSHOP_DECISIONS)
WORKSHOP_SERVICE_FAMILY_LABELS = dict(WORKSHOP_SERVICE_FAMILIES)
WORKSHOP_SERVICE_DETAIL_LABELS = {code: label for code, label, _ in WORKSHOP_SERVICE_DETAILS}
WORKSHOP_SERVICE_AXIS_LABELS = dict(WORKSHOP_SERVICE_AXES)
WORKSHOP_SERVICE_STATUS_LABELS = dict(WORKSHOP_SERVICE_STATUSES)
WORKSHOP_EVIDENCE_TYPE_LABELS = dict(WORKSHOP_EVIDENCE_TYPES)
WORKSHOP_EVIDENCE_CATEGORY_LABELS = dict(WORKSHOP_EVIDENCE_CATEGORIES)
WORKSHOP_EVIDENCE_STATUS_LABELS = dict(WORKSHOP_EVIDENCE_STATUSES)
WORKSHOP_READING_TYPE_LABELS = dict([*WORKSHOP_LEGACY_READING_TYPES, *WORKSHOP_READING_TYPES])
WORKSHOP_READING_PHASES = {
    "initial": {
        "label": "Leitura inicial",
        "flow_status": "bsi_initial",
        "allowed_types": {
            "maintenance_info",
            "maintenance_program",
            "lubrication_info",
            "fault_reading",
            "software_identification",
            "other",
        },
    },
    "final": {
        "label": "Leitura final",
        "flow_status": "bsi_final",
        "allowed_types": {
            "maintenance_info",
            "lubrication_info",
        },
    },
}
WORKSHOP_READING_PHASE_DISPLAY_LABELS = {
    "initial": "Leitura inicial",
    "final": "Leitura final",
    "bsi_initial": "Leitura inicial",
    "bsi_final": "Leitura final",
}
WORKSHOP_READING_STATUSES = [
    ("active", "Ativa"),
    ("voided", "Anulada"),
    ("replaced", "Substituída"),
]
WORKSHOP_READING_STATUS_LABELS = dict(WORKSHOP_READING_STATUSES)
WORKSHOP_SERVICE_DETAIL_FAMILIES = {
    family for _, _, family in WORKSHOP_SERVICE_DETAILS if family != "any"
}
WORKSHOP_SERVICE_AXIS_FAMILIES = {"brakes", "tyres"}

TECHNICAL_HISTORY_FIELD_GROUPS = {
    "maintenance_info": [
        "maintenance_last_reset_km",
        "maintenance_km_until_next",
        "maintenance_days_until_next",
        "maintenance_days_since_last_reset",
        "maintenance_count",
        "maintenance_temporal_limit_exceeded",
        "maintenance_distance_limit_exceeded",
        "maintenance_next_due_date",
        "maintenance_last_reset_date_estimated",
    ],
    "maintenance_program": [
        "maintenance_threshold_km",
        "maintenance_duration_months",
        "maintenance_days_since_first_circulation",
        "maintenance_first_start_km",
        "maintenance_first_duration_months",
        "maintenance_management_mode",
        "maintenance_first_circulation_date_estimated",
        "maintenance_days_since_last_estimated",
        "maintenance_last_date_estimated",
    ],
    "lubrication_info": [
        "oil_dilution_rate",
        "oil_carbon_rate",
        "oil_anti_dilution_status",
        "engine_calculated_interval_km",
    ],
    "fault_reading": [
        "faults_present",
        "fault_event_count",
        "fault_codes",
        "critical_fault",
        "fault_main_status",
        "fault_characterization",
        "fault_odometer_km",
        "recommended_action",
    ],
    "software_identification": [
        "software_reference",
        "calibration_edition",
        "software_edition",
        "download_date",
        "download_count",
        "ecu_supplier",
        "material_reference",
    ],
    "technical": [],
    "bsi": [],
    "diagnostic": [
        "fault_codes",
        "recommended_action",
    ],
    "maintenance": [
        "maintenance_last_reset_km",
        "maintenance_km_until_next",
        "maintenance_days_until_next",
        "maintenance_next_due_date",
    ],
    "other": [],
}

WORKSHOP_FLOW_STEPS = [
    {
        "code": "history_check",
        "title": "Verificar histórico",
        "description": "Consultar histórico disponível ou sinalizar que não existe histórico suficiente para apoiar a decisão.",
        "field_label": "Histórico consultado",
        "placeholder": "Regista apenas se houver algum ponto essencial para a decisão.",
        "button": "Confirmar histórico",
        "decision": "",
        "mode": "history_check",
    },
    {
        "code": "stellantis_service_box",
        "title": "Revisão Stellantis / Service Box",
        "description": "Validar plano de manutenção, simulação por KM/idade e campanhas técnicas quando aplicável.",
        "field_label": "Preparação Service Box",
        "placeholder": "Regista plano consultado, simulação, campanhas e documentos anexados ou em falta.",
        "button": "Registar Service Box",
        "decision": "",
    },
    {
        "code": "bsi_initial",
        "title": "Registo de leitura técnica / BSI inicial",
        "description": "Registar leitura técnica inicial antes de fechar o diagnóstico.",
        "field_label": "Objetivo da leitura",
        "placeholder": "Indica que leitura será efetuada e que informação se pretende validar.",
        "button": "Abrir leitura inicial",
        "decision": "",
    },
    {
        "code": "technical_info",
        "title": "Registo de informação técnica",
        "description": "Consolidar informação técnica recolhida nos relatórios, histórico e observações.",
        "field_label": "Informação técnica registada",
        "placeholder": "Resumo técnico, dados relevantes e pontos ainda por confirmar.",
        "button": "Registar informação técnica",
        "decision": "",
    },
    {
        "code": "systematic_checks",
        "title": "Verificações sistemáticas",
        "description": "Confirmar segurança e mecânica base antes de decidir serviços ou orçamento.",
        "field_label": "Verificações efetuadas",
        "placeholder": "Anomalias encontradas, evidências necessárias ou recomendação técnica.",
        "button": "Registar verificações",
        "decision": "",
    },
    {
        "code": "service_quote",
        "title": "Serviços a executar / orçamento",
        "description": "Definir trabalhos previstos, necessidade de orçamento ou material.",
        "field_label": "Serviços ou orçamento",
        "placeholder": "Serviços a executar, orçamento necessário, material previsto ou fornecedor.",
        "button": "Registar serviços/orçamento",
        "decision": "request_quote",
    },
    {
        "code": "decision",
        "title": "Registar decisão",
        "description": "Registar a decisão com contexto e sugestão de resolução.",
        "field_label": "Contexto e sugestão",
        "placeholder": "Problema identificado, opção recomendada e impacto esperado.",
        "button": "Registar decisão",
        "decision": "",
    },
    {
        "code": "bsi_final",
        "title": "Registo de leitura técnica / BSI final",
        "description": "Registar leitura final ou validação técnica após execução.",
        "field_label": "Validação técnica necessária",
        "placeholder": "Indica que leitura/validação final será registada.",
        "button": "Abrir leitura final",
        "decision": "",
    },
    {
        "code": "technical_close",
        "title": "Fecho técnico",
        "description": "Confirmar que a intervenção técnica está validada.",
        "field_label": "Conclusão técnica",
        "placeholder": "Resultado técnico, teste efetuado e evidência relevante.",
        "button": "Registar fecho técnico",
        "decision": "",
    },
    {
        "code": "administrative_close",
        "title": "Fecho administrativo",
        "description": "Confirmar documentos, custos, notas e condições de arquivo.",
        "field_label": "Conferência administrativa",
        "placeholder": "Documentos, orçamento/fatura, anexos ou pontos administrativos confirmados.",
        "button": "Registar fecho administrativo",
        "decision": "",
    },
    {
        "code": "closed",
        "title": "Fecho sem intervenção",
        "description": "Usar quando a análise confirma que não existe necessidade de intervenção.",
        "field_label": "Justificação",
        "placeholder": "Explica porque não existe necessidade de intervenção.",
        "button": "Fechar sem intervenção",
        "decision": "no_action_needed",
    },
]
for index, step in enumerate(WORKSHOP_FLOW_STEPS, start=2):
    step["index"] = index
WORKSHOP_FLOW_ORDER = ["opening", "reception", *[step["code"] for step in WORKSHOP_FLOW_STEPS]]
WORKSHOP_FLOW_TITLES = {step["code"]: step["title"] for step in WORKSHOP_FLOW_STEPS}


def workshop_phase_records(
    notes: list[WorkshopProcessNote],
    process: WorkshopProcess,
    technical_readings: list[WorkshopTechnicalReading],
) -> dict[str, dict]:
    records: dict[str, dict] = {}

    for reading in technical_readings:
        flow_phase = (reading.data_json or {}).get("flow_phase")
        if flow_phase in WORKSHOP_READING_PHASES:
            code = WORKSHOP_READING_PHASES[flow_phase]["flow_status"]
        elif flow_phase in {"bsi_initial", "bsi_final"}:
            code = flow_phase
        else:
            continue
        if code in records:
            continue
        body_lines = [
            WORKSHOP_READING_TYPE_LABELS.get(reading.reading_type, reading.reading_type),
        ]
        if reading.reading_date:
            body_lines.append(f"Data da leitura: {reading.reading_date}")
        if reading.odometer_km is not None:
            body_lines.append(f"KM: {reading.odometer_km}")
        if reading.summary:
            body_lines.append(reading.summary)
        if reading.external_url:
            body_lines.append("Relatório externo associado.")
        records[code] = {
            "title": WORKSHOP_FLOW_TITLES.get(code, WORKSHOP_STATUS_LABELS.get(code, code)),
            "body": "\n".join(body_lines),
            "body_lines": body_lines,
            "created_at": reading.created_at,
            "user_id": reading.user_id,
            "source_type": "technical_reading",
            "source_url": reading.external_url,
            "source_id": reading.id,
        }

    label_to_code = {label: code for code, label in WORKSHOP_STATUS_LABELS.items()}
    for note in notes:
        lines = [line.strip() for line in (note.note or "").splitlines() if line.strip()]
        if not lines:
            continue
        code = ""
        body_lines: list[str] = []
        if lines[0] == "Receção confirmada.":
            code = "reception"
            body_lines = lines[1:]
        elif lines[0].startswith("Fase registada: "):
            raw_code = lines[0].replace("Fase registada: ", "", 1).strip()
            code = raw_code if raw_code in WORKSHOP_STATUS_LABELS else label_to_code.get(raw_code, "")
            body_lines = [line for line in lines[1:] if not line.startswith("Fluxo atualizado:")]
        if code and code not in records:
            clean_body_lines = body_lines or ["Registo sem detalhe."]
            records[code] = {
                "title": WORKSHOP_FLOW_TITLES.get(code, WORKSHOP_STATUS_LABELS.get(code, code)),
                "body": "\n".join(clean_body_lines),
                "body_lines": clean_body_lines,
                "created_at": note.created_at,
                "user_id": note.user_id,
                "source_type": "note",
                "source_url": "",
                "source_id": note.id,
            }

    if process.status and process.decision_note and process.status not in records:
        body_lines = [line.strip() for line in process.decision_note.splitlines() if line.strip()]
        records[process.status] = {
            "title": WORKSHOP_FLOW_TITLES.get(process.status, WORKSHOP_STATUS_LABELS.get(process.status, process.status)),
            "body": process.decision_note,
            "body_lines": body_lines or [process.decision_note],
            "created_at": process.updated_at,
            "user_id": process.decided_by_id,
            "source_type": "process",
            "source_url": "",
            "source_id": process.id,
        }

    return records


def workshop_reading_flow_code(reading: WorkshopTechnicalReading) -> str:
    flow_phase = (reading.data_json or {}).get("flow_phase")
    if flow_phase in WORKSHOP_READING_PHASES:
        return WORKSHOP_READING_PHASES[flow_phase]["flow_status"]
    if flow_phase in {"bsi_initial", "bsi_final"}:
        return flow_phase
    return ""


def workshop_note_flow_record(note: WorkshopProcessNote) -> tuple[str, list[str]]:
    lines = [line.strip() for line in (note.note or "").splitlines() if line.strip()]
    if not lines:
        return "", []
    label_to_code = {label: code for code, label in WORKSHOP_STATUS_LABELS.items()}
    if lines[0] == "Receção confirmada.":
        return "reception", lines[1:]
    if lines[0].startswith("Fase registada: "):
        raw_code = lines[0].replace("Fase registada: ", "", 1).strip()
        code = raw_code if raw_code in WORKSHOP_STATUS_LABELS else label_to_code.get(raw_code, "")
        body_lines = [line for line in lines[1:] if not line.startswith("Fluxo atualizado:")]
        return code, body_lines
    return "", []


def workshop_phase_activity(
    *,
    notes: list[WorkshopProcessNote],
    services: list[WorkshopProcessService],
    evidences: list[WorkshopProcessEvidence],
    technical_readings: list[WorkshopTechnicalReading],
) -> dict[str, list[dict]]:
    activity: dict[str, list[dict]] = {}

    def add(
        code: str,
        *,
        kind: str,
        title: str,
        detail: str = "",
        created_at: datetime | None = None,
        url: str = "",
    ) -> None:
        if not code:
            return
        activity.setdefault(code, []).append(
            {
                "kind": kind,
                "title": title,
                "detail": detail,
                "created_at": created_at,
                "url": url,
            }
        )

    for service in services:
        detail = " · ".join(
            item
            for item in [
                WORKSHOP_SERVICE_DETAIL_LABELS.get(service.service_detail, service.service_detail or ""),
                WORKSHOP_SERVICE_AXIS_LABELS.get(service.service_axis, service.service_axis or ""),
                WORKSHOP_SERVICE_STATUS_LABELS.get(service.status, service.status or ""),
            ]
            if item
        )
        if service.note:
            detail = f"{detail}. {service.note}" if detail else service.note
        add(
            "reception",
            kind="Serviço",
            title=WORKSHOP_SERVICE_FAMILY_LABELS.get(service.service_family, service.service_family),
            detail=detail,
            created_at=service.created_at,
        )

    for note in notes:
        code, lines = workshop_note_flow_record(note)
        if not code:
            continue
        add(
            code,
            kind="Nota",
            title=WORKSHOP_FLOW_TITLES.get(code, WORKSHOP_STATUS_LABELS.get(code, code)),
            detail=" · ".join(lines) or "Registo sem detalhe.",
            created_at=note.created_at,
        )

    for evidence in evidences:
        detail = " · ".join(
            item
            for item in [
                WORKSHOP_EVIDENCE_TYPE_LABELS.get(evidence.evidence_type, evidence.evidence_type),
                WORKSHOP_EVIDENCE_STATUS_LABELS.get(evidence.status, evidence.status),
                evidence.description,
            ]
            if item
        )
        add(
            evidence.phase,
            kind="Evidência",
            title=WORKSHOP_EVIDENCE_CATEGORY_LABELS.get(evidence.anomaly_category, evidence.anomaly_category),
            detail=detail,
            created_at=evidence.observed_at,
            url=evidence.external_url or "",
        )

    for reading in technical_readings:
        code = workshop_reading_flow_code(reading)
        detail_parts = []
        if reading.reading_date:
            detail_parts.append(str(reading.reading_date))
        if reading.odometer_km is not None:
            detail_parts.append(f"{reading.odometer_km} km")
        if reading.summary:
            detail_parts.append(reading.summary)
        add(
            code,
            kind="Leitura",
            title=WORKSHOP_READING_TYPE_LABELS.get(reading.reading_type, reading.reading_type),
            detail=" · ".join(detail_parts) or "Leitura técnica registada.",
            created_at=reading.created_at,
            url=reading.external_url or "",
        )

    for items in activity.values():
        items.sort(key=lambda item: item["created_at"].isoformat() if item.get("created_at") else "", reverse=True)
    return activity


def workshop_latest_activity_at(
    process: WorkshopProcess,
    notes: list[WorkshopProcessNote],
    evidences: list[WorkshopProcessEvidence],
    incidents: list[Incident],
    documents: list[Document],
    technical_readings: list[WorkshopTechnicalReading],
) -> datetime | None:
    activity_dates = [
        process.updated_at,
        process.created_at,
        *(item.created_at for item in notes if item.created_at),
        *(item.observed_at for item in evidences if item.observed_at),
        *(item.created_at for item in incidents if item.created_at),
        *(item.created_at for item in documents if item.created_at),
        *(item.created_at for item in technical_readings if item.created_at),
    ]
    return max((item for item in activity_dates if item), default=None)


def build_workshop_alerts(
    *,
    process: WorkshopProcess,
    vehicle: Vehicle | None,
    phase_records: dict[str, dict],
    completed_flow_statuses: set[str],
    current_flow_index: int,
    workshop_flow_order: list[str],
    documents: list[Document],
    evidences: list[WorkshopProcessEvidence],
    incidents: list[Incident],
    technical_readings: list[WorkshopTechnicalReading],
    notes: list[WorkshopProcessNote],
) -> list[dict[str, str]]:
    alerts: list[dict[str, str]] = []

    def add(severity: str, title: str, detail: str, action: str = "") -> None:
        alerts.append(
            {
                "severity": severity,
                "title": title,
                "detail": detail,
                "action": action,
            }
        )

    def passed(step_code: str) -> bool:
        return step_code in workshop_flow_order and current_flow_index > workshop_flow_order.index(step_code)

    if not process.closed_at:
        if "reception" not in completed_flow_statuses or process.km_entry is None:
            add(
                "warning",
                "Receção incompleta",
                "Confirma a receção e o KM de entrada para fixar o início operacional do processo.",
                "Confirmar receção",
            )

        if passed("history_check") and "history_check" not in completed_flow_statuses:
            add(
                "warning",
                "Histórico por verificar",
                "O processo já avançou, mas não existe registo claro de consulta ao histórico.",
                "Verificar histórico",
            )

        if is_stellantis_vehicle(vehicle) and passed("stellantis_service_box") and "stellantis_service_box" not in completed_flow_statuses:
            add(
                "warning",
                "Service Box em falta",
                "Viatura Stellantis sem registo de plano, simulação ou campanhas técnicas.",
                "Registar Service Box",
            )

        if passed("bsi_initial") and "bsi_initial" not in completed_flow_statuses:
            add(
                "warning",
                "Leitura BSI inicial em falta",
                "Antes da decisão técnica deve existir leitura inicial ou justificação clara.",
                "Abrir leitura inicial",
            )

        if passed("systematic_checks") and "systematic_checks" not in completed_flow_statuses:
            add(
                "warning",
                "Verificações sistemáticas pendentes",
                "Segurança e mecânica rápida ainda não têm registo claro.",
                "Registar verificações",
            )

        if process.status in {"technical_close", "administrative_close", "closed"} and not documents:
            add(
                "warning",
                "Sem documentos associados",
                "Antes do fecho, confirma se orçamento, fatura, folha de obra, BSI ou evidências relevantes estão ligados ao processo.",
                "Adicionar documento",
            )

        if process.status in {"technical_close", "administrative_close", "closed"} and "bsi_final" not in completed_flow_statuses:
            add(
                "info",
                "Leitura final por confirmar",
                "Se houve intervenção técnica, regista a leitura final ou justifica que não se aplica.",
                "Abrir leitura final",
            )

        latest_activity = workshop_latest_activity_at(process, notes, evidences, incidents, documents, technical_readings)
        if latest_activity:
            latest_activity_date = latest_activity.date() if isinstance(latest_activity, datetime) else latest_activity
            idle_days = (date.today() - latest_activity_date).days
            if idle_days >= 3:
                add(
                    "info",
                    "Processo sem movimento",
                    f"Sem novos registos há {idle_days} dias. Confirma se está parado, concluído ou a aguardar terceiros.",
                    "Atualizar processo",
                )

    open_relevant_incidents = [
        item
        for item in incidents
        if item.status not in {"closed", "resolved", "no_action_needed"}
    ]
    critical_incidents = [
        item
        for item in open_relevant_incidents
        if item.severity in {"high", "critical"}
    ]
    if critical_incidents:
        add(
            "critical",
            "Incidente crítico por tratar",
            f"Existem {len(critical_incidents)} incidentes técnicos/comerciais de gravidade alta ou crítica.",
            "Rever incidentes",
        )
    elif open_relevant_incidents:
        add(
            "info",
            "Incidentes em aberto",
            f"Existem {len(open_relevant_incidents)} incidentes ainda não fechados.",
            "Rever incidentes",
        )

    if not alerts and not process.closed_at:
        add(
            "ok",
            "Sem alertas automáticos",
            "Os principais pontos de controlo estão coerentes com o estado atual do processo.",
            "Continuar fluxo",
        )

    severity_order = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
    return sorted(alerts, key=lambda item: severity_order.get(item["severity"], 9))


INCIDENT_TYPES = [
    ("technical", "Técnico"),
    ("damage", "Dano"),
    ("safety", "Segurança"),
    ("customer", "Cliente"),
    ("supplier", "Fornecedor"),
    ("operational", "Operacional"),
    ("other", "Outro"),
]
INCIDENT_TYPE_LABELS = dict(INCIDENT_TYPES)

INCIDENT_CATEGORIES = [
    ("noise", "Ruído anormal"),
    ("visible_damage", "Dano visível"),
    ("warning_light", "Luz de avaria"),
    ("wear", "Desgaste irregular"),
    ("leak", "Fuga"),
    ("broken_part", "Peça partida"),
    ("safety", "Segurança"),
    ("documentation", "Documentação"),
    ("customer_report", "Reporte de cliente"),
    ("other", "Outra situação"),
]
INCIDENT_CATEGORY_LABELS = dict(INCIDENT_CATEGORIES)

INCIDENT_SEVERITIES = [
    ("low", "Baixa"),
    ("medium", "Média"),
    ("high", "Alta"),
    ("critical", "Crítica"),
]
INCIDENT_SEVERITY_LABELS = dict(INCIDENT_SEVERITIES)

INCIDENT_STATUSES = [
    ("new", "Novo"),
    ("analysis", "Em análise"),
    ("in_treatment", "Em tratamento"),
    ("waiting_decision", "A aguardar decisão"),
    ("waiting_supplier", "A aguardar fornecedor"),
    ("resolved", "Resolvido"),
    ("closed", "Fechado"),
    ("no_action_needed", "Sem ação necessária"),
]
INCIDENT_STATUS_LABELS = dict(INCIDENT_STATUSES)

INCIDENT_EVIDENCE_TYPES = [
    ("photo", "Foto"),
    ("video", "Vídeo"),
    ("audio", "Áudio/nota de voz"),
    ("document", "Documento"),
    ("link", "Link externo"),
]
INCIDENT_EVIDENCE_TYPE_LABELS = dict(INCIDENT_EVIDENCE_TYPES)

TASK_STATUSES = [
    ("planned", "Planeada"),
    ("new", "Nova"),
    ("in_execution", "Em execução"),
    ("delegated", "Execução delegada"),
    ("waiting", "A aguardar"),
    ("execution_done", "Execução concluída"),
    ("ready_validation", "Pronta para validação"),
    ("closed", "Fechada"),
    ("cancelled", "Cancelada"),
    ("no_action_needed", "Sem ação necessária"),
]

TASK_STATUS_LABELS = dict(TASK_STATUSES)
TASK_LEGACY_STATUS_LABELS = {
    "analysis": "Em análise",
    "in_treatment": "Em tratamento",
    "waiting_customer": "A aguardar cliente",
    "waiting_internal": "A aguardar interno",
    "waiting_supplier": "A aguardar fornecedor",
    "answered": "Respondida",
    "resolved": "Resolvida",
    "no_action_needed": "Sem ação necessária",
    "cancelled": "Cancelada",
}
TASK_STATUS_DISPLAY_LABELS = {**TASK_STATUS_LABELS, **TASK_LEGACY_STATUS_LABELS}

PRIORITIES = [
    ("normal", "Normal"),
    ("high", "Alta"),
    ("urgent", "Urgente"),
]
PRIORITY_LABELS = dict(PRIORITIES)
PRIORITY_DISPLAY_LABELS = {**PRIORITY_LABELS, "low": "Baixa"}

TASK_ARCHIVE_STATUSES = {"closed", "cancelled", "no_action_needed"}
TASK_PLANNED_STATUSES = {"planned"}
TASK_RESPONSIBLE_ONLY_STATUSES = {"in_execution", "closed", "cancelled", "no_action_needed"}
TASK_ADMIN_ONLY_ASSIGNMENT_EMAILS = {"andrecoroa@daccordinvest.pt"}
TASK_NEVER_ASSIGNMENT_NAMES = {"codex carfast"}
TASK_WAITING_REASONS = [
    ("customer", "Cliente"),
    ("partner_broker", "Parceiro / Broker"),
    ("other_entity", "Outro tipo de entidade"),
    ("clarification", "Esclarecimento"),
    ("validation", "Validação"),
    ("decision", "Decisão"),
    ("other", "Outro motivo"),
]
TASK_WAITING_REASON_LABELS = dict(TASK_WAITING_REASONS)

GUIDED_FLOW_STEP_STATUSES = [
    ("pending", "Pendente"),
    ("done", "Concluído"),
    ("not_applicable", "Não aplicável"),
    ("task_created", "Tarefa criada"),
]
GUIDED_FLOW_STEP_STATUS_LABELS = dict(GUIDED_FLOW_STEP_STATUSES)
GUIDED_FLOW_STEP_STATUS_CLASS = {
    "pending": "pending",
    "done": "done",
    "not_applicable": "neutral",
    "task_created": "task",
}

GUIDED_FLOW_TEMPLATES = {
    "daily_checklist": {
        "title": "Checklist diária operacional",
        "workspaces": {"operational", "administration"},
        "description": "Rotina simples para controlo diário com vários pontos de confirmação.",
        "steps": [
            ("base_context", "Confirmar contexto", "Valida data, estação/equipa e objetivo da checklist."),
            ("pending_items", "Pendentes críticos", "Regista pendentes que exigem seguimento no dia."),
            ("communications", "Comunicações por tratar", "Confirma e regista comunicações relevantes."),
            ("exceptions", "Ocorrências / exceções", "Regista anomalias ou confirma que não existem."),
            ("close_checklist", "Fechar checklist", "Confirma conclusão e observações finais."),
        ],
    },
    "workshop_technical_history_audit": {
        "title": "Auditoria histórico técnico",
        "workspaces": {"workshop"},
        "description": "Verificação provisória de histórico de manutenção, conservação e relatórios técnicos da viatura.",
        "steps": [
            ("vehicle_base", "Dados base da viatura", "Confirmar matrícula, marca/modelo, chassi e datas principais."),
            ("rentway_history", "Histórico Rentway", "Verificar histórico disponível e sinalizar falhas."),
            ("work_orders", "Folhas de obra", "Validar folhas de obra de reparação/manutenção."),
            ("supplier_invoices", "Faturas associadas", "Confirmar se as faturas correspondem às intervenções."),
            ("bsi_reports", "BSI / diagnósticos", "Verificar existência dos relatórios técnicos relevantes."),
            ("gaps", "Falhas encontradas", "Registar falhas e gerar tarefas se necessário."),
            ("conclusion", "Conclusão da auditoria", "Fechar auditoria com resultado e recomendação."),
        ],
    },
    "workshop_revision_light": {
        "title": "Revisão oficina - fluxo leve",
        "workspaces": {"workshop"},
        "description": "Fluxo guiado leve para revisão/manutenção sem substituir o processo de oficina.",
        "steps": [
            ("reception", "Receção", "Confirmar entrada, KM e motivo da intervenção."),
            ("admin_check", "Verificação administrativa", "Validar histórico, documentos e Service Box quando aplicável."),
            ("technical_diagnosis", "Diagnóstico técnico", "Registar leitura inicial, verificações e conclusão técnica."),
            ("decision", "Decisão", "Registar decisão e próxima ação."),
            ("execution", "Intervenção técnica", "Registar serviço executado, material e evidências."),
            ("validation", "Validação", "Confirmar leitura final ou validação aplicável."),
            ("close", "Fecho", "Concluir com nota final e documentos associados."),
        ],
    },
    "document_review": {
        "title": "Tratamento documental",
        "workspaces": {"operational", "workshop", "administration"},
        "description": "Receber, classificar, associar e preparar arquivo de documentação.",
        "steps": [
            ("identify", "Identificar documento", "Confirmar origem, remetente e assunto."),
            ("classify", "Classificar", "Escolher área, tipologia e contexto."),
            ("associate", "Associar contexto", "Ligar a viatura, tarefa, processo ou entidade."),
            ("archive_decision", "Decidir arquivo", "Definir pasta sugerida ou rejeitar sem interesse."),
            ("close", "Concluir tratamento", "Confirmar link final, observações e estado."),
        ],
    },
}

RECURRENCE_RULES = [
    ("daily", "Diária"),
    ("weekly", "Semanal"),
    ("monthly", "Mensal"),
]
RECURRENCE_RULE_LABELS = dict(RECURRENCE_RULES)

TASK_TYPES = [
    ("operational_task", "Tarefa operacional"),
    ("workshop_task", "Tarefa da oficina"),
    ("management_task", "Tarefa de gestão"),
    ("administration_task", "Tarefa de administração"),
    ("request_info", "Pedido / Informação"),
    ("operational_incident", "Incidente operacional"),
    ("technical_incident", "Incidente técnico"),
    ("entity_incident", "Incidente entidade"),
    ("workshop_audit", "Tarefa de auditoria"),
]
TASK_LEGACY_TYPE_LABELS = {
    "task": "Tarefa",
    "request": "Pedido",
    "incident": "Incidente",
}
LEGACY_TASK_TYPES = list(TASK_LEGACY_TYPE_LABELS.items())
TASK_TYPE_LABELS = {**dict(TASK_TYPES), **TASK_LEGACY_TYPE_LABELS}
TASK_TYPE_CANONICAL_GROUP = {
    "task": "operational_task",
    "request": "request_info",
    "incident": "operational_incident",
    "management_task": "administration_task",
}
TASK_TYPE_LEGACY_BY_CANONICAL = {
    "operational_task": ["task"],
    "request_info": ["request"],
    "operational_incident": ["incident"],
}
TASK_BOARD_TYPE_LABELS = {
    "operational_task": "Tarefas operacionais",
    "workshop_task": "Tarefas da oficina",
    "management_task": "Tarefas de gestão",
    "administration_task": "Tarefas de administração",
    "request_info": "Pedidos / Informação",
    "operational_incident": "Incidentes operacionais",
    "technical_incident": "Incidentes técnicos",
    "entity_incident": "Incidentes entidade",
    "workshop_audit": "Tarefas de auditoria",
}

TASK_WORKSPACES = [
    ("operational", "Operacional"),
    ("workshop", "Oficina"),
    ("administration", "Administração"),
]
TASK_WORKSPACE_LABELS = dict(TASK_WORKSPACES)
TASK_WORKSPACE_ALIASES = {
    "management": "administration",
}
TASK_WORKSPACE_CONFIG = {
    "operational": {
        "label": "Operacional",
        "eyebrow": "Centro operacional",
        "title": "Gestão operacional",
        "breadcrumb": "Centro de Tarefas > Operacional",
        "description": "Execução diária, pedidos, comunicações, anomalias e reclamações.",
        "default_task_type": "operational_task",
        "primary_task_types": [
            "operational_task",
            "task",
            "request_info",
            "request",
            "operational_incident",
            "incident",
            "technical_incident",
            "entity_incident",
        ],
        "secondary_task_types": [],
        "default_category": "operations",
        "default_team_code": "operations",
    },
    "workshop": {
        "label": "Oficina",
        "eyebrow": "Centro de oficina",
        "title": "Tarefas da oficina",
        "breadcrumb": "Centro de Tarefas > Oficina",
        "description": "Tarefas técnicas, registos rápidos e auditoria da oficina.",
        "default_task_type": "workshop_task",
        "primary_task_types": ["workshop_task"],
        "secondary_task_types": ["workshop_audit"],
        "default_category": "workshop",
        "default_team_code": "workshop",
    },
    "administration": {
        "label": "Administração",
        "eyebrow": "Centro reservado",
        "title": "Tarefas de administração",
        "breadcrumb": "Centro de Tarefas > Administração",
        "description": "Assuntos reservados da direção/administração, fora do backlog operacional.",
        "default_task_type": "administration_task",
        "primary_task_types": ["administration_task"],
        "secondary_task_types": [],
        "default_category": "other",
        "default_team_code": "finance",
    },
}
TASK_WORKSPACE_TASK_TYPES = {
    workspace: [*config["primary_task_types"], *config["secondary_task_types"]]
    for workspace, config in TASK_WORKSPACE_CONFIG.items()
}

QUICK_RECORD_TYPES_BY_WORKSPACE = {
    "operational": [
        ("request", "Pedido"),
        ("information", "Informação / Comunicação"),
        ("anomaly_incident", "Anomalia / Incidente"),
        ("complaint", "Reclamação"),
        ("other", "Outro"),
    ],
    "workshop": [
        ("technical_request", "Pedido técnico"),
        ("information", "Informação / Comunicação"),
        ("anomaly_incident", "Anomalia / Incidente"),
        ("material", "Material"),
        ("evidence", "Evidência"),
        ("other", "Outro"),
    ],
    "administration": [
        ("decision", "Decisão"),
        ("sensitive_document", "Documento sensível"),
        ("finance_topic", "Tema financeiro"),
        ("reserved_followup", "Follow-up reservado"),
        ("implementation", "Implementação"),
        ("supervision", "Supervisão"),
        ("improvement", "Melhoria"),
        ("other", "Outro"),
    ],
}
QUICK_RECORD_TYPE_LABELS = {
    code: label
    for items in QUICK_RECORD_TYPES_BY_WORKSPACE.values()
    for code, label in items
}
QUICK_RECORD_STATUSES = [
    ("new", "Novo"),
    ("analysis", "Em análise"),
    ("converted", "Convertido"),
    ("closed", "Fechado"),
]
QUICK_RECORD_STATUS_LABELS = dict(QUICK_RECORD_STATUSES)
QUICK_RECORD_ARCHIVE_STATUSES = ("closed", "converted", "no_action_needed")

WORKSHOP_BLOCKED_VEHICLE_STATUSES = {"sold", "written_off", "inactive"}
STELLANTIS_BRANDS = {
    "abarth",
    "alfa romeo",
    "chrysler",
    "citroen",
    "dodge",
    "ds",
    "fiat",
    "jeep",
    "lancia",
    "maserati",
    "opel",
    "peugeot",
    "ram",
    "vauxhall",
}


def normalize_vehicle_brand(brand: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (brand or "").casefold()).strip()


def is_stellantis_vehicle(vehicle: Vehicle | None) -> bool:
    return normalize_vehicle_brand(vehicle.brand if vehicle else None) in STELLANTIS_BRANDS


def workshop_flow_steps_for_vehicle(vehicle: Vehicle | None) -> list[dict]:
    if is_stellantis_vehicle(vehicle):
        steps = WORKSHOP_FLOW_STEPS
    else:
        steps = [step for step in WORKSHOP_FLOW_STEPS if step["code"] != "stellantis_service_box"]
    return [dict(step, index=index) for index, step in enumerate(steps, start=2)]


def normalize_task_workspace(workspace: str | None) -> str:
    aliased_workspace = TASK_WORKSPACE_ALIASES.get(workspace or "", workspace)
    return aliased_workspace if aliased_workspace in TASK_WORKSPACE_CONFIG else "operational"


def task_workspace_read_permissions(workspace: str | None) -> set[str]:
    clean_workspace = normalize_task_workspace(workspace)
    return {f"tasks.{clean_workspace}.read", f"tasks.{clean_workspace}.write", "admin.manage"}


def task_workspace_write_permissions(workspace: str | None) -> set[str]:
    clean_workspace = normalize_task_workspace(workspace)
    return {f"tasks.{clean_workspace}.write", "admin.manage"}


def user_can_access_task_workspace(db, user: User | None, workspace: str | None, *, write: bool = False) -> bool:
    if not user or not user.active:
        return False
    permissions = get_user_permission_codes(db, user)
    required = task_workspace_write_permissions(workspace) if write else task_workspace_read_permissions(workspace)
    return bool(permissions.intersection(required))


def user_task_workspace_codes(db, user: User | None, *, write: bool = False) -> list[str]:
    return [
        workspace_code
        for workspace_code in TASK_WORKSPACE_CONFIG
        if user_can_access_task_workspace(db, user, workspace_code, write=write)
    ]


def user_can_create_recurring_tasks(db, user: User | None) -> bool:
    if not user or not user.active:
        return False
    permissions = get_user_permission_codes(db, user)
    return bool({"admin.manage", "tasks.create_recurring"} & permissions)


def guided_flow_options_for_workspace(workspace: str) -> list[tuple[str, str]]:
    clean_workspace = normalize_task_workspace(workspace)
    return [
        (code, template["title"])
        for code, template in GUIDED_FLOW_TEMPLATES.items()
        if clean_workspace in template["workspaces"]
    ]


def guided_flow_template(flow_code: str | None) -> dict | None:
    if not flow_code:
        return None
    return GUIDED_FLOW_TEMPLATES.get(flow_code)


def create_guided_flow_run_for_task(db, task: Task, flow_code: str | None, user_id: int | None) -> TaskGuidedFlowRun | None:
    template = guided_flow_template(flow_code)
    if not template:
        return None
    exists = db.scalar(select(TaskGuidedFlowRun).where(TaskGuidedFlowRun.task_id == task.id))
    if exists:
        return exists
    run = TaskGuidedFlowRun(
        task_id=task.id,
        flow_code=flow_code or "",
        title=template["title"],
        status="active",
        started_by_id=user_id,
    )
    db.add(run)
    db.flush()
    for index, (step_code, title, description) in enumerate(template["steps"], start=1):
        db.add(
            TaskGuidedFlowStepRun(
                flow_run_id=run.id,
                task_id=task.id,
                step_code=step_code,
                title=title,
                sort_order=index,
                status="pending",
                data_json={"description": description},
            )
        )
    task.guided_flow_code = flow_code
    return run


def task_guided_flow_context(db, task: Task) -> dict:
    flow_run = db.scalar(
        select(TaskGuidedFlowRun)
        .where(TaskGuidedFlowRun.task_id == task.id)
        .order_by(TaskGuidedFlowRun.id.desc())
    )
    if not flow_run:
        return {"run": None, "steps": [], "progress": {"total": 0, "done": 0, "pending": 0}}
    steps = db.scalars(
        select(TaskGuidedFlowStepRun)
        .where(TaskGuidedFlowStepRun.flow_run_id == flow_run.id)
        .order_by(TaskGuidedFlowStepRun.sort_order, TaskGuidedFlowStepRun.id)
    ).all()
    done_count = sum(1 for step in steps if step.status in {"done", "not_applicable", "task_created"})
    pending_count = sum(1 for step in steps if step.status == "pending")
    return {
        "run": flow_run,
        "steps": steps,
        "progress": {"total": len(steps), "done": done_count, "pending": pending_count},
    }


def next_recurrence_date(base: date | None, rule: str | None, interval: int | None) -> date | None:
    if rule not in RECURRENCE_RULE_LABELS:
        return None
    clean_interval = max(interval or 1, 1)
    start = base or date.today()
    if rule == "daily":
        return start + timedelta(days=clean_interval)
    if rule == "weekly":
        return start + timedelta(weeks=clean_interval)
    if rule == "monthly":
        month = start.month - 1 + clean_interval
        year = start.year + month // 12
        month = month % 12 + 1
        days_in_month = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        return date(year, month, min(start.day, days_in_month[month - 1]))
    return None


def create_next_recurring_task(db, task: Task, user_id: int | None) -> Task | None:
    if not task.recurrence_enabled or not task.recurrence_rule:
        return None
    next_on = task.recurrence_next_on or next_recurrence_date(task.due_on or date.today(), task.recurrence_rule, task.recurrence_interval)
    if not next_on:
        return None
    existing = db.scalar(
        select(Task).where(
            Task.recurrence_created_from_task_id == task.id,
            Task.planned_for == next_on,
            Task.closed_at.is_(None),
        )
    )
    if existing:
        return existing
    next_task = Task(
        title=task.title,
        description=task.description,
        task_type=task.task_type,
        source=task.source,
        category=task.category,
        subcategory=task.subcategory,
        status="planned",
        priority=task.priority,
        customer_name=task.customer_name,
        customer_contact=task.customer_contact,
        customer_email=task.customer_email,
        customer_phone=task.customer_phone,
        plate=task.plate,
        reservation_number=task.reservation_number,
        contract_number=task.contract_number,
        station=task.station,
        department=task.department,
        external_source_id=task.external_source_id,
        entity_type=task.entity_type,
        entity_id=task.entity_id,
        team_id=task.team_id,
        assigned_to_id=task.assigned_to_id,
        delegated_to_user_id=task.delegated_to_user_id,
        delegated_to_team_id=task.delegated_to_team_id,
        created_by_id=user_id,
        due_on=next_on,
        planned_for=next_on,
        guided_flow_code=task.guided_flow_code,
        recurrence_enabled=True,
        recurrence_rule=task.recurrence_rule,
        recurrence_interval=task.recurrence_interval or 1,
        recurrence_next_on=next_recurrence_date(next_on, task.recurrence_rule, task.recurrence_interval),
        recurrence_created_from_task_id=task.id,
    )
    db.add(next_task)
    db.flush()
    create_guided_flow_run_for_task(db, next_task, next_task.guided_flow_code, user_id)
    db.add(
        TaskHistory(
            task_id=next_task.id,
            user_id=user_id,
            field_name="status",
            old_value=None,
            new_value=TASK_STATUS_DISPLAY_LABELS.get("planned", "Planeada"),
        )
    )
    return next_task


def user_accessible_task_type_codes(db, user: User | None) -> list[str]:
    task_types: list[str] = []
    for workspace_code in user_task_workspace_codes(db, user):
        task_types.extend(TASK_WORKSPACE_TASK_TYPES[workspace_code])
    return task_types


def task_workspace_manage_url(workspace: str | None) -> str:
    clean_workspace = normalize_task_workspace(workspace)
    if clean_workspace == "operational":
        return "/task-board/manage"
    return f"/task-board/{clean_workspace}/manage"


def task_workspace_new_url(workspace: str | None, mode: str = "task") -> str:
    clean_workspace = normalize_task_workspace(workspace)
    return f"/task-board/new?mode={mode}&workspace={clean_workspace}"


def workspace_task_type_options(workspace: str | None) -> list[tuple[str, str]]:
    clean_workspace = normalize_task_workspace(workspace)
    allowed_codes = set(TASK_WORKSPACE_TASK_TYPES[clean_workspace])
    return [(code, label) for code, label in TASK_TYPES if code in allowed_codes]


def workspace_for_task_type(task_type: str | None) -> str:
    normalized_type = TASK_TYPE_CANONICAL_GROUP.get(task_type or "", task_type or "")
    for workspace, codes in TASK_WORKSPACE_TASK_TYPES.items():
        if (task_type or "") in codes or normalized_type in codes:
            return workspace
    return "operational"


def default_task_subcategory(category: str | None) -> str:
    options = TASK_SUBCATEGORIES_BY_CATEGORY.get(category or "", TASK_SUBCATEGORIES_BY_CATEGORY["other"])
    return options[0][0]


def normalize_task_subcategory(category: str | None, subcategory: str | None) -> str:
    clean_category = category if category in TASK_CATEGORY_LABELS else "other"
    clean_subcategory = (subcategory or "").strip()
    allowed = {code for code, _ in TASK_SUBCATEGORIES_BY_CATEGORY.get(clean_category, [])}
    return clean_subcategory if clean_subcategory in allowed else default_task_subcategory(clean_category)


def task_subcategory_allows_manual_text(subcategory: str | None) -> bool:
    clean_subcategory = (subcategory or "").strip().lower()
    display_label = TASK_SUBCATEGORY_DISPLAY_LABELS.get(clean_subcategory, clean_subcategory).lower()
    return clean_subcategory == "other" or clean_subcategory.endswith("_other") or "outro" in display_label

TASK_SOURCES = [
    ("manual", "Manual"),
    ("system", "Sistema"),
    ("external", "Externo"),
]

TASK_SOURCE_LABELS = dict(TASK_SOURCES)
TASK_LEGACY_SOURCE_LABELS = {
    "email": "E-mail",
    "whatsapp": "WhatsApp",
    "webex": "Webex",
    "rentway": "Rentway",
    "external_portal": "Portal externo",
}
TASK_SOURCE_DISPLAY_LABELS = {**TASK_SOURCE_LABELS, **TASK_LEGACY_SOURCE_LABELS}

TASK_CATEGORIES = [
    ("support", "Suporte"),
    ("operations", "Operações"),
    ("workshop", "Oficina"),
    ("other", "Outro"),
]

TASK_CATEGORY_LABELS = dict(TASK_CATEGORIES)
TASK_SUBCATEGORIES_BY_CATEGORY = {
    "support": [
        ("support_tbd", "A definir"),
        ("support_other", "Outro suporte"),
    ],
    "operations": [
        ("operations_tbd", "A definir"),
        ("operations_other", "Outro operacional"),
    ],
    "workshop": [
        ("workshop_tbd", "A definir"),
        ("workshop_other", "Outro oficina"),
    ],
    "other": [
        ("other_tbd", "A classificar"),
        ("other", "Outro"),
    ],
}
TASK_SUBCATEGORY_LABELS = {
    code: label
    for subcategories in TASK_SUBCATEGORIES_BY_CATEGORY.values()
    for code, label in subcategories
}
TASK_LEGACY_CATEGORY_LABELS = {
    "finance": "Financeira",
    "reservas": "Reservas",
    "alteracoes": "Alterações",
    "cancelamentos": "Cancelamentos",
    "caucoes_reembolsos": "Cauções/Reembolsos",
    "faturacao": "Faturação",
    "danos": "Danos",
    "sinistros": "Sinistros",
    "reclamacoes": "Reclamações",
    "assistencia": "Assistência",
    "shuttle_aeroporto": "Shuttle/Aeroporto",
    "manutencao": "Manutenção",
    "logistica_viaturas": "Logística de viaturas",
    "brokers": "Brokers",
    "corporate": "Corporate",
    "sem_acao_necessaria": "Sem ação necessária",
}
TASK_CATEGORY_DISPLAY_LABELS = {**TASK_CATEGORY_LABELS, **TASK_LEGACY_CATEGORY_LABELS}
TASK_SUBCATEGORY_DISPLAY_LABELS = {**TASK_SUBCATEGORY_LABELS}

EXTERNAL_PORTAL_CATEGORIES = [
    ("operations", "Pedido geral"),
    ("reservas", "Reserva"),
    ("alteracoes", "Alteração"),
    ("faturacao", "Faturação"),
    ("danos", "Danos"),
    ("sinistros", "Sinistro"),
    ("assistencia", "Assistência"),
    ("workshop", "Oficina"),
]
EXTERNAL_PORTAL_CATEGORY_LABELS = dict(EXTERNAL_PORTAL_CATEGORIES)
EXTERNAL_PORTAL_RATE_LIMIT: dict[str, list[float]] = {}
EXTERNAL_PORTAL_RATE_LIMIT_WINDOW_SECONDS = 600
EXTERNAL_PORTAL_RATE_LIMIT_MAX_REQUESTS = 5

PILOT_FEEDBACK_KINDS = [
    ("question", "Pedir ajuda"),
    ("experience", "Relatar experiência"),
]
PILOT_FEEDBACK_KIND_LABELS = dict(PILOT_FEEDBACK_KINDS)
PILOT_FEEDBACK_SOURCE_LABELS = {
    "dashboard": "Dashboard",
    "tasks": "Gestão de Tarefas",
    "workshop": "Oficina",
    "fleet": "Frota",
    "imports": "Importações",
    "documents": "Documentos",
    "admin": "Administração",
    "general": "Geral",
}

HISTORY_AUDIT_PHASES = [
    ("document_collection", "Recolha documental"),
    ("service_classification", "Classificação de serviços"),
    ("technical_loading", "Carregamento técnico"),
    ("crosscheck", "Cruzamento / divergências"),
    ("discussion", "Discussão"),
    ("assumed_truth", "Verdade assumida"),
    ("future_rules", "Regras futuras"),
    ("closed", "Fecho"),
]
HISTORY_AUDIT_PHASE_LABELS = dict(HISTORY_AUDIT_PHASES)
HISTORY_AUDIT_STATUS_LABELS = {
    "building": "Em construção",
    "validation": "Em validação",
    "truth_assumed": "Verdade assumida",
    "monitoring": "Em acompanhamento",
    "open": "Aberta",
    "in_progress": "Em curso",
    "pending_discussion": "Para discussão",
    "closed": "Fechada",
}
HISTORY_AUDIT_CONFIDENCE_LABELS = {"low": "Baixa", "medium": "Média", "high": "Alta"}
HISTORY_AUDIT_DOCUMENT_TYPES = [
    ("invoice", "Fatura"),
    ("work_order", "Folha de obra"),
    ("technical_report", "Relatório técnico"),
    ("maintenance_information", "BSI / Informações manutenção"),
    ("engine_lubrication", "Lubrificação motor"),
    ("maintenance_programming", "Programação manutenção"),
    ("fault_reading", "Jornal defeitos"),
    ("global_test", "Teste global"),
    ("telecoding_identification", "Telecarregamento"),
    ("service_box", "Service Box"),
    ("tsb", "TSB / Campanha"),
    ("other", "Outro"),
]
HISTORY_AUDIT_SERVICE_FAMILIES = [
    ("maintenance", "Manutenção"),
    ("oil", "Óleo"),
    ("filter", "Filtro"),
    ("diagnosis", "Diagnóstico"),
    ("telecharge", "Telecarregamento"),
    ("tyres", "Pneus"),
    ("brake_pads", "Calços"),
    ("brake_discs", "Discos"),
    ("braking", "Travagem"),
    ("suspension", "Suspensão"),
    ("steering", "Direção"),
    ("battery", "Bateria"),
    ("wipers", "Escovas"),
    ("lighting", "Iluminação"),
    ("adblue", "AdBlue"),
    ("belts", "Correias"),
    ("ac", "AC"),
    ("body_damage", "Carroçaria / danos"),
    ("other", "Outros"),
]
HISTORY_AUDIT_ISSUE_TYPES = [
    ("bsi", "BSI"),
    ("oil", "Óleo"),
    ("telecharge", "Telecarregamento"),
    ("maintenance", "Manutenção"),
    ("tyres", "Pneus"),
    ("brakes", "Travões"),
    ("billing", "Faturação"),
    ("plan", "Plano"),
    ("tsb", "TSB"),
    ("documents", "Documentos"),
    ("technical_reading", "Leitura técnica"),
    ("other", "Outro"),
]
HISTORY_AUDIT_ISSUE_STATUS_LABELS = {
    "por_analisar": "Por analisar",
    "em_discussao": "Em discussão",
    "aguardar_resposta": "Aguardar resposta",
    "confirmado": "Confirmado",
    "descartado": "Descartado",
    "resolvido": "Resolvido",
    "new": "Novo",
    "in_analysis": "Em análise",
    "to_discuss": "Para discutir",
    "waiting_evidence": "Aguarda evidência",
    "converted_incident": "Convertido em incidente",
    "discarded": "Descartado",
    "resolved": "Resolvido",
}
HISTORY_AUDIT_RULE_TYPES = [
    ("workshop", "Oficina"),
    ("sale", "Venda"),
    ("maintenance", "Manutenção"),
    ("claim", "Reclamação"),
    ("documents", "Documentos"),
    ("other", "Outro"),
]
HISTORY_AUDIT_REPORT_LABELS = dict(HISTORY_AUDIT_DOCUMENT_TYPES)
CLEAN_WORKSHOP_REPORT_LABELS = {
    "engine_lubrication": "Informações lubrificação motor",
    "maintenance_information": "Informações de manutenção",
    "maintenance_programming": "Programação de manutenção",
    "fault_reading": "Leitura de defeitos",
    "remote_download": "Telecarregamento",
    "global_test": "Teste global",
    "other_reading": "Relatório de diagnóstico do veículo",
}
CLEAN_WORKSHOP_REPORT_CODES = set(CLEAN_WORKSHOP_REPORT_LABELS)


def clean_workshop_report_display_label(report_code: str, fallback: str | None = None) -> str:
    return CLEAN_WORKSHOP_REPORT_LABELS.get(report_code, (fallback or report_code))


HISTORY_AUDIT_EXTRACTABLE_REPORTS = {
    "maintenance_information",
    "engine_lubrication",
    "maintenance_programming",
    "fault_reading",
    "telecoding_identification",
}


def stellantis_report_fields(report_code: str) -> list[dict[str, object]]:
    for report in STELLANTIS_REPORTS:
        if report.get("code") == report_code:
            return list(report.get("fields") or [])
    return []


def history_audit_reading_rows(
    report_code: str,
    extracted_values: dict | None,
) -> list[dict[str, str | None]]:
    values = extracted_values if isinstance(extracted_values, dict) else {}
    fields = stellantis_report_fields(report_code)
    rows: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for field in fields:
        code = str(field.get("code") or "")
        if not code:
            continue
        seen.add(code)
        value = values.get(code)
        if value in (None, ""):
            continue
        rows.append(
            {
                "field_code": code,
                "field_label": str(field.get("label") or code),
                "unit": str(field.get("unit")) if field.get("unit") else None,
                "extracted_value": str(value),
            }
        )
    for code, value in values.items():
        if code in seen or value in (None, ""):
            continue
        rows.append(
            {
                "field_code": str(code),
                "field_label": str(code).replace("_", " ").title(),
                "unit": None,
                "extracted_value": str(value),
            }
        )
    return rows

ADMIN_USER_ROLES = [
    ("operator", "Operador"),
    ("manager", "Gestor"),
    ("admin", "Admin"),
    ("viewer", "Consulta"),
]

TASK_CLASSIFICATION_ACCESS_RULES = [
    {
        "scope": "Centro de tarefas",
        "name": "Administração",
        "status": "Ativo",
        "permission": "tasks.administration.read / write",
        "summary": "Assuntos reservados ficam no centro Administração e só aparecem a perfis com permissão própria.",
    },
    {
        "scope": "Classificação",
        "name": "Documento sensível",
        "status": "Preparado",
        "permission": "A definir por classificação",
        "summary": "Base prevista para restringir categorias/subcategorias sensíveis sem criar outro centro de tarefas.",
    },
    {
        "scope": "Subclassificação",
        "name": "Financeiro / Direção / Supervisão",
        "status": "Futuro",
        "permission": "A definir por perfil",
        "summary": "Permite esconder ou limitar apenas certos tipos de assunto dentro do mesmo centro.",
    },
]

IMPLEMENTATION_ROADMAP = [
    {
        "area": "Piloto",
        "title": "Gestão de relatos",
        "status": "Próximo",
        "priority": "Alta",
        "summary": "Ver autor, responder, fechar ou converter relatos em tarefas.",
    },
    {
        "area": "Documentos",
        "title": "Anexos por link",
        "status": "Próximo",
        "priority": "Alta",
        "summary": "Associar links 365, fotos, vídeos ou evidências a tarefas e processos.",
    },
    {
        "area": "Stock",
        "title": "Gestão de stock fase 1",
        "status": "A avaliar",
        "priority": "Alta",
        "summary": "Artigos, movimentos simples, pedidos e consumo associado à operação.",
    },
    {
        "area": "Tarefas",
        "title": "Fluxos por tarefa tipo lego",
        "status": "A desenhar",
        "priority": "Alta",
        "summary": "Montar fluxos com ações reutilizáveis por natureza ou contexto.",
    },
    {
        "area": "Comunicação",
        "title": "Envio e receção de e-mails",
        "status": "A avaliar",
        "priority": "Média",
        "summary": "Criar tarefas a partir de e-mail e responder com histórico associado.",
    },
    {
        "area": "Arquivo",
        "title": "Estrutura documental 365",
        "status": "A validar",
        "priority": "Média",
        "summary": "Regras leves de arquivo por Frota, Financeiro, Rentway e Arquivo Geral.",
    },
    {
        "area": "Portal externo",
        "title": "Portal externo fase 2",
        "status": "Futuro",
        "priority": "Média",
        "summary": "Permitir anexos e melhor classificação de pedidos externos.",
    },
    {
        "area": "Administração",
        "title": "Permissões e áreas",
        "status": "Base ativa",
        "priority": "Alta",
        "summary": "Permissões principais por perfil já ativas; áreas por utilizador existem e falta aplicar a filtragem fina por contexto.",
    },
]

DOCUMENT_AREAS = [
    ("workshop", "Oficina"),
    ("fleet", "Frota"),
    ("finance", "Financeiro"),
]
DOCUMENT_AREA_LABELS = {
    **dict(DOCUMENT_AREAS),
    "fleet": "Frota",
    "rentway_imports": "Rentway Importações",
    "general_archive": "Arquivo Geral",
}

DOCUMENT_TYPES = [
    ("workshop_photo", "Foto"),
    ("workshop_diagnostic", "Diagnóstico"),
    ("workshop_bsi", "BSI / Dados técnicos"),
    ("workshop_work_order", "Folha de obra"),
    ("workshop_quote", "Orçamento"),
    ("workshop_supplier_invoice", "Fatura"),
    ("workshop_evidence", "Comprovativo / evidência"),
    ("workshop_report", "Relatório técnico"),
    ("workshop_other", "Outro documento de oficina"),
    ("maintenance_plan", "Plano de manutenção"),
    ("finance_supplier_invoice", "Fatura fornecedor"),
    ("finance_credit_note", "Nota de crédito"),
    ("finance_receipt", "Recibo"),
    ("finance_payment_proof", "Comprovativo pagamento"),
    ("finance_customer_document", "Documento cliente"),
    ("finance_rental_plan", "Plano de renda / Plano financeiro"),
    ("finance_other", "Outro documento financeiro"),
]
DOCUMENT_TYPE_LABELS = {
    **dict(DOCUMENT_TYPES),
    "general_fleet": "Geral Frota",
    "general_finance": "Geral Financeiro",
    "general_rentway": "Geral Rentway",
    "general_archive": "Geral Arquivo",
}
DOCUMENT_TYPE_AREAS = {
    "workshop_photo": "workshop",
    "workshop_diagnostic": "workshop",
    "workshop_bsi": "workshop",
    "workshop_work_order": "workshop",
    "workshop_quote": "workshop",
    "workshop_supplier_invoice": "workshop",
    "workshop_evidence": "workshop",
    "workshop_report": "workshop",
    "workshop_other": "workshop",
    "maintenance_plan": "fleet",
    "finance_supplier_invoice": "finance",
    "finance_credit_note": "finance",
    "finance_receipt": "finance",
    "finance_payment_proof": "finance",
    "finance_customer_document": "finance",
    "finance_rental_plan": "finance",
    "finance_other": "finance",
}

DOCUMENT_STATUSES = [
    ("received", "Recebido"),
    ("unclassified", "Por classificar"),
    ("associated", "Associado"),
    ("validated", "Validado"),
    ("classified", "Classificado"),
    ("archived", "Arquivado"),
    ("rejected", "Rejeitado / Sem interesse"),
]
DOCUMENT_STATUS_LABELS = dict(DOCUMENT_STATUSES)

DOCUMENT_ATTACHMENT_STATUSES = [
    ("pending", "Por tratar"),
    ("classified", "Classificado / a arquivar"),
    ("archived", "Arquivado"),
    ("rejected", "Rejeitado / sem interesse"),
]
DOCUMENT_ATTACHMENT_STATUS_LABELS = dict(DOCUMENT_ATTACHMENT_STATUSES)

DOCUMENT_SOURCES = [
    ("email", "E-mail"),
    ("manual", "Manual"),
    ("whatsapp", "WhatsApp"),
    ("scanner", "Scanner"),
    ("rentway", "Rentway"),
    ("workshop", "Oficina"),
    ("onedrive", "OneDrive/SharePoint"),
    ("other", "Outro"),
]


@web_router.get("/portal", response_class=HTMLResponse)
@web_router.get("/portal/pedido", response_class=HTMLResponse)
def external_portal_request_form(
    request: Request,
    sent: str | None = None,
    ref: str | None = None,
    error: str | None = None,
):
    error_messages = {
        "required": "Indica o assunto, a mensagem e pelo menos um contacto.",
        "consent": "Confirma que podemos usar os dados enviados para tratar o pedido.",
        "rate_limit": "Foram enviados vários pedidos recentemente. Tenta novamente dentro de alguns minutos.",
        "spam": "Não foi possível registar o pedido.",
    }
    return templates.TemplateResponse(
        request,
        "external_request.html",
        {
            "categories": EXTERNAL_PORTAL_CATEGORIES,
            "sent": sent == "1",
            "reference": ref,
            "error": error_messages.get(error),
        },
    )


@web_router.post("/portal/pedido", response_class=HTMLResponse)
def external_portal_request_create(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    category: str = Form(""),
    subject: str = Form(""),
    message: str = Form(""),
    plate: str = Form(""),
    reservation_number: str = Form(""),
    contract_number: str = Form(""),
    station: str = Form(""),
    consent: str = Form(""),
    company: str = Form(""),
):
    if company.strip():
        return RedirectResponse("/portal/pedido?error=spam", status_code=303)
    if not external_portal_rate_limit_allows(external_client_key(request)):
        return RedirectResponse("/portal/pedido?error=rate_limit", status_code=303)
    if not consent:
        return RedirectResponse("/portal/pedido?error=consent", status_code=303)

    clean_subject = subject.strip()
    clean_message = message.strip()
    clean_email = email.strip().lower()
    clean_phone = phone.strip()
    clean_name = name.strip()
    if not clean_subject or not clean_message or not (clean_email or clean_phone):
        return RedirectResponse("/portal/pedido?error=required", status_code=303)
    if category not in EXTERNAL_PORTAL_CATEGORY_LABELS:
        category = "operations"

    with SessionLocal() as db:
        assigned_team_id = default_team_id(db, "support") or default_team_id(db, "operations")
        task = Task(
            title=clean_subject[:200],
            description=build_external_portal_description(
                message=clean_message,
                category=category,
                station=station,
            ),
            task_type="request_info",
            source="external_portal",
            category=category,
            subcategory=normalize_task_subcategory(category, ""),
            status="new",
            priority="normal",
            customer_name=clean_name[:200] or None,
            customer_contact=(clean_email or clean_phone)[:200] or None,
            customer_email=clean_email[:255] or None,
            customer_phone=clean_phone[:80] or None,
            plate=plate.strip().upper().replace(" ", "")[:40] or None,
            reservation_number=reservation_number.strip()[:120] or None,
            contract_number=contract_number.strip()[:120] or None,
            station=station.strip()[:120] or None,
            department="Suporte",
            external_source_id=None,
            assigned_to_id=None,
            team_id=assigned_team_id,
            created_by_id=None,
        )
        db.add(task)
        db.flush()
        task.external_source_id = f"portal:{task.id:05d}"
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=None,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        db.add(
            TaskComment(
                task_id=task.id,
                user_id=None,
                comment="Pedido recebido através do portal externo.",
            )
        )
        record_audit(
            db,
            action="external_portal.task_created",
            entity_type="task",
            entity_id=task.id,
            detail=f"Pedido externo registado: {task.title}",
            after_json={
                "source": "external_portal",
                "category": category,
                "team_id": assigned_team_id,
            },
            user_id=None,
        )
        db.commit()
        reference = f"CF-TASK-{task.id:05d}"

    return RedirectResponse(f"/portal/pedido?sent=1&ref={reference}", status_code=303)


@web_router.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)
        today = date.today()
        permission_codes = set(get_user_permission_codes(db, user))
        can_view_tasks = False
        can_view_fleet = bool({"vehicles.read", "vehicles.write"} & permission_codes)
        can_view_workshop = bool({"workshop.read", "workshop.write"} & permission_codes)
        can_view_documents = bool({"documents.read", "documents.write"} & permission_codes)
        can_view_imports = bool({"imports.run", "imports.approve"} & permission_codes)
        accessible_task_types = user_accessible_task_type_codes(db, user)
        can_view_tasks = bool(accessible_task_types)
        task_access_condition = (
            Task.task_type.in_(tuple(accessible_task_types))
            if accessible_task_types
            else Task.id == -1
        )
        open_subtask_condition = (
            task_access_condition,
            Task.closed_at.is_(None),
            ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
            Task.parent_task_id.is_not(None),
        )
        unavailable_vehicle_statuses = {"blocked", "in_maintenance", "in_preparation", "in_impro"}
        open_workshop_statuses = {code for code, _ in WORKSHOP_STATUSES if code != "closed"}
        metrics = {
            "vehicles": count_rows(db, Vehicle) if can_view_fleet else 0,
            "for_sale_vehicles": db.scalar(
                select(func.count()).select_from(Vehicle).where(Vehicle.lifecycle_status == "for_sale")
            )
            if can_view_fleet
            else 0,
            "open_tasks": db.scalar(
                select(func.count()).select_from(Task).where(task_access_condition, Task.closed_at.is_(None), ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES))
            )
            if can_view_tasks
            else 0,
            "open_subtasks": db.scalar(
                select(func.count()).select_from(Task).where(*open_subtask_condition)
            )
            if can_view_tasks
            else 0,
            "imports": count_rows(db, ImportBatch) if can_view_imports else 0,
            "documents": count_rows(db, Document) if can_view_documents else 0,
            "overdue_tasks": db.scalar(
                select(func.count()).select_from(Task).where(
                    task_access_condition,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.due_on.is_not(None),
                    Task.due_on < today,
                )
            )
            if can_view_tasks
            else 0,
            "unassigned_tasks": db.scalar(
                select(func.count()).select_from(Task).where(
                    task_access_condition,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.assigned_to_id.is_(None),
                    Task.team_id.is_(None),
                )
            )
            if can_view_tasks
            else 0,
            "due_today_tasks": db.scalar(
                select(func.count()).select_from(Task).where(
                    task_access_condition,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.due_on == today,
                )
            )
            if can_view_tasks
            else 0,
            "unavailable_vehicles": db.scalar(
                select(func.count()).select_from(Vehicle).where(
                    Vehicle.active.is_(True),
                    Vehicle.operational_status.in_(unavailable_vehicle_statuses),
                )
            )
            if can_view_fleet
            else 0,
            "open_workshop": db.scalar(
                select(func.count()).select_from(WorkshopProcess).where(
                    WorkshopProcess.closed_at.is_(None),
                    WorkshopProcess.status.in_(open_workshop_statuses),
                )
            )
            if can_view_workshop
            else 0,
            "document_inbox": db.scalar(
                select(func.count()).select_from(Document).where(
                    Document.archived.is_(False),
                    Document.status.in_({"received", "unclassified"}),
                )
            )
            if can_view_documents
            else 0,
            "import_errors": db.scalar(select(func.count()).select_from(ImportError)) if can_view_imports else 0,
        }
        priority_tasks = (
            db.scalars(
                select(Task)
                .where(task_access_condition, Task.closed_at.is_(None), ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES))
                .order_by(Task.due_on.is_(None), Task.due_on, Task.priority.desc(), Task.id.desc())
                .limit(5)
            ).all()
            if can_view_tasks
            else []
        )
        critical_vehicles = (
            db.scalars(
                select(Vehicle)
                .where(
                    Vehicle.active.is_(True),
                    Vehicle.operational_status.in_(unavailable_vehicle_statuses),
                )
                .order_by(Vehicle.updated_at.desc(), Vehicle.id.desc())
                .limit(5)
            ).all()
            if can_view_fleet
            else []
        )
        recent_tasks = (
            db.scalars(
                select(Task)
                .where(task_access_condition)
                .order_by(Task.created_at.desc(), Task.id.desc())
                .limit(3)
            ).all()
            if can_view_tasks
            else []
        )
        recent_workshop = (
            db.scalars(select(WorkshopProcess).order_by(WorkshopProcess.created_at.desc(), WorkshopProcess.id.desc()).limit(3)).all()
            if can_view_workshop
            else []
        )
        recent_imports = (
            db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc()).limit(3)).all()
            if can_view_imports
            else []
        )
        recent_documents = (
            db.scalars(select(Document).order_by(Document.id.desc()).limit(3)).all()
            if can_view_documents
            else []
        )
        recent_activity = (
            [{"kind": "Tarefa", "title": item.title, "detail": item.status, "created_at": item.created_at} for item in recent_tasks]
            + [
                {"kind": "Oficina", "title": item.title, "detail": item.status, "created_at": item.created_at}
                for item in recent_workshop
            ]
            + [
                {
                    "kind": "Importação",
                    "title": f"{item.source_system} / {item.import_type}",
                    "detail": item.status,
                    "created_at": item.created_at,
                }
                for item in recent_imports
            ]
            + [
                {
                    "kind": "Documento",
                    "title": item.title or item.original_name,
                    "detail": item.status,
                    "created_at": item.created_at,
                }
                for item in recent_documents
            ]
        )
        recent_activity = sorted(
            recent_activity,
            key=lambda item: item["created_at"] or datetime.min.replace(tzinfo=UTC),
            reverse=True,
        )[:6]
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "user": user,
                "permissions": sorted(permission_codes),
                "authorized_units": sorted(get_user_authorized_unit_codes(db, user)),
                "dashboard_access": {
                    "tasks": can_view_tasks,
                    "fleet": can_view_fleet,
                    "workshop": can_view_workshop,
                    "documents": can_view_documents,
                    "imports": can_view_imports,
                },
                "metrics": metrics,
                "priority_tasks": priority_tasks,
                "critical_vehicles": critical_vehicles,
                "recent_activity": recent_activity,
                "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
                "priority_labels": PRIORITY_DISPLAY_LABELS,
                "vehicle_status_labels": {
                    "blocked": "Bloqueada",
                    "in_maintenance": "Em manutenção",
                    "in_preparation": "Em preparação",
                    "in_impro": "Em impro",
                },
            },
        )


def clean_experience_denied(request: Request) -> RedirectResponse | None:
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not has_any_web_permission(
        request,
        "dashboard.read",
        "vehicles.read",
        "workshop.read",
        "tasks.read",
        "management_center.read",
        "documents.read",
        "admin.manage",
    ):
        return RedirectResponse("/", status_code=303)
    return None


def clean_process_area_cards(db: Session) -> list[dict[str, object]]:
    return [
        {
            "code": "operational",
            "short": "OP",
            "label": "Operacional",
            "description": "Coordenação diária, tarefas guiadas e ocorrências rápidas.",
            "open": 0,
            "critical": 0,
            "models": ["Transferência crítica", "Verificação operacional"],
            "href": "#process-operational",
            "action": "Em preparação",
            "state": "Base limpa",
        },
        {
            "code": "fleet",
            "short": "FR",
            "label": "Frota",
            "description": "Ciclo técnico, documentação e decisões comerciais da viatura.",
            "open": 0,
            "critical": 0,
            "models": ["Auditoria técnica da viatura", "Preparação para venda", "Regularização documental da viatura"],
            "href": "/v2-clean/fleet",
            "action": "Abrir frota",
            "state": "Base limpa",
        },
        {
            "code": "management",
            "short": "GE",
            "label": "Gestão",
            "description": "Sinistros, fornecedores, discussões e validações de gestão.",
            "open": 0,
            "critical": 0,
            "models": ["Sinistro acompanhado", "Reclamação fornecedor", "Discussão Stellantis"],
            "href": "#process-management",
            "action": "Em preparação",
            "state": "Base limpa",
        },
        {
            "code": "administration",
            "short": "AD",
            "label": "Administração",
            "description": "Procedimentos, protocolos e organização interna.",
            "open": 0,
            "critical": 0,
            "models": ["Alteração de procedimento", "Revisão de protocolo", "Descritivo de função"],
            "href": "#process-administration",
            "action": "Em preparação",
            "state": "Base limpa",
        },
    ]


def clean_task_division_cards(db: Session) -> list[dict[str, object]]:
    cards: list[dict[str, object]] = []
    division_specs = [
        (
            "operational",
            "OP",
            "Operacional",
            "Pedidos, execucao diaria e ocorrencias rapidas.",
            ["Pedido", "Incidente", "Reclamacao"],
            "Base ativa",
        ),
        (
            "workshop",
            "OF",
            "Oficina",
            "Tarefas tecnicas e seguimento de apoio a oficina.",
            ["Diagnostico", "Reserva", "Apoio tecnico"],
            "Ligado ao modulo",
        ),
        (
            "management",
            "GE",
            "Gestão",
            "Discussões de negocio, fornecedores e decisões de supervisão.",
            ["Fornecedor", "Sinistro", "Discussao"],
            "A abrir",
        ),
        (
            "administration",
            "AD",
            "Administração",
            "Assuntos reservados, sensiveis ou internos.",
            ["Procedimento", "Acesso", "Validacao"],
            "Restrito",
        ),
    ]
    for workspace_code, short, label, description, chips, state in division_specs:
        cards.append(
            {
                "code": workspace_code,
                "short": short,
                "label": label,
                "description": description,
                "open": 0,
                "quick": 0,
                "due_today": 0,
                "chips": chips,
                "state": state,
                "href": None,
                "action": "Base limpa",
            }
        )
    return cards


@web_router.get("/new", response_class=HTMLResponse)
@web_router.get("/v2-clean", response_class=HTMLResponse)
def clean_experience_home(request: Request):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    with SessionLocal() as db:
        area_cards = clean_process_area_cards(db)
        quick_metrics = {
            "vehicles": count_rows(db, Vehicle),
            "workshop_alerts": area_cards[0]["critical"],
            "tasks": area_cards[0]["open"],
            "audits": area_cards[1]["open"],
        }
        return templates.TemplateResponse(
            request,
            "clean_home.html",
            {
                "area_cards": area_cards,
                "quick_metrics": quick_metrics,
            },
        )


@web_router.get("/v2-clean/processes", response_class=HTMLResponse)
def clean_process_center(request: Request):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    with SessionLocal() as db:
        area_cards = clean_process_area_cards(db)
        recent_audits: list[VehicleHistoryAudit] = []
        recent_management: list[ManagementProcess] = []
        process_metrics = {
            "areas": len(area_cards),
            "open": sum(int(area["open"]) for area in area_cards),
            "critical": sum(int(area["critical"]) for area in area_cards),
            "models": sum(len(area["models"]) for area in area_cards),
        }
        return templates.TemplateResponse(
            request,
            "clean_process_center.html",
            {
                "area_cards": area_cards,
                "recent_audits": recent_audits,
                "recent_management": recent_management,
                "process_metrics": process_metrics,
            },
        )


@web_router.get("/v2-clean/tasks", response_class=HTMLResponse)
def clean_tasks_center(request: Request):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    with SessionLocal() as db:
        task_divisions = clean_task_division_cards(db)
        urgent_tasks: list[dict[str, str | None]] = []
        recent_entries: list[dict[str, str | None]] = []
        task_metrics = {
            "divisions": len(task_divisions),
            "open": sum(int(item["open"]) for item in task_divisions),
            "quick": sum(int(item["quick"]) for item in task_divisions),
            "due_today": sum(int(item["due_today"]) for item in task_divisions),
        }
        return templates.TemplateResponse(
            request,
            "clean_task_center.html",
            {
                "task_divisions": task_divisions,
                "task_metrics": task_metrics,
                "urgent_tasks": urgent_tasks,
                "recent_entries": recent_entries,
            },
        )


@web_router.get("/v2-clean/admin", response_class=HTMLResponse)
def clean_admin_center(request: Request):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    return templates.TemplateResponse(
        request,
        "clean_module_placeholder.html",
        {
            "active_menu": "clean_admin",
            "eyebrow": "Nova experiência / administração",
            "title": "Administração",
            "description": "Zona reservada para regras, permissões e controlos próprios da nova experiência.",
            "panel_title": "Preparação segura",
            "cards": [
                {"code": "AC", "title": "Acessos", "text": "Perfis e permissões da v2-clean devem ser separados antes de uso real."},
                {"code": "RG", "title": "Regras", "text": "Aqui vamos consolidar configurações sem contaminar a base operacional antiga."},
                {"code": "LG", "title": "Auditoria", "text": "As ações sensíveis, como cancelar e reabrir processos, ficam melhor centralizadas aqui."},
            ],
            "next_title": "Sem risco operacional",
            "next_text": "Por agora deixamos a área preparada e visível, mas sem ligar nenhum fluxo crítico à administração antiga.",
            "actions": [
                {"href": "/v2-clean", "label": "Voltar ao início", "secondary": False},
            ],
        },
    )


@web_router.get("/v2-clean/workshop", response_class=HTMLResponse)
def clean_workshop_dashboard(request: Request, scope: str = "open"):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if scope not in {"open", "closed", "cancelled", "all"}:
        scope = "open"
    with SessionLocal() as db:
        v2_process_filter = WorkshopPhasedProcess.origin == "v2_clean"
        all_processes = (
            db.scalar(
                select(func.count())
                .select_from(WorkshopPhasedProcess)
                .where(v2_process_filter)
            )
            or 0
        )
        open_processes = (
            db.scalar(
                select(func.count())
                .select_from(WorkshopPhasedProcess)
                .where(v2_process_filter, WorkshopPhasedProcess.status.notin_(("closed", "cancelled")))
            )
            or 0
        )
        closed_processes = (
            db.scalar(
                select(func.count())
                .select_from(WorkshopPhasedProcess)
                .where(v2_process_filter, WorkshopPhasedProcess.status == "closed")
            )
            or 0
        )
        cancelled_processes = (
            db.scalar(
                select(func.count())
                .select_from(WorkshopPhasedProcess)
                .where(v2_process_filter, WorkshopPhasedProcess.status == "cancelled")
            )
            or 0
        )
        historical_processes = (
            db.scalar(
                select(func.count())
                .select_from(WorkshopPhasedProcess)
                .where(
                    v2_process_filter,
                    WorkshopPhasedProcess.creation_mode == "historical",
                    WorkshopPhasedProcess.status.notin_(("closed", "cancelled")),
                )
            )
            or 0
        )
        open_alerts = (
            db.scalar(
                select(func.count())
                .select_from(WorkshopPhasedProcessAlert)
                .join(WorkshopPhasedProcess, WorkshopPhasedProcess.id == WorkshopPhasedProcessAlert.process_id)
                .where(WorkshopPhasedProcessAlert.status == "open", v2_process_filter)
            )
            or 0
        )
        pending_validation = (
            db.scalar(
                select(func.count())
                .select_from(WorkshopPhasedProcess)
                .where(
                    v2_process_filter,
                    WorkshopPhasedProcess.current_phase_code.in_(("entrada", "validacao", "diagnostico")),
                    WorkshopPhasedProcess.status.notin_(("closed", "cancelled")),
                )
            )
            or 0
        )
        recent_query = select(WorkshopPhasedProcess).where(v2_process_filter)
        if scope == "open":
            recent_query = recent_query.where(WorkshopPhasedProcess.status.notin_(("closed", "cancelled")))
        elif scope == "closed":
            recent_query = recent_query.where(WorkshopPhasedProcess.status == "closed")
        elif scope == "cancelled":
            recent_query = recent_query.where(WorkshopPhasedProcess.status == "cancelled")
        recent_processes = db.scalars(
            recent_query
            .order_by(WorkshopPhasedProcess.updated_at.desc(), WorkshopPhasedProcess.id.desc())
            .limit(40)
        ).all()
        return templates.TemplateResponse(
            request,
            "clean_workshop_dashboard.html",
            {
                "metrics": {
                    "total": all_processes,
                    "open": open_processes,
                    "closed": closed_processes,
                    "cancelled": cancelled_processes,
                    "historical": historical_processes,
                    "alerts": open_alerts,
                    "pending_validation": pending_validation,
                },
                "recent_processes": recent_processes,
                "scope": scope,
            },
        )



CLEAN_WORKSHOP_CONTEXT = {
    "process_ref": "Novo processo",
    "plate": "Sem matrícula",
    "vehicle": "Selecionar viatura",
    "vin": "-",
    "fuel": "-",
    "entry_date": "-",
    "entry_km": "",
    "expected_exit": "-",
    "registration_date": "-",
    "purchase_date": "-",
    "real_start_date": "Por validar",
    "next_ipo": "-",
    "last_service_km": "-",
    "next_service_km": "-",
    "maintenance_status": "Por validar após seleção da viatura",
    "history_audit_status": "Auditoria histórico: por validar",
    "sale_status": "Venda: por validar",
    "brand_rule": "Por validar",
    "alerts": [],
}

CLEAN_WORKSHOP_STEP_DEFS = [
    {"key": "entrada", "number": 1, "label": "Entrada", "path": "/v2-clean/workshop-entry"},
    {"key": "validacao", "number": 2, "label": "Validação Administrativa", "path": "/v2-clean/workshop/validacao"},
    {"key": "diagnostico", "number": 3, "label": "Diagnóstico Técnico", "path": "/v2-clean/workshop/diagnostico"},
    {"key": "inspecao", "number": 4, "label": "Inspeção Técnica", "path": "/v2-clean/workshop/inspecao"},
    {"key": "auditoria", "number": 5, "label": "Auditoria e Validação", "path": "/v2-clean/workshop/auditoria"},
    {"key": "reparacao", "number": 6, "label": "Reparação", "path": "/v2-clean/workshop/reparacao"},
    {"key": "fecho", "number": 7, "label": "Validação e Fecho", "path": "/v2-clean/workshop/fecho"},
]

CLEAN_WORKSHOP_ENTRY_REASONS = [
    "Revisão / degradação óleo",
    "Verificação de rotina",
    "Pneus",
    "Travões",
    "Danos / sinistro",
    "Avaria",
    "IPO",
    "Outro",
]

CLEAN_WORKSHOP_ENTRY_PHYSICAL_CHECKS = [
    "visible_damage",
    "damage_matches_rentway",
    "dua_copy",
    "green_card_valid",
    "vv_device",
    "reflective_vest",
    "triangle",
    "spare_tyre",
    "jack",
    "inflation_kit",
]

CLEAN_WORKSHOP_ENTRY_MINIMUM_CHECKS = [
    "minimum_reason_selected",
    "minimum_km_confirmed",
    "minimum_dashboard_photo",
    "minimum_damage_photos",
]

CLEAN_WORKSHOP_PHASE_UPLOADS = {
    "inspecao": {
        "inspection_lights_photo": ("inspection_lights", "Foto inspeção - luzes"),
        "inspection_battery_photo": ("inspection_battery", "Foto inspeção - bateria"),
        "inspection_leaks_photo": ("inspection_leaks", "Foto inspeção - fugas"),
        "inspection_noises_photo": ("inspection_noises", "Foto inspeção - ruídos"),
        "inspection_road_test_photo": ("inspection_road_test", "Foto inspeção - teste de estrada"),
        "inspection_tyres_brakes_photo": ("inspection_tyres_brakes", "Foto inspeção - pneus e travões"),
    },
    "reparacao": {
        "repair_work_order_file": ("repair_work_order", "Folha de obra da reparação"),
        "repair_photos_files": ("repair_photos", "Fotos da reparação"),
        "repair_post_report_file": ("repair_post_report", "Relatório pós-intervenção"),
        "repair_campaign_proof_file": ("repair_campaign_proof", "Comprovativo de campanha"),
    },
    "fecho": {
        "closure_work_order_file": ("closure_work_order", "Folha de obra final"),
        "closure_invoice_file": ("closure_invoice", "Fatura da intervenção"),
        "closure_post_report_file": ("closure_post_report", "Relatório pós-intervenção final"),
        "closure_final_photos_files": ("closure_final_photos", "Fotos finais da viatura"),
    },
}

CLEAN_WORKSHOP_UPLOAD_STATUS_UPDATES = {
    "repair_work_order_file": ("repair_fo_status", "Recebida"),
    "repair_photos_files": ("repair_photos_status", "Recebidas"),
    "repair_post_report_file": ("repair_post_report_status", "Recebido"),
    "repair_campaign_proof_file": ("repair_campaign_proof_status", "Recebido"),
    "closure_work_order_file": ("closure_work_order_status", "Recebida"),
    "closure_invoice_file": ("closure_invoice_status", "Recebida"),
    "closure_post_report_file": ("closure_post_report_status", "Recebido"),
    "closure_final_photos_files": ("closure_final_photos_status", "Recebidas"),
}

CLEAN_WORKSHOP_PHASE_ALIASES = {
    "decisao": "auditoria",
    "execucao": "reparacao",
}

CLEAN_WORKSHOP_SUBSTEP_FLOW = {
    "validacao": ("prerequisitos", "pedido", "orientacao"),
    "diagnostico": ("relatorios", "leituras", "problemas", "saida-diagnostico"),
    "inspecao": ("checklist", "pneus-travoes", "oleo-niveis", "saida-inspecao"),
    "auditoria": ("evidencias", "coerencia", "problemas-auditoria", "decisao", "saida-auditoria"),
    "reparacao": ("ordem-reparacao", "execucao", "evidencias-reparacao", "desvios", "saida-reparacao"),
    "fecho": ("validacao-final", "documentos-fecho", "historico-fecho", "pendencias-fecho", "encerramento"),
}

CLEAN_WORKSHOP_PHASES = {
    "validacao": {
        "step": 2,
        "title": "Validação Administrativa",
        "subtitle": "Confirmar contexto administrativo, marca, histórico e coerência antes do diagnóstico técnico.",
        "primary_action": "Avançar para Diagnóstico Técnico",
        "sections": [],
    },
    "diagnostico": {
        "step": 3,
        "title": "Diagnóstico Técnico",
        "subtitle": "Carregar relatórios, extrair leituras e validar dados técnicos por relatório.",
        "primary_action": "Avançar para Inspeção Técnica",
        "sections": [
            {
                "eyebrow": "Relatórios técnicos",
                "title": "Documentos e extração",
                "report_cards": [
                    "Lubrificação motor",
                    "Informações manutenção",
                    "Programação manutenção",
                    "Telecarregamento",
                    "Leitura defeitos",
                    "Teste global",
                ],
            },
            {
                "eyebrow": "Dados extraídos",
                "title": "Leituras por validar",
                "table": ["Campo", "Valor extraído", "Valor validado", "Estado", "Observação"],
            },
            {
                "eyebrow": "Decisão da leitura",
                "title": "Problemas e ação seguinte",
                "fields": [
                    "Degradação óleo",
                    "Falta telecarregamento",
                    "BSI sem registo",
                    "Intervalo incoerente",
                    "Ação seguinte",
                    "Nota de validação",
                ],
            },
            {
                "eyebrow": "Comparação",
                "title": "Histórico comparativo",
                "large": True,
                "fields": ["Relatórios anteriores do mesmo tipo", "Diferenças relevantes", "Evidência objetiva"],
            },
        ],
    },
    "inspecao": {
        "step": 4,
        "title": "Inspeção Técnica",
        "subtitle": "Confirmar pontos físicos/técnicos observados e recolher evidências.",
        "primary_action": "Avançar para Auditoria e Validação",
        "sections": [
            {
                "eyebrow": "Checklist técnica",
                "title": "Verificações principais",
                "check_cards": [
                    "Níveis",
                    "Pneus",
                    "Travões",
                    "Luzes",
                    "Bateria",
                    "Fugas visíveis",
                    "Ruídos anormais",
                    "Estado visual técnico",
                    "Teste de estrada",
                ],
            },
            {
                "eyebrow": "Registo de incidência",
                "title": "Quando algo não está conforme",
                "large": True,
                "fields": ["Estado", "Evidência", "Observação", "Criar tarefa", "Possível cobrança cliente"],
            },
        ],
    },
    "auditoria": {
        "step": 5,
        "title": "Auditoria e Validação",
        "subtitle": "Cruzar diagnóstico, histórico e inspeção para decidir a intervenção e pendências.",
        "primary_action": "Avançar para Reparação",
        "sections": [
            {
                "eyebrow": "Auditoria técnica",
                "title": "O que ficou provado",
                "fields": ["Serviço confirmado", "BSI vs faturas", "Telecarregamento", "Conclusão", "Bloqueia reparação?"],
            },
            {
                "eyebrow": "Decisão operacional",
                "title": "Intervenção e aprovação",
                "fields": ["Intervenção", "Orçamento necessário?", "Estado autorização", "Valor estimado", "Próxima ação"],
            },
            {
                "eyebrow": "Problemas / tarefas",
                "title": "Pendências abertas",
                "table": ["Problema", "Estado", "Prioridade", "Responsável"],
            },
            {
                "eyebrow": "Saída da fase",
                "title": "Condições para avançar",
                "large": True,
                "fields": ["Validação concluída?", "Motivo da reserva", "Auditoria histórico", "Campanhas por executar"],
            },
        ],
    },
    "reparacao": {
        "step": 6,
        "title": "Reparação",
        "subtitle": "Acompanhar execução, desvios, evidências e relatórios pós-intervenção.",
        "primary_action": "Avançar para Validação e Fecho",
        "sections": [
            {
                "eyebrow": "Execução",
                "title": "Trabalho em curso",
                "fields": ["Tipo execução", "Estado", "Previsão conclusão", "Serviços executados", "Responsável/oficina"],
            },
            {
                "eyebrow": "Evidências",
                "title": "Documentar intervenção",
                "uploads": ["Fotos reparação", "Folha de obra", "Relatório pós-intervenção", "Comprovativos"],
                "fields": ["Peças/serviços aplicados", "Observação"],
            },
            {
                "eyebrow": "Desvios e bloqueios",
                "title": "Alterações ao previsto",
                "large": True,
                "fields": ["Alteração ao previsto?", "Novo orçamento?", "Bloqueio atual", "Pronto para fecho?"],
            },
        ],
    },
    "fecho": {
        "step": 7,
        "title": "Validação e Fecho",
        "subtitle": "Confirmar resolução, documentos finais, atualização de histórico e pendências.",
        "primary_action": "Fechar processo",
        "sections": [
            {
                "eyebrow": "Validação final",
                "title": "Estado de saída",
                "fields": ["Viatura pronta?", "KM saída", "Foto quadrante saída", "Teste final", "Pode circular?", "Regressar à frota?"],
                "uploads": ["Foto quadrante saída", "Fotos finais"],
            },
            {
                "eyebrow": "Documentos e histórico",
                "title": "Fechar sem perder rasto",
                "fields": ["Folha obra fechada?", "Fatura esperada?", "Relatórios finais", "Histórico atualizado?", "Problemas abertos", "Pendências"],
            },
            {
                "eyebrow": "Resultado final",
                "title": "Decisão de fecho",
                "large": True,
                "fields": ["Resultado", "Observação final", "Fechar com pendências", "Responsável pela pendência", "Prazo"],
            },
        ],
    },
}


STELLANTIS_BRANDS = {"CITROEN", "CITROËN", "PEUGEOT", "DS", "OPEL", "FIAT", "JEEP"}


def clean_date(value: str | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except ValueError:
        return str(value)[:10]


def clean_km(value: str | None) -> str:
    if not value:
        return "-"
    text = str(value).strip()
    try:
        return f"{int(float(text.replace(' ', '').replace(',', '.'))):,}".replace(",", " ")
    except ValueError:
        return text


def parse_int_from_text(value: str | None) -> int | None:
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", str(value))
    return int(digits) if digits else None


def clean_workshop_query_suffix(
    process_id: int | None = None,
    vehicle_id: int | None = None,
    plate: str | None = None,
    historical: bool = False,
    new_entry: bool = False,
) -> str:
    query: dict[str, str] = {}
    if process_id:
        query["process_id"] = str(process_id)
    elif vehicle_id:
        query["vehicle_id"] = str(vehicle_id)
    elif plate:
        query["plate"] = plate
    if historical:
        query["historical"] = "1"
    if new_entry:
        query["new"] = "1"
    return f"?{urlencode(query)}" if query else ""


def clean_workshop_process_reference(process: WorkshopPhasedProcess) -> str:
    reference_date = process.received_at or process.created_at or datetime.now(UTC)
    return f"OFI-{reference_date.year}-{process.id:06d}"


def clean_workshop_process_url(process: WorkshopPhasedProcess) -> str:
    phase = process.current_phase_code or "entrada"
    if phase == "entrada":
        return f"/v2-clean/workshop-entry?process_id={process.id}"
    return f"{clean_workshop_phase_path(phase)}?process_id={process.id}"


def clean_workshop_admin_context(
    db: Session,
    request: Request,
    process: WorkshopPhasedProcess | None,
) -> dict[str, object]:
    user_id = get_web_user_id(request)
    current_user = db.get(User, user_id) if user_id else None
    metadata = dict(process.metadata_json or {}) if process and isinstance(process.metadata_json, dict) else {}
    cancellation = metadata.get("cancellation") if isinstance(metadata.get("cancellation"), dict) else {}
    open_task_count = 0
    if process:
        open_task_count = (
            db.scalar(
                select(func.count())
                .select_from(Task)
                .where(
                    Task.entity_type == "workshop_phased_process",
                    Task.entity_id == str(process.id),
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES),
                )
            )
            or 0
        )
    return {
        "can_manage": can_manage_admin(db, current_user),
        "is_cancelled": bool(process and process.status == "cancelled"),
        "is_closed": bool(process and process.status == "closed"),
        "cancellation": cancellation,
        "open_task_count": int(open_task_count),
    }


def clean_workshop_process_is_readonly(process: WorkshopPhasedProcess | None) -> bool:
    return bool(process and process.status in {"closed", "cancelled"})


def clean_workshop_find_vehicle(
    db: Session,
    *,
    vehicle_id: int | None = None,
    plate: str | None = None,
) -> Vehicle | None:
    if vehicle_id:
        return db.get(Vehicle, vehicle_id)
    if plate:
        return db.scalar(select(Vehicle).where(Vehicle.plate == normalize_identifier(plate)))
    return None


def clean_workshop_create_process(
    db: Session,
    *,
    request: Request,
    vehicle_id: int | None = None,
    plate: str | None = None,
    historical: bool = False,
) -> WorkshopPhasedProcess:
    user_id = get_web_user_id(request)
    vehicle = clean_workshop_find_vehicle(db, vehicle_id=vehicle_id, plate=plate)
    plate_snapshot = vehicle.plate if vehicle and vehicle.plate else normalize_identifier(plate) if plate else None
    display_plate = plate_snapshot or "Sem matrícula"
    now = datetime.now(UTC)
    process = WorkshopPhasedProcess(
        process_type="workshop",
        title=f"Oficina {display_plate}",
        creation_mode="historical" if historical else "operational",
        status="open",
        vehicle_id=vehicle.id if vehicle else None,
        plate_snapshot=plate_snapshot,
        current_phase_code="entrada",
        priority="normal",
        origin="v2_clean",
        origin_detail="Criado na experiência v2-clean.",
        initial_km=None,
        initial_observation="Processo histórico criado para reconstrução." if historical else "Entrada criada na experiência v2-clean.",
        responsible_user_id=user_id,
        created_by_id=user_id,
        received_at=now,
        metadata_json={
            "v2_clean": True,
            "historical": historical,
            "source": "v2_clean_workshop_entry",
        },
    )
    db.add(process)
    db.flush()
    process.title = f"{clean_workshop_process_reference(process)} · {display_plate}"
    for index, step in enumerate(CLEAN_WORKSHOP_STEP_DEFS, start=1):
        db.add(
            WorkshopPhasedProcessPhase(
                process_id=process.id,
                phase_code=str(step["key"]),
                name=str(step["label"]),
                status="pending_review" if step["key"] == "entrada" else "not_started",
                sort_order=index,
                started_at=now if step["key"] == "entrada" else None,
                data_json={},
            )
        )
    db.commit()
    db.refresh(process)
    return process


def clean_workshop_context_for_process(db: Session, process: WorkshopPhasedProcess) -> dict[str, object]:
    context = clean_workshop_vehicle_context(
        db,
        vehicle_id=process.vehicle_id,
        plate=process.plate_snapshot,
    )
    context["process_ref"] = clean_workshop_process_reference(process)
    context["process_id"] = process.id
    return context


def clean_workshop_get_phase(
    db: Session,
    process_id: int,
    phase_code: str,
) -> WorkshopPhasedProcessPhase | None:
    return db.scalar(
        select(WorkshopPhasedProcessPhase).where(
            WorkshopPhasedProcessPhase.process_id == process_id,
            WorkshopPhasedProcessPhase.phase_code == phase_code,
        )
    )


async def clean_workshop_store_entry_uploads(
    process_id: int,
    form,
) -> list[dict[str, str]]:
    field_map = {
        "dashboard_photo": ("dashboard", "Foto do quadrante"),
        "dashboard_photo_camera": ("dashboard", "Foto do quadrante"),
        "vehicle_front_photo": ("front", "Foto frente"),
        "vehicle_front_photo_camera": ("front", "Foto frente"),
        "vehicle_rear_photo": ("rear", "Foto traseira"),
        "vehicle_rear_photo_camera": ("rear", "Foto traseira"),
        "vehicle_left_photo": ("left", "Foto lateral esquerda"),
        "vehicle_left_photo_camera": ("left", "Foto lateral esquerda"),
        "vehicle_right_photo": ("right", "Foto lateral direita"),
        "vehicle_right_photo_camera": ("right", "Foto lateral direita"),
        "entry_photos": ("support", "Foto de apoio"),
        "entry_photos_camera": ("support", "Foto de apoio"),
    }
    stored: list[dict[str, str]] = []
    upload_root = APP_PROJECT_ROOT / "uploads" / "workshop_entry" / str(process_id)
    for form_field, (slot, label) in field_map.items():
        for upload in form.getlist(form_field):
            if not hasattr(upload, "filename") or not hasattr(upload, "read") or not upload.filename:
                continue
            content = await upload.read()
            if not content:
                continue
            original_name = Path(upload.filename).name
            digest = hashlib.sha256(content).hexdigest()
            suffix = Path(original_name).suffix or ".bin"
            upload_root.mkdir(parents=True, exist_ok=True)
            stored_name = f"{slot}_{digest[:12]}{suffix}"
            stored_path = upload_root / stored_name
            if not stored_path.exists():
                stored_path.write_bytes(content)
            stored.append(
                {
                    "field": form_field,
                    "slot": slot,
                    "label": label,
                    "original_name": original_name,
                    "stored_name": stored_name,
                    "path": str(stored_path),
                    "sha256": digest,
                }
            )
    return stored


async def clean_workshop_store_phase_uploads(
    db: Session,
    process: WorkshopPhasedProcess,
    phase: str,
    form,
    user_id: int | None,
) -> list[dict[str, object]]:
    field_map = CLEAN_WORKSHOP_PHASE_UPLOADS.get(phase, {})
    if not field_map:
        return []

    plate_value = normalize_identifier(str(process.plate_snapshot or ""))
    plate_folder = re.sub(r"[^A-Z0-9_-]+", "_", plate_value or f"PROCESSO_{process.id}")
    upload_root = APP_PROJECT_ROOT / "uploads" / "vehicle_documents" / plate_folder / phase
    stored: list[dict[str, object]] = []

    for form_field, (category, label) in field_map.items():
        for upload in form.getlist(form_field):
            if not hasattr(upload, "filename") or not hasattr(upload, "read") or not upload.filename:
                continue
            content = await upload.read()
            if not content:
                continue
            original_name = Path(upload.filename).name
            digest = hashlib.sha256(content).hexdigest()
            suffix = Path(original_name).suffix or ".bin"
            upload_root.mkdir(parents=True, exist_ok=True)
            stored_name = f"{category}_{digest[:12]}{suffix}"
            stored_path = upload_root / stored_name
            if not stored_path.exists():
                stored_path.write_bytes(content)

            document = db.scalar(select(Document).where(Document.storage_path == str(stored_path)))
            if document is None:
                document = Document(
                    title=f"{label} - {plate_value or process.id}",
                    document_type=category,
                    classification="workshop",
                    source="workshop_v2_clean",
                    entry_channel="upload",
                    source_subject=label,
                    original_name=original_name,
                    file_name=stored_name,
                    file_type=suffix.lstrip(".") or None,
                    file_size=len(content),
                    storage_provider="local",
                    storage_path=str(stored_path),
                    storage_key=digest,
                    file_hash=digest,
                    folder_path=suggest_workshop_process_document_folder(process, vehicle, "03_Fotos_Evidencias"),
                    status="received",
                    vehicle_id=process.vehicle_id,
                    plate=process.plate_snapshot,
                    uploaded_by_id=user_id,
                )
                db.add(document)
                db.flush()

            existing_link = db.scalar(
                select(DocumentLink).where(
                    DocumentLink.document_id == document.id,
                    DocumentLink.entity_type == "workshop_phased_process",
                    DocumentLink.entity_id == str(process.id),
                    DocumentLink.category == category,
                )
            )
            if existing_link is None:
                db.add(
                    DocumentLink(
                        document_id=document.id,
                        entity_type="workshop_phased_process",
                        entity_id=str(process.id),
                        category=category,
                    )
                )
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="document.workshop_v2_phase_upload",
                    new_value=f"process={process.id}; phase={phase}; category={category}",
                    user_id=user_id,
                )
            )
            stored.append(
                {
                    "field": form_field,
                    "category": category,
                    "label": label,
                    "original_name": original_name,
                    "stored_name": stored_name,
                    "path": str(stored_path),
                    "sha256": digest,
                    "document_id": document.id,
                }
            )
    return stored


@web_router.get("/v2-clean/workshop-entry/{process_id}/uploads/{stored_name}")
def clean_workshop_entry_upload_file(request: Request, process_id: int, stored_name: str):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    safe_name = Path(stored_name).name
    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        entry_phase = clean_workshop_get_phase(db, process.id, "entrada")
        entry_data = entry_phase.data_json if entry_phase and isinstance(entry_phase.data_json, dict) else {}
        uploads = entry_data.get("uploads")
        if not isinstance(uploads, list):
            uploads = []
        upload = next(
            (
                item
                for item in uploads
                if isinstance(item, dict) and Path(str(item.get("stored_name") or "")).name == safe_name
            ),
            None,
        )
        if not upload:
            return RedirectResponse(f"/v2-clean/workshop-entry?process_id={process.id}&file_missing=1", status_code=303)
        original_name = str(upload.get("original_name") or safe_name)
        raw_path = Path(str(upload.get("path") or ""))

    file_path = raw_path if raw_path.is_absolute() else APP_PROJECT_ROOT / raw_path
    root_path = (APP_PROJECT_ROOT / "uploads" / "workshop_entry" / str(process_id)).resolve()
    try:
        resolved_path = file_path.resolve()
        resolved_path.relative_to(root_path)
    except (OSError, ValueError):
        return RedirectResponse(f"/v2-clean/workshop-entry?process_id={process_id}&file_missing=1", status_code=303)
    if not resolved_path.exists() or not resolved_path.is_file():
        return RedirectResponse(f"/v2-clean/workshop-entry?process_id={process_id}&file_missing=1", status_code=303)
    return FileResponse(resolved_path, filename=original_name)


@web_router.get("/v2-clean/workshop/{process_id}/phase-uploads/{stored_name}")
def clean_workshop_phase_upload_file(request: Request, process_id: int, stored_name: str):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    safe_name = Path(stored_name).name
    upload: dict[str, object] | None = None
    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        phase_rows = db.scalars(
            select(WorkshopPhasedProcessPhase).where(
                WorkshopPhasedProcessPhase.process_id == process.id
            )
        ).all()
        for phase_row in phase_rows:
            phase_data = phase_row.data_json if isinstance(phase_row.data_json, dict) else {}
            uploads = phase_data.get("uploads")
            if not isinstance(uploads, list):
                continue
            upload = next(
                (
                    item
                    for item in uploads
                    if isinstance(item, dict)
                    and Path(str(item.get("stored_name") or "")).name == safe_name
                ),
                None,
            )
            if upload:
                break

    if not upload:
        return RedirectResponse(f"/v2-clean/workshop?file_missing=1", status_code=303)
    raw_path = Path(str(upload.get("path") or ""))
    file_path = raw_path if raw_path.is_absolute() else APP_PROJECT_ROOT / raw_path
    root_path = (APP_PROJECT_ROOT / "uploads" / "vehicle_documents").resolve()
    try:
        resolved_path = file_path.resolve()
        resolved_path.relative_to(root_path)
    except (OSError, ValueError):
        return RedirectResponse("/v2-clean/workshop?file_missing=1", status_code=303)
    if not resolved_path.exists() or not resolved_path.is_file():
        return RedirectResponse("/v2-clean/workshop?file_missing=1", status_code=303)
    original_name = str(upload.get("original_name") or safe_name)
    return FileResponse(resolved_path, filename=original_name)


def clean_workshop_entry_substep_status(entry_data: dict[str, object]) -> dict[str, str]:
    if not entry_data:
        return {"motivo": "Obrigatório", "danos": "Por validar", "saida": "Rascunho"}

    has_motivo = any(
        [
            entry_data.get("entry_reasons"),
            str(entry_data.get("short_description") or "").strip(),
            str(entry_data.get("requested_service") or "").strip(),
            str(entry_data.get("entry_km") or "").strip(),
        ]
    )
    physical_checks = entry_data.get("physical_checks")
    has_physical_checks = False
    if isinstance(physical_checks, dict):
        has_physical_checks = any(str(value) != "not_checked" for value in physical_checks.values())
    has_danos = has_physical_checks or bool(str(entry_data.get("physical_check_note") or "").strip())

    minimum_checks = entry_data.get("minimum_checks")
    has_minimum_checks = False
    if isinstance(minimum_checks, dict):
        has_minimum_checks = any(str(value) != "not_checked" for value in minimum_checks.values())
    has_saida = has_minimum_checks or bool(
        str(entry_data.get("expected_exit") or "").strip()
        or str(entry_data.get("validation_notes") or "").strip()
    )

    return {
        "motivo": "Guardado" if has_motivo else "Obrigatório",
        "danos": "Guardado" if has_danos else "Por validar",
        "saida": "Guardado" if has_saida else "Rascunho",
    }


def clean_workshop_steps(query_suffix: str = "") -> list[dict[str, str | int]]:
    return [
        {
            "key": step["key"],
            "number": step["number"],
            "label": step["label"],
            "href": f"{step['path']}{query_suffix}",
        }
        for step in CLEAN_WORKSHOP_STEP_DEFS
    ]


def clean_workshop_phase_nav(active_key: str, query_suffix: str = "") -> dict[str, str | None]:
    step_index = next(
        (index for index, step in enumerate(CLEAN_WORKSHOP_STEP_DEFS) if step["key"] == active_key),
        None,
    )
    if step_index is None:
        return {"previous_phase_url": None, "next_phase_url": None}
    previous_phase_url = (
        f"{CLEAN_WORKSHOP_STEP_DEFS[step_index - 1]['path']}{query_suffix}" if step_index > 0 else None
    )
    next_phase_url = (
        f"{CLEAN_WORKSHOP_STEP_DEFS[step_index + 1]['path']}{query_suffix}"
        if step_index < len(CLEAN_WORKSHOP_STEP_DEFS) - 1
        else None
    )
    return {"previous_phase_url": previous_phase_url, "next_phase_url": next_phase_url}


def clean_workshop_next_phase_key(active_key: str) -> str | None:
    step_index = next(
        (index for index, step in enumerate(CLEAN_WORKSHOP_STEP_DEFS) if step["key"] == active_key),
        None,
    )
    if step_index is None or step_index >= len(CLEAN_WORKSHOP_STEP_DEFS) - 1:
        return None
    return str(CLEAN_WORKSHOP_STEP_DEFS[step_index + 1]["key"])


def clean_workshop_substeps(phase_key: str) -> tuple[str, ...]:
    return tuple(CLEAN_WORKSHOP_SUBSTEP_FLOW.get(phase_key, ()))


def clean_workshop_next_substep_key(phase_key: str, current_substep: str) -> str | None:
    substeps = clean_workshop_substeps(phase_key)
    if not substeps:
        return None
    try:
        step_index = substeps.index(current_substep)
    except ValueError:
        return substeps[0]
    if step_index >= len(substeps) - 1:
        return None
    return substeps[step_index + 1]


def clean_workshop_phase_path(phase_key: str) -> str:
    step = next((item for item in CLEAN_WORKSHOP_STEP_DEFS if item["key"] == phase_key), None)
    return str(step["path"]) if step else "/v2-clean/workshop-entry"


CLEAN_WORKSHOP_PHASE_ERROR_MESSAGES = {
    "validation_incomplete": "Conclui a decisão dos serviços e fecha a validação administrativa antes de avançar.",
    "reports_pending": "Existem relatórios por validar. Valida-os ou fecha o diagnóstico com reserva e motivo.",
    "inspection_incomplete": "Conclui a checklist técnica ou fecha a inspeção com reserva e respetivo motivo.",
    "audit_incomplete": "Regista a decisão da auditoria e fecha a fase antes de avançar.",
    "repair_incomplete": "A reparação deve estar concluída ou fechada com reserva devidamente justificada.",
    "closure_incomplete": "Confirma as condições mínimas de fecho e o tratamento das pendências.",
}


def clean_workshop_phase_advance_error(
    phase: str,
    snapshot: dict[str, object],
    reports: list[WorkshopPhasedTechnicalReport] | None = None,
) -> str | None:
    if phase == "validacao":
        decisions = clean_form_values(snapshot, "service_decision")
        closed = clean_form_value(snapshot, "validation_closed", "Por confirmar")
        if not decisions or any(value in {"", "Por decidir"} for value in decisions):
            return "validation_incomplete"
        if closed not in {"Sim", "Com reservas"}:
            return "validation_incomplete"
        if closed == "Com reservas" and not clean_form_value(snapshot, "validation_reserve_reason").strip():
            return "validation_incomplete"
        return None

    if phase == "diagnostico":
        closed = clean_form_value(snapshot, "diagnostic_closed", "Por confirmar")
        pending_reports = [
            report
            for report in (reports or [])
            if report.status not in {"voided", "superseded"}
            and not clean_workshop_report_is_complete(report)
        ]
        if closed not in {"Sim", "Com reservas"}:
            return "reports_pending"
        if pending_reports and (
            closed != "Com reservas"
            or not clean_form_value(snapshot, "diagnostic_reserve_reason").strip()
        ):
            return "reports_pending"
        return None

    if phase == "inspecao":
        closed = clean_form_value(snapshot, "inspection_closed", "Por confirmar")
        checklist_values = [
            clean_form_value(snapshot, key, "review")
            for key in (
                "inspection_check_lights",
                "inspection_check_battery",
                "inspection_check_leaks",
                "inspection_check_noises",
                "inspection_check_road_test",
            )
        ]
        checklist_pending = any(value in {"", "review"} for value in checklist_values)
        if closed not in {"Sim", "Com reservas"}:
            return "inspection_incomplete"
        if checklist_pending and (
            closed != "Com reservas"
            or not clean_form_value(snapshot, "inspection_reserve_reason").strip()
        ):
            return "inspection_incomplete"
        return None

    if phase == "auditoria":
        closed = clean_form_value(snapshot, "audit_closed", "Por confirmar")
        decision = clean_form_value(snapshot, "audit_decision_main", "Por decidir")
        if decision in {"", "Por decidir"}:
            return "audit_incomplete"
        if closed not in {"Sim", "Com reservas"}:
            return "audit_incomplete"
        if closed == "Com reservas" and not clean_form_value(snapshot, "audit_reserve_reason").strip():
            return "audit_incomplete"
        return None

    if phase == "reparacao":
        closed = clean_form_value(snapshot, "repair_closed", "Por confirmar")
        execution_status = clean_form_value(snapshot, "repair_execution_status")
        if closed not in {"Sim", "Com reservas"}:
            return "repair_incomplete"
        if closed == "Sim" and execution_status != "Concluída":
            return "repair_incomplete"
        if closed == "Com reservas" and not clean_form_value(snapshot, "repair_reserve_reason").strip():
            return "repair_incomplete"
        return None

    if phase == "fecho":
        result = clean_form_value(snapshot, "closure_result", "Não fechar")
        required_checks = ("closure_vehicle_validated", "closure_history_updated")
        if result == "Não fechar" or any(clean_form_value(snapshot, key) != "yes" for key in required_checks):
            return "closure_incomplete"
        fleet_state_defined = clean_form_value(snapshot, "closure_fleet_state_defined") == "yes" or (
            clean_form_value(snapshot, "closure_back_to_fleet") == "yes"
            and clean_form_value(snapshot, "closure_final_status").strip() not in {"", "Por confirmar"}
        )
        if not fleet_state_defined:
            return "closure_incomplete"
        if result != "Fechado com reserva" and clean_form_value(snapshot, "closure_min_docs_attached") != "yes":
            return "closure_incomplete"
        if result == "Fechado com reserva":
            pending_description = clean_form_value(snapshot, "closure_pending_description").strip()
            pending_assigned = clean_form_value(snapshot, "closure_pending_assigned") == "yes" or (
                bool(clean_form_value(snapshot, "closure_pending_owner").strip()) and bool(pending_description)
            )
            if not pending_assigned or not pending_description:
                return "closure_incomplete"
    return None


def clean_form_value(snapshot: dict[str, object], key: str, default: str = "") -> str:
    value = snapshot.get(key)
    if isinstance(value, list):
        return str(value[0]) if value else default
    if value is None:
        return default
    return str(value)


def clean_form_values(snapshot: dict[str, object], key: str) -> list[str]:
    value = snapshot.get(key)
    if isinstance(value, list):
        return [str(item) for item in value]
    if value is None or value == "":
        return []
    return [str(value)]


def clean_workshop_saved_substeps(phase_data: dict[str, object]) -> set[str]:
    raw_value = phase_data.get("saved_substeps")
    if not isinstance(raw_value, list):
        return set()
    return {str(item) for item in raw_value if str(item).strip()}


def clean_workshop_substep_is_saved(
    saved_substeps: set[str] | None,
    substep: str,
    *,
    legacy_has_data: bool = False,
) -> bool:
    saved = saved_substeps or set()
    return substep in saved or (not saved and legacy_has_data)


def clean_workshop_validation_rows(
    snapshot: dict[str, object],
    entry_snapshot: dict[str, object] | None = None,
) -> list[dict[str, str]]:
    entry_reasons = [
        item.strip()
        for item in clean_form_values(entry_snapshot or {}, "entry_reasons")
        if item.strip()
    ]
    fields = [
        "service_type",
        "service_already_done",
        "previous_service_date",
        "previous_service_km",
        "previous_service_supplier",
        "previous_service_document",
        "service_decision",
    ]
    values = {field: clean_form_values(snapshot, field) for field in fields}

    requested_services = entry_reasons[:]
    value_lengths = [len(items) for items in values.values()]
    row_count = max([len(requested_services), *value_lengths, 1])
    rows: list[dict[str, str]] = []

    def build_row(index: int, default_service: str = "Outro") -> dict[str, str]:
        row = {
            "service_type": values["service_type"][index]
            if index < len(values["service_type"])
            else default_service,
            "service_already_done": values["service_already_done"][index]
            if index < len(values["service_already_done"])
            else "Por confirmar",
            "previous_service_date": values["previous_service_date"][index]
            if index < len(values["previous_service_date"])
            else "",
            "previous_service_km": values["previous_service_km"][index]
            if index < len(values["previous_service_km"])
            else "",
            "previous_service_supplier": values["previous_service_supplier"][index]
            if index < len(values["previous_service_supplier"])
            else "",
            "previous_service_document": values["previous_service_document"][index]
            if index < len(values["previous_service_document"])
            else "",
            "service_decision": values["service_decision"][index]
            if index < len(values["service_decision"])
            else "Por decidir",
        }
        return row

    def has_non_default_data(row: dict[str, str]) -> bool:
        return any(
            [
                row["service_already_done"] != "Por confirmar",
                row["previous_service_date"],
                row["previous_service_km"],
                row["previous_service_supplier"],
                row["previous_service_document"],
                row["service_decision"] != "Por decidir",
            ]
        )

    if requested_services:
        for index, requested_service in enumerate(requested_services):
            rows.append(build_row(index, requested_service))
        return rows

    for index in range(row_count):
        row = build_row(index, "Outro")
        has_non_default_data = any(
            [
                row["service_already_done"] != "Por confirmar",
                row["previous_service_date"],
                row["previous_service_km"],
                row["previous_service_supplier"],
                row["previous_service_document"],
                row["service_decision"] != "Por decidir",
            ]
        )
        if has_non_default_data or index == 0:
            rows.append(row)
    return rows


def clean_workshop_validation_substep_status(
    snapshot: dict[str, object],
    *,
    phase_saved: bool = False,
    prerequisite_warning_count: int = 0,
    saved_substeps: set[str] | None = None,
) -> dict[str, str]:
    has_service_data = any(
        [
            clean_form_values(snapshot, "service_type"),
            clean_form_values(snapshot, "previous_service_date"),
            clean_form_values(snapshot, "previous_service_km"),
            clean_form_values(snapshot, "previous_service_supplier"),
            clean_form_values(snapshot, "previous_service_document"),
            clean_form_value(snapshot, "validation_observation").strip(),
        ]
    )
    service_decisions = clean_form_values(snapshot, "service_decision")
    has_decision = any(value and value != "Por decidir" for value in service_decisions)
    already_done_values = clean_form_values(snapshot, "service_already_done")
    has_history_answer = any(value and value != "Por confirmar" for value in already_done_values)
    orientation_has_data = any(
        [
            clean_form_value(snapshot, "validation_closed").strip(),
            clean_form_value(snapshot, "validation_priority").strip(),
            clean_form_value(snapshot, "validation_diagnostic_focus").strip(),
            clean_form_value(snapshot, "validation_reserve_reason").strip(),
        ]
    )
    return {
        "prerequisitos": "OK" if prerequisite_warning_count == 0 else f"{prerequisite_warning_count} avisos",
        "pedido": "Guardado"
        if clean_workshop_substep_is_saved(
            saved_substeps,
            "pedido",
            legacy_has_data=has_decision or has_history_answer or has_service_data,
        )
        else "Por validar",
        "orientacao": "Guardado"
        if clean_workshop_substep_is_saved(
            saved_substeps,
            "orientacao",
            legacy_has_data=orientation_has_data,
        )
        else "Rascunho",
    }


def clean_workshop_validation_prerequisites(
    db: Session,
    process: WorkshopPhasedProcess | None,
    vehicle_context: dict[str, object],
) -> list[dict[str, str | None]]:
    vehicle_id = process.vehicle_id if process else None
    plate = normalize_identifier(str(process.plate_snapshot or "")) if process and process.plate_snapshot else ""
    vehicle_href = f"/v2-clean/fleet/{vehicle_id}" if vehicle_id else None
    process_return_url = f"/v2-clean/workshop/validacao?process_id={process.id}" if process else "/v2-clean/workshop"
    plan_create_href = f"/v2-clean/fleet/{vehicle_id}/documents?doc_group=plans" if vehicle_id else None

    plan_document = None
    if vehicle_id:
        plan_document = db.scalar(
            select(Document)
            .where(
                Document.vehicle_id == vehicle_id,
                or_(
                    Document.document_type.in_(("maintenance_plan", "service_plan", "plano_manutencao")),
                    Document.title.ilike("%plano%manuten%"),
                    Document.original_name.ilike("%plano%manuten%"),
                    Document.file_name.ilike("%plano%manuten%"),
                ),
            )
            .order_by(Document.id.desc())
        )

    campaign_task = None
    if plate:
        campaign_task = db.scalar(
            select(Task)
            .where(
                Task.plate == plate,
                Task.closed_at.is_(None),
                or_(
                    Task.title.ilike("%campanha%"),
                    Task.description.ilike("%campanha%"),
                    Task.category.ilike("%campanha%"),
                    Task.subcategory.ilike("%campanha%"),
                    Task.title.ilike("%service box%"),
                    Task.description.ilike("%service box%"),
                ),
            )
            .order_by(Task.id.desc())
        )

    history_audit = None
    if vehicle_id:
        history_audit = db.scalar(
            select(VehicleHistoryAudit)
            .where(VehicleHistoryAudit.vehicle_id == vehicle_id, VehicleHistoryAudit.status != "closed")
            .order_by(VehicleHistoryAudit.updated_at.desc(), VehicleHistoryAudit.id.desc())
        )

    real_start_date = str(vehicle_context.get("real_start_date") or "").strip()
    if not real_start_date or real_start_date in {"-", "Por validar"}:
        real_start_status = "Por definir"
        real_start_impact = "Aviso"
        real_start_class = "warn"
    else:
        real_start_status = real_start_date
        real_start_impact = "Informativo"
        real_start_class = "ok"

    return [
        {
            "name": "Plano de manutenção",
            "origin": "Ficha da viatura",
            "status": f"Documento #{plan_document.id}" if plan_document else "Em falta / por associar",
            "impact": "Informativo" if plan_document else "Aviso",
            "impact_class": "ok" if plan_document else "warn",
            "action": "Abrir plano" if plan_document else "Associar plano",
            "href": f"/v2-clean/fleet/{vehicle_id}/documents?main_group=plans" if vehicle_id else plan_create_href,
        },
        {
            "name": "Service Box / campanhas",
            "origin": "Stellantis",
            "status": "Tarefa aberta" if campaign_task else "Sem tarefa aberta registada",
            "impact": "Aviso" if campaign_task else "Informativo",
            "impact_class": "warn" if campaign_task else "ok",
            "action": f"Tarefa #{campaign_task.id}" if campaign_task else "Criar tarefa se existir campanha",
            "href": f"/v2-clean/tasks?plate={plate}" if campaign_task and plate else None,
        },
        {
            "name": "Início real da viatura",
            "origin": "Ficha da viatura",
            "status": real_start_status,
            "impact": real_start_impact,
            "impact_class": real_start_class,
            "action": "Definir início" if real_start_class == "warn" else "Ver / alterar",
            "href": vehicle_href,
        },
        {
            "name": "Auditoria histórico",
            "origin": "Centro de processos",
            "status": history_audit.status if history_audit else "Sem auditoria aberta",
            "impact": "Aviso" if history_audit else "Informativo",
            "impact_class": "warn" if history_audit else "ok",
            "action": "Abrir auditoria" if history_audit else "Criar auditoria se necessário",
            "href": f"/v2-clean/processes?vehicle_id={history_audit.vehicle_id}" if history_audit else (f"/v2-clean/processes?vehicle_id={vehicle_id}" if vehicle_id else None),
        },
    ]


CLEAN_WORKSHOP_REPORT_TERMINAL_STATUSES = {"OK", "Corrigido", "Não legível", "Não aplicável"}


def clean_workshop_report_is_complete(report: WorkshopPhasedTechnicalReport) -> bool:
    extracted = report.extracted_values_json if isinstance(report.extracted_values_json, dict) else {}
    validated = report.validated_values_json if isinstance(report.validated_values_json, dict) else {}
    if extracted:
        return all(
            str((validated.get(str(code)) or {}).get("status") or "Por validar")
            in CLEAN_WORKSHOP_REPORT_TERMINAL_STATUSES
            for code in extracted
        )
    manual = validated.get("manual_reading") if isinstance(validated.get("manual_reading"), dict) else {}
    return str(manual.get("status") or "Por validar") in CLEAN_WORKSHOP_REPORT_TERMINAL_STATUSES


def clean_workshop_technical_report_summary(
    reports: list[WorkshopPhasedTechnicalReport],
) -> dict[str, dict[str, object]]:

    status_labels = {
        "pending_validation": "Por validar",
        "validated": "Validado",
        "validated_manually": "Validado manual",
        "corrected_manually": "Corrigido",
        "unable_to_read": "Leitura falhou",
        "voided": "Anulado",
    }
    summary: dict[str, dict[str, object]] = {}
    grouped: dict[str, list[WorkshopPhasedTechnicalReport]] = defaultdict(list)
    for report in reports:
        if report.status in {"voided", "superseded"}:
            continue
        grouped[report.report_code].append(report)
    for code, items in grouped.items():
        latest = sorted(items, key=lambda item: item.id, reverse=True)[0]
        extracted_values = latest.extracted_values_json if isinstance(latest.extracted_values_json, dict) else {}
        complete = clean_workshop_report_is_complete(latest)
        if complete:
            display_status = (
                "Validado manual"
                if latest.status in {"pending_validation", "unable_to_read"}
                else status_labels.get(latest.status, latest.status or "Validado manual")
            )
        else:
            display_status = "Por validar"
        summary[code] = {
            "count": len(items),
            "latest": latest,
            "status": display_status,
            "file_name": Path(str(latest.original_link or "")).name or "-",
            "extracted_count": len(extracted_values),
        }
    return summary


def clean_workshop_technical_reading_rows(
    reports: list[WorkshopPhasedTechnicalReport],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    sorted_reports = sorted(
        [item for item in reports if item.status not in {"voided", "superseded"}],
        key=lambda item: item.id,
        reverse=True,
    )
    for report in sorted_reports:
        extracted_values = report.extracted_values_json if isinstance(report.extracted_values_json, dict) else {}
        validated_values = report.validated_values_json if isinstance(report.validated_values_json, dict) else {}
        report_open_url = f"/v2-clean/workshop/technical-reports/{report.id}/file"
        report_display_name = clean_workshop_report_display_label(report.report_code, report.report_name)
        if extracted_values:
            report_fields = stellantis_report_fields(report.report_code)
            field_labels = {
                str(field.get("code")): str(field.get("label"))
                for field in report_fields
            }
            field_labels["machine_path_only"] = "Caminho registado pela maquina (sem valores tecnicos)"
            ordered_codes = [
                str(field.get("code"))
                for field in report_fields
                if str(field.get("code") or "") in extracted_values
            ]
            extra_codes = [
                str(key)
                for key in extracted_values.keys()
                if str(key) not in ordered_codes
            ]
            for key in ordered_codes + extra_codes:
                value = extracted_values.get(key)
                validation = validated_values.get(str(key)) if isinstance(validated_values.get(str(key)), dict) else {}
                validation_status = str(validation.get("status") or "Por validar")
                rows.append(
                    {
                        "report_id": str(report.id),
                        "field_code": str(key),
                        "field": field_labels.get(str(key), str(key)),
                        "report": report_display_name,
                        "report_name": report_display_name,
                        "value": str(value),
                        "corrected_value": str(validation.get("corrected_value") or ""),
                        "observation": str(validation.get("observation") or ""),
                        "status": validation_status,
                        "action": "Guardar",
                        "open_url": report_open_url,
                    }
                )
            continue
        raw_values = report.raw_values_json if isinstance(report.raw_values_json, dict) else {}
        if report.status == "unable_to_read":
            validation = (
                validated_values.get("manual_reading")
                if isinstance(validated_values.get("manual_reading"), dict)
                else {}
            )
            validation_status = str(validation.get("status") or "Por validar")
            rows.append(
                {
                    "report_id": str(report.id),
                    "field_code": "manual_reading",
                    "field": "Leitura automática",
                    "report": report_display_name,
                    "report_name": report_display_name,
                    "value": str(raw_values.get("extraction_error") or "Sem dados extraídos"),
                    "corrected_value": str(validation.get("corrected_value") or ""),
                    "observation": str(validation.get("observation") or ""),
                    "status": validation_status,
                    "action": "Guardar",
                    "open_url": report_open_url,
                }
            )
            continue

        validation = (
            validated_values.get("manual_reading")
            if isinstance(validated_values.get("manual_reading"), dict)
            else {}
        )
        validation_status = str(validation.get("status") or "Por validar")
        rows.append(
            {
                "report_id": str(report.id),
                "field_code": "manual_reading",
                "field": "Relatório carregado",
                "report": report_display_name,
                "report_name": report_display_name,
                "value": str(raw_values.get("original_name") or Path(str(report.original_link or "")).name or "-"),
                "corrected_value": str(validation.get("corrected_value") or ""),
                "observation": str(validation.get("observation") or ""),
                "status": validation_status,
                "action": "Guardar",
                "open_url": report_open_url,
            }
        )
    return rows


def clean_workshop_technical_reading_groups(
    reports: list[WorkshopPhasedTechnicalReport],
) -> list[dict[str, object]]:
    grouped: list[dict[str, object]] = []
    by_report_id: dict[str, dict[str, object]] = {}
    report_statuses = {str(report.id): report.status for report in reports}
    for row in clean_workshop_technical_reading_rows(reports):
        report_id = str(row["report_id"])
        group = by_report_id.get(report_id)
        if not group:
            group = {
                "report_id": report_id,
                "report": row["report"],
                "open_url": row["open_url"],
                "report_name": row["report_name"],
                "report_status": report_statuses.get(report_id, "pending_validation"),
                "rows": [],
            }
            by_report_id[report_id] = group
            grouped.append(group)
        group["rows"].append(row)

    for group in grouped:
        rows = group["rows"] if isinstance(group["rows"], list) else []
        group["count"] = len(rows)
        group["validated_count"] = sum(
            1
            for row in rows
            if str(row.get("status") or "Por validar") in {"OK", "Corrigido", "Não legível", "Não aplicável"}
        )
    return grouped


def clean_workshop_diagnostic_substep_status(
    reports: list[WorkshopPhasedTechnicalReport],
) -> dict[str, str]:
    active_reports = [report for report in reports if report.status not in {"voided", "superseded"}]
    pending = [report for report in active_reports if not clean_workshop_report_is_complete(report)]
    extracted = [
        report
        for report in active_reports
        if isinstance(report.extracted_values_json, dict) and report.extracted_values_json
    ]
    validated = [report for report in active_reports if report.status in {"validated", "validated_manually", "corrected_manually"}]
    return {
        "relatorios": f"{len(pending)} por validar" if pending else ("Sem relatórios" if not active_reports else "Guardado"),
        "leituras": (
            f"{len(extracted)} com dados"
            if extracted
            else ("Sem dados" if not active_reports else ("Validado" if validated and not pending else "Por rever"))
        ),
    }


def clean_workshop_diagnostic_form_status(
    snapshot: dict[str, object],
    reports: list[WorkshopPhasedTechnicalReport],
    saved_substeps: set[str] | None = None,
) -> dict[str, str]:
    report_status = clean_workshop_diagnostic_substep_status(reports)
    comparison_has_data = any(
        [
            clean_form_value(snapshot, "pre_report_exists").strip(),
            clean_form_value(snapshot, "post_report_exists").strip(),
            clean_form_value(snapshot, "bsi_vs_billing").strip(),
            clean_form_value(snapshot, "remote_download_vs_tsb").strip(),
            clean_form_value(snapshot, "comparison_differences").strip(),
            clean_form_value(snapshot, "comparison_evidence").strip(),
        ]
    )
    problem_has_data = any(
        [
            clean_form_value(snapshot, "diagnostic_problem_detected").strip(),
            clean_form_value(snapshot, "diagnostic_problem_title").strip(),
            clean_form_value(snapshot, "diagnostic_problem_origin").strip(),
            clean_form_value(snapshot, "diagnostic_problem_evidence").strip(),
            clean_form_value(snapshot, "diagnostic_problem_action").strip(),
        ]
    )
    exit_has_data = any(
        [
            clean_form_value(snapshot, "diagnostic_closed").strip(),
            clean_form_value(snapshot, "diagnostic_priority").strip(),
            clean_form_value(snapshot, "diagnostic_conclusion").strip(),
            clean_form_value(snapshot, "diagnostic_reserve_reason").strip(),
        ]
    )
    return {
        "relatorios": report_status["relatorios"],
        "leituras": report_status["leituras"],
        "comparacao": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "comparacao", legacy_has_data=comparison_has_data)
        else "Por validar",
        "problemas": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "problemas", legacy_has_data=problem_has_data)
        else "Por validar",
        "saida": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "saida-diagnostico", legacy_has_data=exit_has_data)
        else "Pendente",
    }


def clean_workshop_inspection_form_status(
    snapshot: dict[str, object],
    saved_substeps: set[str] | None = None,
) -> dict[str, str]:
    checklist_keys = [
        "inspection_check_lights",
        "inspection_check_battery",
        "inspection_check_leaks",
        "inspection_check_noises",
        "inspection_check_road_test",
    ]
    checklist_answers = [clean_form_value(snapshot, key, "review") for key in checklist_keys]
    checklist_pending = sum(1 for value in checklist_answers if value in {"", "review"})
    checklist_has_data = any(value not in {"", "review"} for value in checklist_answers)

    tyres_brakes_has_data = any(
        [
            clean_form_value(snapshot, "tyres_front_condition").strip(),
            clean_form_value(snapshot, "tyres_rear_condition").strip(),
            clean_form_value(snapshot, "pads_front_condition").strip(),
            clean_form_value(snapshot, "discs_front_condition").strip(),
            clean_form_value(snapshot, "brakes_rear_condition").strip(),
        ]
    )
    oil_levels_has_data = any(
        [
            clean_form_value(snapshot, "oil_level").strip(),
            clean_form_value(snapshot, "oil_visual_state").strip(),
            clean_form_value(snapshot, "coolant_level").strip(),
            clean_form_value(snapshot, "brake_fluid_level").strip(),
            clean_form_value(snapshot, "oil_diagnosis_confirmed").strip(),
            clean_form_value(snapshot, "oil_levels_observation").strip(),
        ]
    )
    exit_has_data = any(
        [
            clean_form_value(snapshot, "inspection_closed").strip(),
            clean_form_value(snapshot, "inspection_priority").strip(),
            clean_form_value(snapshot, "inspection_summary").strip(),
            clean_form_value(snapshot, "inspection_reserve_reason").strip(),
            clean_form_value(snapshot, "inspection_create_task").strip(),
            clean_form_value(snapshot, "inspection_create_problem").strip(),
            clean_form_value(snapshot, "inspection_needs_quote").strip(),
            clean_form_value(snapshot, "inspection_can_advance_with_reserve").strip(),
            clean_form_value(snapshot, "inspection_no_nonconformities").strip(),
        ]
    )
    checklist_status = "Por rever"
    if checklist_has_data:
        checklist_status = "Guardado" if checklist_pending == 0 else f"{checklist_pending} por rever"
    return {
        "checklist": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "checklist", legacy_has_data=checklist_pending == 0 and checklist_has_data)
        else checklist_status,
        "pneus_travoes": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "pneus-travoes", legacy_has_data=tyres_brakes_has_data)
        else "Por validar",
        "oleo_niveis": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "oleo-niveis", legacy_has_data=oil_levels_has_data)
        else "Por validar",
        "saida": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "saida-inspecao", legacy_has_data=exit_has_data)
        else "Pendente",
    }


def clean_workshop_audit_form_status(
    snapshot: dict[str, object],
    saved_substeps: set[str] | None = None,
) -> dict[str, str]:
    evidence_has_data = bool(clean_form_value(snapshot, "audit_evidence_summary").strip())
    coherence_has_data = any(
        [
            clean_form_value(snapshot, "audit_bsi_billing_result").strip(),
            clean_form_value(snapshot, "audit_oil_limit_result").strip(),
            clean_form_value(snapshot, "audit_remote_download_result").strip(),
            clean_form_value(snapshot, "audit_service_repeat_result").strip(),
        ]
    )
    problems_has_data = bool(clean_form_value(snapshot, "audit_open_items_summary").strip())
    decision_has_data = any(
        [
            clean_form_value(snapshot, "audit_decision_main").strip(),
            clean_form_value(snapshot, "audit_repair_authorized").strip(),
            clean_form_value(snapshot, "audit_responsibility").strip(),
            clean_form_value(snapshot, "audit_quote_needed").strip(),
            clean_form_value(snapshot, "audit_estimated_value").strip(),
            clean_form_value(snapshot, "audit_decision_reason").strip(),
        ]
    )
    exit_has_data = any(
        [
            clean_form_value(snapshot, "audit_closed").strip(),
            clean_form_value(snapshot, "audit_priority").strip(),
            clean_form_value(snapshot, "audit_summary").strip(),
            clean_form_value(snapshot, "audit_reserve_reason").strip(),
            clean_form_value(snapshot, "audit_condition_service_confirmed").strip(),
            clean_form_value(snapshot, "audit_condition_quote_handled").strip(),
            clean_form_value(snapshot, "audit_condition_campaigns_checked").strip(),
            clean_form_value(snapshot, "audit_condition_problems_logged").strip(),
            clean_form_value(snapshot, "audit_condition_owner_defined").strip(),
        ]
    )
    return {
        "evidencias": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "evidencias", legacy_has_data=evidence_has_data)
        else "Por fechar",
        "coerencia": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "coerencia", legacy_has_data=coherence_has_data)
        else "Por validar",
        "problemas": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "problemas-auditoria", legacy_has_data=problems_has_data)
        else "Por fechar",
        "decisao": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "decisao", legacy_has_data=decision_has_data)
        else "Pendente",
        "saida": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "saida-auditoria", legacy_has_data=exit_has_data)
        else "Pendente",
    }


def clean_workshop_repair_form_status(
    snapshot: dict[str, object],
    saved_substeps: set[str] | None = None,
) -> dict[str, str]:
    order_has_data = bool(clean_form_value(snapshot, "repair_authorized_services").strip())
    execution_has_data = any(
        [
            clean_form_value(snapshot, "repair_execution_status").strip(),
            clean_form_value(snapshot, "repair_responsible").strip(),
            clean_form_value(snapshot, "repair_started_on").strip(),
            clean_form_value(snapshot, "repair_eta").strip(),
            clean_form_value(snapshot, "repair_vehicle_immobilized").strip(),
            clean_form_value(snapshot, "repair_execution_note").strip(),
        ]
    )
    evidence_has_data = any(
        [
            clean_form_value(snapshot, "repair_fo_status").strip(),
            clean_form_value(snapshot, "repair_photos_status").strip(),
            clean_form_value(snapshot, "repair_post_report_status").strip(),
            clean_form_value(snapshot, "repair_campaign_proof_status").strip(),
        ]
    )
    deviations_has_data = any(
        [
            clean_form_value(snapshot, "repair_deviation_exists").strip(),
            clean_form_value(snapshot, "repair_new_quote_needed").strip(),
            clean_form_value(snapshot, "repair_deviation_reason").strip(),
            clean_form_value(snapshot, "repair_timing_impact").strip(),
            clean_form_value(snapshot, "repair_financial_impact").strip(),
            clean_form_value(snapshot, "repair_action_needed").strip(),
        ]
    )
    exit_has_data = any(
        [
            clean_form_value(snapshot, "repair_closed").strip(),
            clean_form_value(snapshot, "repair_exit_status").strip(),
            clean_form_value(snapshot, "repair_summary").strip(),
            clean_form_value(snapshot, "repair_reserve_reason").strip(),
            clean_form_value(snapshot, "repair_done").strip(),
            clean_form_value(snapshot, "repair_fo_attached").strip(),
            clean_form_value(snapshot, "repair_photos_attached").strip(),
            clean_form_value(snapshot, "repair_post_report_done").strip(),
            clean_form_value(snapshot, "repair_campaigns_done").strip(),
        ]
    )
    return {
        "ordem": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "ordem-reparacao", legacy_has_data=order_has_data)
        else "Em curso",
        "execucao": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "execucao", legacy_has_data=execution_has_data)
        else "Por atualizar",
        "evidencias": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "evidencias-reparacao", legacy_has_data=evidence_has_data)
        else "Pendente",
        "desvios": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "desvios", legacy_has_data=deviations_has_data)
        else "Sem desvios",
        "saida": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "saida-reparacao", legacy_has_data=exit_has_data)
        else "Pendente",
    }


def clean_workshop_closure_form_status(
    snapshot: dict[str, object],
    saved_substeps: set[str] | None = None,
) -> dict[str, str]:
    final_validation_has_data = any(
        [
            clean_form_value(snapshot, "closure_vehicle_ready").strip(),
            clean_form_value(snapshot, "closure_final_status").strip(),
            clean_form_value(snapshot, "closure_exit_observation").strip(),
            clean_form_value(snapshot, "closure_km_checked").strip(),
            clean_form_value(snapshot, "closure_dashboard_exit_photo").strip(),
            clean_form_value(snapshot, "closure_final_test_ok").strip(),
            clean_form_value(snapshot, "closure_can_drive").strip(),
            clean_form_value(snapshot, "closure_back_to_fleet").strip(),
        ]
    )
    documents_has_data = any(
        [
            clean_form_value(snapshot, "closure_work_order_status").strip(),
            clean_form_value(snapshot, "closure_invoice_status").strip(),
            clean_form_value(snapshot, "closure_post_report_status").strip(),
            clean_form_value(snapshot, "closure_final_photos_status").strip(),
        ]
    )
    history_has_data = any(
        [
            clean_form_value(snapshot, "closure_service_history_status").strip(),
            clean_form_value(snapshot, "closure_next_maintenance_status").strip(),
            clean_form_value(snapshot, "closure_problem_history_status").strip(),
            clean_form_value(snapshot, "closure_audit_history_status").strip(),
            clean_form_value(snapshot, "closure_sale_state_status").strip(),
        ]
    )
    pending_has_data = any(
        [
            clean_form_value(snapshot, "closure_pending_exists").strip(),
            clean_form_value(snapshot, "closure_pending_type").strip(),
            clean_form_value(snapshot, "closure_pending_owner").strip(),
            clean_form_value(snapshot, "closure_pending_due").strip(),
            clean_form_value(snapshot, "closure_pending_blocks_use").strip(),
            clean_form_value(snapshot, "closure_pending_description").strip(),
        ]
    )
    closing_has_data = any(
        [
            clean_form_value(snapshot, "closure_result").strip(),
            clean_form_value(snapshot, "closure_state").strip(),
            clean_form_value(snapshot, "closure_summary").strip(),
            clean_form_value(snapshot, "closure_final_note").strip(),
            clean_form_value(snapshot, "closure_vehicle_validated").strip(),
            clean_form_value(snapshot, "closure_min_docs_attached").strip(),
            clean_form_value(snapshot, "closure_history_updated").strip(),
            clean_form_value(snapshot, "closure_pending_assigned").strip(),
            clean_form_value(snapshot, "closure_fleet_state_defined").strip(),
        ]
    )
    return {
        "validacao": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "validacao-final", legacy_has_data=final_validation_has_data)
        else "Por validar",
        "documentos": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "documentos-fecho", legacy_has_data=documents_has_data)
        else "Pendente",
        "historico": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "historico-fecho", legacy_has_data=history_has_data)
        else "Pendente",
        "pendencias": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "pendencias-fecho", legacy_has_data=pending_has_data)
        else "Pendente",
        "encerramento": "Guardado"
        if clean_workshop_substep_is_saved(saved_substeps, "encerramento", legacy_has_data=closing_has_data)
        else "Pendente",
    }


def clean_workshop_vehicle_context(db: Session, vehicle_id: int | None = None, plate: str | None = None) -> dict[str, object]:
    vehicle: Vehicle | None = None
    if vehicle_id:
        vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle and plate:
        vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == normalize_identifier(plate)))
    if not vehicle:
        return dict(CLEAN_WORKSHOP_CONTEXT)

    snapshot = db.scalar(
        select(VehicleExternalSnapshot)
        .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
        .order_by(VehicleExternalSnapshot.updated_at.desc())
    )
    data = snapshot_data(snapshot)
    vehicle_context = rentway_vehicle_context(snapshot)
    commercial_context = rentway_commercial_context(snapshot)
    manual_fields = {
        item.field_code: item.value_json
        for item in db.scalars(select(VehicleManualField).where(VehicleManualField.vehicle_id == vehicle.id)).all()
    }
    rules = vehicle_rule_context(snapshot, manual_fields)
    brand = vehicle.brand or snapshot_value(data, ["brandid", "marca", "brand"]) or ""
    model = vehicle.model or snapshot_value(data, ["modelid", "modelo", "model"]) or ""
    version = vehicle.version or snapshot_value(data, ["version", "versao"]) or ""
    fuel = snapshot_value(data, ["fuel", "combustivel"]) or "-"
    real_start_date = str(manual_fields.get("real_start_date") or "").strip() or "Por validar"
    is_stellantis = brand.strip().upper() in STELLANTIS_BRANDS

    current_km = parse_decimal_text(commercial_context.get("km") or snapshot_value(data, ["kms", "km"]))
    rentway_next_service_km = parse_decimal_text(rules.get("rentway_next_service_km"))
    calculated_ipo = rules.get("calculated_ipo")
    rentway_ipo = rules.get("rentway_ipo")
    ipo_diff_days = None
    if isinstance(calculated_ipo, date) and isinstance(rentway_ipo, date):
        ipo_diff_days = abs((calculated_ipo - rentway_ipo).days)
    alerts: list[dict[str, str]] = []
    if rules.get("ipo_status") == "Divergente" and (ipo_diff_days is None or ipo_diff_days > 7):
        alerts.append(
            {
                "severity": "danger",
                "title": "IPO divergente",
                "detail": f"Rentway {clean_date(rentway_ipo.isoformat() if rentway_ipo else None)} / cálculo {clean_date(calculated_ipo.isoformat() if calculated_ipo else None)}",
            }
        )
    if isinstance(calculated_ipo, date):
        days_to_ipo = (calculated_ipo - date.today()).days
        if days_to_ipo < 0:
            alerts.append(
                {
                    "severity": "danger",
                    "title": "IPO vencida",
                    "detail": f"Data calculada {clean_date(calculated_ipo.isoformat())}",
                }
            )
        elif days_to_ipo <= 60:
            alerts.append(
                {
                    "severity": "warn",
                    "title": "IPO próxima",
                    "detail": f"{clean_date(calculated_ipo.isoformat())} · faltam {days_to_ipo} dias",
                }
            )
    if rules.get("maintenance_status") == "Divergente":
        alerts.append(
            {
                "severity": "danger",
                "title": "Manutenção divergente",
                "detail": "Rentway e cálculo CarFast não coincidem.",
            }
        )
    if current_km is not None and rentway_next_service_km is not None:
        km_to_service = int(rentway_next_service_km - current_km)
        if km_to_service < 0:
            alerts.append(
                {
                    "severity": "danger",
                    "title": "Manutenção ultrapassada",
                    "detail": f"{abs(km_to_service)} km acima do próximo serviço Rentway.",
                }
            )
        elif km_to_service <= 1500:
            alerts.append(
                {
                    "severity": "warn",
                    "title": "Manutenção próxima",
                    "detail": f"Faltam {km_to_service} km para o próximo serviço Rentway.",
                }
            )
    calculated_service_date = rules.get("calculated_service_date")
    if isinstance(calculated_service_date, date):
        days_to_service = (calculated_service_date - date.today()).days
        if days_to_service < 0:
            alerts.append(
                {
                    "severity": "danger",
                    "title": "Manutenção calculada vencida",
                    "detail": f"Data calculada {clean_date(calculated_service_date.isoformat())}",
                }
            )
        elif days_to_service <= 30:
            alerts.append(
                {
                    "severity": "warn",
                    "title": "Manutenção calculada próxima",
                    "detail": f"{clean_date(calculated_service_date.isoformat())} · faltam {days_to_service} dias",
                }
            )

    return {
        "process_ref": CLEAN_WORKSHOP_CONTEXT["process_ref"],
        "plate": vehicle.plate or snapshot_value(data, ["platenr", "matricula", "plate"]) or "-",
        "vehicle": " ".join(part for part in [brand, model, version] if part).strip() or "-",
        "vin": vehicle.vin or snapshot_value(data, ["chassinr", "vin", "chassis"]) or "-",
        "groupid": vehicle_context.get("groupid") or "-",
        "fuel": fuel,
        "purchase_supplier": commercial_context.get("purchase_supplier") or "-",
        "entry_date": datetime.now().strftime("%d/%m/%Y"),
        "entry_km": clean_km(commercial_context.get("km") or snapshot_value(data, ["kms", "km"])),
        "expected_exit": "-",
        "registration_date": clean_date(vehicle_context.get("plate_date")),
        "purchase_date": clean_date(vehicle_context.get("purchase_date")),
        "real_start_date": clean_date(real_start_date) if real_start_date != "Por validar" else real_start_date,
        "next_ipo": clean_date((rules.get("calculated_ipo") or rules.get("rentway_ipo")).isoformat() if rules.get("calculated_ipo") or rules.get("rentway_ipo") else None),
        "last_service_km": f"{clean_km(snapshot_value(data, ['last_service', 'lastservice']))} km",
        "next_service_km": f"{clean_km(snapshot_value(data, ['next_service', 'nextservice']))} km",
        "next_service_date": clean_date(str(rules.get("rentway_next_service_date") or "")),
        "maintenance_status": f"Manutenção: {rules.get('maintenance_status')}",
        "history_audit_status": "Auditoria histórico: por validar",
        "sale_status": "Venda: por validar",
        "brand_rule": "Service Box aplicável" if is_stellantis else "Service Box não aplicável",
        "alerts": alerts,
    }




def latest_vehicle_snapshot(db: Session, vehicle_id: int) -> VehicleExternalSnapshot | None:
    return db.scalar(
        select(VehicleExternalSnapshot)
        .where(VehicleExternalSnapshot.vehicle_id == vehicle_id)
        .order_by(VehicleExternalSnapshot.updated_at.desc())
    )


def clean_vehicle_display_context(db: Session, vehicle: Vehicle) -> dict[str, object]:
    snapshot = latest_vehicle_snapshot(db, vehicle.id)
    data = snapshot_data(snapshot)
    vehicle_context = rentway_vehicle_context(snapshot)
    commercial_context = rentway_commercial_context(snapshot)
    manual_fields = vehicle_manual_values(db, vehicle.id)
    rules = vehicle_rule_context(snapshot, manual_fields)
    current_cost = current_cost_from_snapshot(snapshot)

    brand = vehicle.brand or snapshot_value(data, ["brandid", "marca", "brand"]) or ""
    model = vehicle.model or snapshot_value(data, ["modelid", "modelo", "model"]) or ""
    version = vehicle.version or snapshot_value(data, ["version", "versao"]) or ""
    real_start_date = str(manual_fields.get("real_start_date") or "").strip()
    sale_blocked = bool(manual_fields.get("sale_blocked"))
    debt_value = manual_fields.get("debt_value")
    finance_entity = manual_fields.get("finance_entity") or commercial_context.get("finance_entity")
    calculated_ipo = rules.get("calculated_ipo")
    rentway_ipo = rules.get("rentway_ipo")
    calculated_service_date = rules.get("calculated_service_date")
    ipo_diff_days = None
    if isinstance(calculated_ipo, date) and isinstance(rentway_ipo, date):
        ipo_diff_days = abs((calculated_ipo - rentway_ipo).days)

    alerts: list[dict[str, str]] = []
    if sale_blocked:
        reason = manual_fields.get("sale_block_reason_other") or manual_fields.get("sale_block_reason") or "Sem motivo registado"
        alerts.append({"severity": "danger", "title": "Venda bloqueada", "detail": str(reason)})
    if not real_start_date:
        alerts.append({"severity": "warn", "title": "Início real por validar", "detail": "Campo necessário para auditoria e manutenção."})
    if rules.get("ipo_status") == "Divergente" and (ipo_diff_days is None or ipo_diff_days > 7):
        alerts.append({"severity": "danger", "title": "IPO divergente", "detail": "Rentway e cálculo CarFast não coincidem."})
    elif isinstance(calculated_ipo, date):
        days_to_ipo = (calculated_ipo - date.today()).days
        if days_to_ipo < 0:
            alerts.append({"severity": "danger", "title": "IPO vencida", "detail": clean_date(calculated_ipo.isoformat())})
        elif days_to_ipo <= 60:
            alerts.append({"severity": "warn", "title": "IPO próxima", "detail": f"{clean_date(calculated_ipo.isoformat())} · {days_to_ipo} dias"})
    if rules.get("maintenance_status") == "Divergente":
        alerts.append({"severity": "danger", "title": "Manutenção divergente", "detail": "Plano calculado e Rentway não coincidem."})
    elif isinstance(calculated_service_date, date):
        days_to_service = (calculated_service_date - date.today()).days
        if days_to_service < 0:
            alerts.append({"severity": "danger", "title": "Manutenção vencida", "detail": clean_date(calculated_service_date.isoformat())})
        elif days_to_service <= 30:
            alerts.append({"severity": "warn", "title": "Manutenção próxima", "detail": f"{clean_date(calculated_service_date.isoformat())} · {days_to_service} dias"})

    return {
        "vehicle": vehicle,
        "snapshot": snapshot,
        "manual": manual_fields,
        "rules": rules,
        "commercial": commercial_context,
        "identity": {
            "unit": vehicle.rentway_unit_nr or snapshot_value(data, ["unitnr", "unit_nr"]),
            "plate": vehicle.plate or snapshot_value(data, ["platenr", "plate", "matricula"]),
            "brand": brand or "-",
            "model": model or "-",
            "version": version or "-",
            "vin": vehicle.vin or snapshot_value(data, ["chassinr", "vin", "chassis"]) or "-",
            "groupid": vehicle_context.get("groupid") or "-",
            "colour": vehicle_context.get("colour") or "-",
            "fuel": vehicle_context.get("fuel") or "-",
            "purchase_supplier": commercial_context.get("purchase_supplier") or "-",
        },
        "dates": {
            "registration": clean_date(vehicle_context.get("plate_date")),
            "purchase": clean_date(vehicle_context.get("purchase_date")),
            "real_start": clean_date(real_start_date) if real_start_date else "Por validar",
            "rentway_ipo": clean_date(rules["rentway_ipo"].isoformat() if rules.get("rentway_ipo") else None),
            "calculated_ipo": clean_date(calculated_ipo.isoformat() if isinstance(calculated_ipo, date) else None),
            "service_calculated": clean_date(calculated_service_date.isoformat() if isinstance(calculated_service_date, date) else None),
        },
        "maintenance": {
            "last_rentway_km": clean_km(str(rules.get("rentway_last_service_km") or "")),
            "next_rentway_km": clean_km(str(rules.get("rentway_next_service_km") or "")),
            "calculated_km": clean_km(str(rules.get("calculated_service_km") or "")),
            "next_display": " · ".join(
                part
                for part in [
                    clean_date(calculated_service_date.isoformat() if isinstance(calculated_service_date, date) else None),
                    f"{clean_km(str(rules.get('calculated_service_km') or rules.get('rentway_next_service_km') or ''))} km"
                    if rules.get("calculated_service_km") or rules.get("rentway_next_service_km")
                    else "",
                ]
                if part and part != "-"
            )
            or "Por configurar",
            "status": rules.get("maintenance_status") or "Por configurar",
        },
        "finance": {
            "initial_cost": format_eur(current_cost.get("initial_cost")),
            "current_cost": format_eur(current_cost.get("current_cost")),
            "amortization_month": current_cost.get("amortization_month") or "-",
            "debt_value": format_eur(debt_value),
            "finance_entity": finance_entity or "-",
        },
        "status": {
            "lifecycle": vehicle.lifecycle_status or "-",
            "operational": vehicle.operational_status or "-",
            "rentway": commercial_context.get("current_status") or "-",
            "location": commercial_context.get("rental_station") or "-",
            "client": commercial_context.get("client") or "-",
            "document": commercial_context.get("document_nr") or "-",
        },
        "alerts": alerts,
    }


def clean_vehicle_fallback_context(vehicle: Vehicle, error: Exception | None = None) -> dict[str, object]:
    alerts = []
    if error:
        alerts.append(
            {
                "severity": "warn",
                "title": "Dados parciais",
                "detail": "Alguns dados externos desta viatura precisam de revisão.",
            }
        )
    return {
        "vehicle": vehicle,
        "snapshot": None,
        "manual": {},
        "rules": {},
        "commercial": {},
        "identity": {
            "unit": vehicle.rentway_unit_nr or "-",
            "plate": vehicle.plate or "-",
            "brand": vehicle.brand or "-",
            "model": vehicle.model or "-",
            "version": vehicle.version or "-",
            "vin": vehicle.vin or "-",
            "groupid": "-",
            "colour": "-",
            "fuel": "-",
            "purchase_supplier": "-",
        },
        "dates": {
            "registration": "-",
            "purchase": "-",
            "real_start": "Por validar",
            "rentway_ipo": "-",
            "calculated_ipo": "-",
            "service_calculated": "-",
        },
        "maintenance": {
            "last_rentway_km": "-",
            "next_rentway_km": "-",
            "calculated_km": "-",
            "next_display": "Por configurar",
            "status": "Por validar",
        },
        "finance": {
            "initial_cost": "-",
            "current_cost": "-",
            "amortization_month": "-",
            "debt_value": "-",
            "finance_entity": "-",
        },
        "status": {
            "lifecycle": vehicle.lifecycle_status or "-",
            "operational": vehicle.operational_status or "-",
            "rentway": "-",
            "location": "-",
            "client": "-",
            "document": "-",
        },
        "alerts": alerts,
    }



def clean_vehicle_document_group(document: Document) -> str:
    doc_type = (document.document_type or "").strip().lower()
    title = " ".join(
        part for part in [document.title, document.original_name, document.supplier_name, document.source_subject] if part
    ).lower()
    if doc_type == "workshop_work_order" or "folha" in title or "ordem" in title or "fo " in title:
        return "work_orders"
    if doc_type in {"workshop_supplier_invoice", "finance_supplier_invoice"} or "fatura" in title or "factura" in title:
        return "invoices"
    if doc_type in {"workshop_report", "workshop_diagnostic", "workshop_bsi"} or "relat" in title or "bsi" in title or "diagn" in title:
        return "technical_reports"
    if "service box" in title or "servicebox" in title:
        return "service_box"
    if "tsb" in title or "boletim" in title:
        return "tsb"
    if "telecarreg" in title or "calibra" in title or "software" in title:
        return "telecharge"
    if doc_type == "finance_rental_plan" or "plano" in title:
        return "plans"
    return "other"


CLEAN_FLEET_DOCUMENT_GROUPS = [
    ("work_orders", "Folhas de obra"),
    ("invoices", "Faturas"),
    ("technical_reports", "Diagnósticos"),
    ("service_box", "Service Box"),
    ("tsb", "TSB"),
    ("telecharge", "Telecarregamentos"),
    ("plans", "Planos"),
    ("missing", "Em falta"),
]
CLEAN_FLEET_DOCUMENT_GROUP_LABELS = dict(CLEAN_FLEET_DOCUMENT_GROUPS)


def clean_vehicle_document_summary(documents: list[Document]) -> dict[str, int]:
    summary = {code: 0 for code, _label in CLEAN_FLEET_DOCUMENT_GROUPS}
    for document in documents:
        group = clean_vehicle_document_group(document)
        summary[group] = summary.get(group, 0) + 1
    return summary
@web_router.get("/v2-clean/fleet", response_class=HTMLResponse)
def clean_fleet_page(request: Request, q: str | None = None, scope: str = "active"):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if not can_view_fleet(request):
        return RedirectResponse("/", status_code=303)
    raw_query = (q or "").strip()
    normalized_query = normalize_identifier(raw_query) if raw_query else ""
    with SessionLocal() as db:
        stmt = select(Vehicle).order_by(Vehicle.updated_at.desc(), Vehicle.id.desc()).limit(300)
        if scope == "active":
            stmt = stmt.where(
                Vehicle.active.is_(True),
                or_(Vehicle.lifecycle_status.is_(None), Vehicle.lifecycle_status != "sold"),
                or_(Vehicle.operational_status.is_(None), Vehicle.operational_status != "sold"),
            )
        elif scope == "for_sale":
            stmt = stmt.where(Vehicle.lifecycle_status == "for_sale")
        if raw_query:
            normalized_plate = func.replace(func.replace(func.upper(Vehicle.plate), "-", ""), " ", "")
            stmt = stmt.where(
                Vehicle.plate.ilike(f"%{raw_query}%")
                | normalized_plate.ilike(f"%{normalized_query}%")
                | Vehicle.vin.ilike(f"%{raw_query}%")
                | Vehicle.rentway_unit_nr.ilike(f"%{raw_query}%")
                | Vehicle.brand.ilike(f"%{raw_query}%")
                | Vehicle.model.ilike(f"%{raw_query}%")
            )
        vehicles = sorted(db.scalars(stmt).all(), key=rentway_unit_sort_key, reverse=True)[:120]
        plate_suggestions = [
            plate
            for plate in db.scalars(
                select(Vehicle.plate)
                .where(Vehicle.plate.is_not(None))
                .order_by(Vehicle.plate.asc())
                .limit(1000)
            ).all()
            if plate
        ]
        rows = []
        for vehicle in vehicles:
            rows.append(
                {
                    "id": vehicle.id,
                    "plate": vehicle.plate or "-",
                    "brand": vehicle.brand or "-",
                    "model": vehicle.model or "-",
                    "version": vehicle.version or "",
                    "unit": vehicle.rentway_unit_nr or "-",
                    "vin": vehicle.vin or "-",
                    "group": "-",
                    "fuel": "-",
                    "ipo": "-",
                    "maintenance": vehicle.lifecycle_status or vehicle.operational_status or "Ver ficha",
                    "primary_alert": None,
                }
            )
        sale_block_fields = db.scalars(
            select(VehicleManualField.value_json).where(
                VehicleManualField.field_code == "sale_blocked",
            )
        ).all()
        counts = {
            "active": db.scalar(
                select(func.count())
                .select_from(Vehicle)
                .where(
                    Vehicle.active.is_(True),
                    or_(Vehicle.lifecycle_status.is_(None), Vehicle.lifecycle_status != "sold"),
                    or_(Vehicle.operational_status.is_(None), Vehicle.operational_status != "sold"),
                )
            ) or 0,
            "for_sale": db.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.lifecycle_status == "for_sale")) or 0,
            "blocked_sale": sum(1 for value in sale_block_fields if value is True or str(value).lower() == "true"),
            "total": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
        }
    return templates.TemplateResponse(
        request,
        "clean_fleet.html",
        {"rows": rows, "counts": counts, "q": q or "", "scope": scope, "plate_suggestions": plate_suggestions},
    )



@web_router.get("/v2-clean/fleet/{vehicle_id}/documents", response_class=HTMLResponse)
def clean_fleet_documents(
    request: Request,
    vehicle_id: int,
    q: str | None = None,
    main_group: str = "",
    doc_group: str = "",
    archive_group: str = "",
    status: str = "",
    document_created: str | None = None,
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if not can_view_fleet(request):
        return RedirectResponse("/", status_code=303)
    search = (q or "").strip().lower()
    clean_main_group = (main_group or doc_group or "").strip()
    clean_main_group = {
        "technical_reports": "diagnostics",
    }.get(clean_main_group, clean_main_group)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet", status_code=303)
        context = clean_vehicle_display_context(db, vehicle)
        try:
            module_ctx = vehicle_document_module_context(db, vehicle)
        except Exception:
            module_ctx = {
                "group_counts": {code: 0 for code, _ in DOCUMENT_HISTORY_MAIN_GROUPS},
                "archive_rows": [],
                "structured_rows": [],
                "comparison_rows": [],
                "timeline_events": [],
                "timeline_ticks": [],
                "timeline_segments": [],
                "alerts": [
                    {
                        "title": "Módulo documental indisponível",
                        "detail": "A documentação desta viatura ainda não pôde ser carregada. Revê migrações ou dados importados.",
                        "severity": "warning",
                        "severity_label": "Aviso",
                        "source": "fallback",
                    }
                ],
                "pendings": [],
                "audit_fields": {},
                "document_options": [],
                "record_tags": {},
                "document_tags": {},
                "archive_documents_count": 0,
                "structured_documents_count": 0,
            }

        def matches_search(parts: list[str]) -> bool:
            if not search:
                return True
            blob = " ".join(part for part in parts if part).lower()
            return search in blob

        archive_rows = []
        for row in module_ctx["archive_rows"]:
            if archive_group and row["archive_group"] != archive_group:
                continue
            if clean_main_group and row.get("main_group") != clean_main_group:
                continue
            if status and row["status"] != status and row.get("comparison_state") != status:
                continue
            if not matches_search(
                [
                    row["title"],
                    row["supplier_name"],
                    row["document_number"],
                    row["document_type"],
                    " ".join(row["tags"]),
                ]
            ):
                continue
            archive_rows.append(row)

        structured_rows = []
        for row in module_ctx["structured_rows"]:
            if clean_main_group and row["main_group"] != clean_main_group:
                continue
            if status and row["status"] != status and row["comparison_state"] != status:
                continue
            if not matches_search(
                [
                    row["title"],
                    row["supplier_name"],
                    row["description"],
                    row["external_reference"],
                    " ".join(row["tags"]),
                ]
            ):
                continue
            structured_rows.append(row)
        structured_order = [code for code, _label in DOCUMENT_HISTORY_MAIN_GROUPS]
        structured_seen = {row["main_group"] for row in structured_rows}
        structured_sections = []
        for group_code in structured_order + sorted(structured_seen - set(structured_order)):
            group_rows = [row for row in structured_rows if row["main_group"] == group_code]
            if group_rows:
                structured_sections.append(
                    {
                        "code": group_code,
                        "label": DOCUMENT_HISTORY_MAIN_GROUP_LABELS.get(group_code, group_code),
                        "rows": group_rows,
                    }
                )

        comparison_rows = [
            row
            for row in module_ctx["comparison_rows"]
            if not status or row["state"] == status
        ]
        if search:
            comparison_rows = [
                row
                for row in comparison_rows
                if matches_search(
                    [
                        row["work_order"]["title"],
                        row["invoice"]["title"] if row["invoice"] else "",
                        row["state_label"],
                    ]
                )
            ]

        all_statuses = [
            ("", "Todos"),
            ("pending", "Pendente"),
            ("associated", "Associado"),
            ("structured", "Estruturado"),
            ("open", "Aberto"),
            ("coerente", "Coerente"),
            ("complementar", "Complementar"),
            ("divergente", "Divergente"),
            ("por_validar", "Por validar"),
        ]
    return templates.TemplateResponse(
        request,
        "clean_fleet_documents.html",
        {
            "ctx": context,
            "module_ctx": module_ctx,
            "archive_rows": archive_rows,
            "structured_rows": structured_rows,
            "structured_sections": structured_sections,
            "comparison_rows": comparison_rows,
            "q": q or "",
            "main_group": clean_main_group,
            "archive_group": archive_group,
            "status": status,
            "main_groups": DOCUMENT_HISTORY_MAIN_GROUPS,
            "main_group_labels": DOCUMENT_HISTORY_MAIN_GROUP_LABELS,
            "comparison_labels": DOCUMENT_HISTORY_COMPARISON_LABELS,
            "quick_classification_labels": DOCUMENT_HISTORY_QUICK_CLASSIFICATION_LABELS,
            "quick_classifications": DOCUMENT_HISTORY_QUICK_CLASSIFICATIONS,
            "audit_fields": DOCUMENT_HISTORY_AUDIT_FIELDS,
            "audit_field_labels": DOCUMENT_HISTORY_AUDIT_FIELD_LABELS,
            "status_options": all_statuses,
            "document_created": document_created,
        },
    )


@web_router.get("/v2-clean/fleet/{vehicle_id}/documents/new", response_class=HTMLResponse)
def clean_fleet_documents_new(request: Request, vehicle_id: int):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if not can_view_fleet(request):
        return RedirectResponse("/", status_code=303)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet", status_code=303)
        plate = normalize_identifier(vehicle.plate or vehicle.license_plate or "")
    return documents_new_page(
        request,
        vehicle_id=vehicle_id,
        plate=plate,
        return_url=f"/v2-clean/fleet/{vehicle_id}/documents",
    )


@web_router.get("/v2-clean/documents/new", response_class=HTMLResponse)
def clean_documents_new_page(
    request: Request,
    vehicle_id: int | None = None,
    plate: str = "",
    classification: str = "",
    document_type: str = "",
    status: str = "",
    source: str = "",
    title: str = "",
    supplier_name: str = "",
    customer_name: str = "",
    document_date: str = "",
    url_original: str = "",
    url_archive: str = "",
    entry_channel: str = "",
    source_sender: str = "",
    source_subject: str = "",
    task_id: str = "",
    workshop_process_id: str = "",
    import_batch_id: str = "",
    notes: str = "",
    return_url: str = "",
    error: str | None = None,
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if not can_view_fleet(request):
        return RedirectResponse("/", status_code=303)
    return documents_new_page(
        request,
        error=error,
        vehicle_id=vehicle_id,
        plate=plate,
        classification=classification,
        document_type=document_type,
        status=status,
        source=source,
        title=title,
        supplier_name=supplier_name,
        customer_name=customer_name,
        document_date=document_date,
        url_original=url_original,
        url_archive=url_archive,
        entry_channel=entry_channel,
        source_sender=source_sender,
        source_subject=source_subject,
        task_id=task_id,
        workshop_process_id=workshop_process_id,
        import_batch_id=import_batch_id,
        notes=notes,
        return_url=return_url or "/v2-clean/documents",
    )


@web_router.post("/v2-clean/documents/new", response_class=HTMLResponse)
def clean_documents_create(
    request: Request,
    title: str = Form(""),
    classification: str = Form("workshop"),
    document_type: str = Form("workshop_other"),
    status: str = Form("received"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    plate: str = Form(""),
    supplier_name: str = Form(""),
    customer_name: str = Form(""),
    vehicle_id: str = Form(""),
    task_id: str = Form(""),
    workshop_process_id: str = Form(""),
    import_batch_id: str = Form(""),
    notes: str = Form(""),
    return_url: str = Form(""),
    document_file: UploadFile | None = File(None),
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    return document_create(
        request,
        title=title,
        classification=classification,
        document_type=document_type,
        status=status,
        document_date=document_date,
        source=source,
        entry_channel=entry_channel,
        source_sender=source_sender,
        source_subject=source_subject,
        url_original=url_original,
        url_archive=url_archive,
        plate=plate,
        supplier_name=supplier_name,
        customer_name=customer_name,
        vehicle_id=vehicle_id,
        task_id=task_id,
        workshop_process_id=workshop_process_id,
        import_batch_id=import_batch_id,
        notes=notes,
        return_url=return_url,
        document_file=document_file,
    )


@web_router.get("/v2-clean/documents", response_class=HTMLResponse)
def clean_document_import_center(
    request: Request,
    imported: str | None = None,
    imported_count: int | None = None,
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if not can_view_fleet(request):
        return RedirectResponse("/", status_code=303)
    with SessionLocal() as db:
        structured_counts = {
            code: db.query(VehicleDocumentRecord).filter(VehicleDocumentRecord.main_group == code).count()
            for code, _label in DOCUMENT_HISTORY_STRUCTURED_GROUPS
        }
        vehicle_count = db.query(Vehicle).count()
    return templates.TemplateResponse(
        request,
        "clean_document_import_center.html",
        {
            "structured_groups": DOCUMENT_HISTORY_STRUCTURED_GROUPS,
            "structured_counts": structured_counts,
            "vehicle_count": vehicle_count,
            "imported": imported,
            "imported_count": imported_count,
        },
    )


@web_router.post("/v2-clean/documents/import/work-orders")
def clean_document_import_center_work_orders(request: Request, file: UploadFile = File(...)):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        tmp_path = save_uploaded_spreadsheet(file)
        try:
            imported_count = import_work_orders_xlsx(db, path=tmp_path, user_id=user_id)
            db.commit()
        finally:
            tmp_path.unlink(missing_ok=True)
    return RedirectResponse(f"/v2-clean/documents?imported=work_orders&imported_count={imported_count}", status_code=303)


@web_router.post("/v2-clean/documents/import/impros")
def clean_document_import_center_impros(request: Request, file: UploadFile = File(...)):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        tmp_path = save_uploaded_spreadsheet(file)
        try:
            imported_count = import_impros_xlsx(db, path=tmp_path, user_id=user_id)
            db.commit()
        finally:
            tmp_path.unlink(missing_ok=True)
    return RedirectResponse(f"/v2-clean/documents?imported=impros&imported_count={imported_count}", status_code=303)


@web_router.post("/v2-clean/documents/import/contracts")
def clean_document_import_center_contracts(request: Request, file: UploadFile = File(...)):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        tmp_path = save_uploaded_spreadsheet(file)
        try:
            imported_count = import_contracts_xlsx(db, path=tmp_path, user_id=user_id)
            db.commit()
        finally:
            tmp_path.unlink(missing_ok=True)
    return RedirectResponse(f"/v2-clean/documents?imported=contracts&imported_count={imported_count}", status_code=303)


@web_router.post("/v2-clean/fleet/{vehicle_id}/documents/import/work-orders")
def clean_fleet_documents_import_work_orders(request: Request, vehicle_id: int, file: UploadFile = File(...)):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        tmp_path = save_uploaded_spreadsheet(file)
        try:
            import_work_orders_xlsx(db, path=tmp_path, user_id=user_id)
            db.commit()
        finally:
            tmp_path.unlink(missing_ok=True)
    return RedirectResponse("/v2-clean/documents?imported=work_orders", status_code=303)


@web_router.post("/v2-clean/fleet/{vehicle_id}/documents/import/impros")
def clean_fleet_documents_import_impros(request: Request, vehicle_id: int, file: UploadFile = File(...)):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        tmp_path = save_uploaded_spreadsheet(file)
        try:
            import_impros_xlsx(db, path=tmp_path, user_id=user_id)
            db.commit()
        finally:
            tmp_path.unlink(missing_ok=True)
    return RedirectResponse("/v2-clean/documents?imported=impros", status_code=303)


@web_router.post("/v2-clean/fleet/{vehicle_id}/documents/import/contracts")
def clean_fleet_documents_import_contracts(request: Request, vehicle_id: int, file: UploadFile = File(...)):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        tmp_path = save_uploaded_spreadsheet(file)
        try:
            import_contracts_xlsx(db, path=tmp_path, user_id=user_id)
            db.commit()
        finally:
            tmp_path.unlink(missing_ok=True)
    return RedirectResponse("/v2-clean/documents?imported=contracts", status_code=303)


@web_router.post("/v2-clean/fleet/{vehicle_id}/documents/pending")
def clean_fleet_documents_create_pending(
    request: Request,
    vehicle_id: int,
    main_group: str = Form("invoices"),
    title: str = Form(""),
    document_date: str = Form(""),
    supplier_name: str = Form(""),
    raw_description: str = Form(""),
    process_reference: str = Form(""),
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet", status_code=303)
        create_archive_placeholder(
            db,
            vehicle_id=vehicle.id,
            main_group=main_group,
            title=title.strip() or ("Fatura pendente" if main_group == "invoices" else "Diagnóstico pendente"),
            document_date=parse_iso_or_dmy_date(document_date),
            supplier_name=supplier_name.strip() or None,
            raw_description=raw_description.strip() or None,
            process_reference=process_reference.strip() or None,
            user_id=user_id,
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/fleet/{vehicle_id}/documents?created=pending", status_code=303)


@web_router.post("/v2-clean/fleet/{vehicle_id}/documents/attach")
def clean_fleet_documents_attach_existing(
    request: Request,
    vehicle_id: int,
    record_id: int = Form(...),
    document_id: int = Form(...),
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        record = db.get(VehicleDocumentRecord, record_id)
        if not record or record.vehicle_id != vehicle_id:
            return RedirectResponse(f"/v2-clean/fleet/{vehicle_id}/documents", status_code=303)
        attach_document_to_record(db, record, document_id=document_id, user_id=user_id)
        db.commit()
    return RedirectResponse(f"/v2-clean/fleet/{vehicle_id}/documents?attached=1", status_code=303)


@web_router.post("/v2-clean/fleet/{vehicle_id}/documents/classify")
def clean_fleet_documents_add_classification(
    request: Request,
    vehicle_id: int,
    category: str = Form(...),
    value: str = Form(""),
    free_text: str = Form(""),
    record_id: int | None = Form(None),
    document_id: int | None = Form(None),
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        add_quick_classification(
            db,
            vehicle_id=vehicle_id,
            record_id=record_id,
            document_id=document_id,
            category=category,
            value=value.strip() or None,
            free_text=free_text.strip() or None,
            user_id=user_id,
        )
        db.commit()
    return RedirectResponse(f"/v2-clean/fleet/{vehicle_id}/documents?classified=1", status_code=303)


@web_router.post("/v2-clean/fleet/{vehicle_id}/documents/audit-field")
def clean_fleet_documents_save_audit_field(
    request: Request,
    vehicle_id: int,
    field_code: str = Form(...),
    value: str = Form(""),
    audited_on: str = Form(""),
    observation: str = Form(""),
    document_basis: str = Form(""),
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet", status_code=303)
        clean_value = value.strip() or None
        audited_value = clean_value
        if field_code == "effective_maintenance_count":
            try:
                audited_value = int(clean_value) if clean_value is not None else None
            except ValueError:
                audited_value = clean_value
        upsert_audit_field(
            db,
            vehicle_id=vehicle.id,
            field_code=field_code,
            value=audited_value,
            audited_on=parse_iso_or_dmy_date(audited_on),
            observation=observation.strip() or None,
            document_basis=document_basis.strip() or None,
            user_id=user_id,
        )
        if field_code == "real_start_date":
            sync_real_start_manual_field(db, vehicle.id, clean_value, user_id)
        db.commit()
    return RedirectResponse(f"/v2-clean/fleet/{vehicle_id}/documents?saved=audit", status_code=303)
@web_router.get("/v2-clean/fleet/{vehicle_id}", response_class=HTMLResponse)
def clean_fleet_detail(request: Request, vehicle_id: int):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if not can_view_fleet(request):
        return RedirectResponse("/", status_code=303)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet", status_code=303)
        context = clean_vehicle_display_context(db, vehicle)
        all_vehicle_documents = db.scalars(
            select(Document)
            .where(or_(Document.vehicle_id == vehicle.id, Document.plate == vehicle.plate))
            .order_by(Document.updated_at.desc(), Document.id.desc())
        ).all()
        documents = all_vehicle_documents[:8]
        document_summary = clean_vehicle_document_summary(all_vehicle_documents)
        tasks = db.scalars(
            select(Task)
            .where(Task.plate == vehicle.plate, Task.status.not_in(["closed", "resolved", "cancelled"]))
            .order_by(Task.updated_at.desc(), Task.id.desc())
            .limit(8)
        ).all()
        audits = db.scalars(
            select(VehicleHistoryAudit)
            .where(VehicleHistoryAudit.vehicle_id == vehicle.id)
            .order_by(VehicleHistoryAudit.updated_at.desc(), VehicleHistoryAudit.id.desc())
            .limit(6)
        ).all()
        document_counts = {
            row[0] or "sem_classificacao": row[1]
            for row in db.execute(
                select(Document.classification, func.count()).where(
                    or_(Document.vehicle_id == vehicle.id, Document.plate == vehicle.plate)
                ).group_by(Document.classification)
            ).all()
        }
    return templates.TemplateResponse(
        request,
        "clean_fleet_detail.html",
        {
            "ctx": context,
            "documents": documents,
            "tasks": tasks,
            "audits": audits,
            "document_counts": document_counts,
            "document_summary": document_summary,
            "document_group_labels": CLEAN_FLEET_DOCUMENT_GROUP_LABELS,
        },
    )


@web_router.post("/v2-clean/fleet/{vehicle_id}/real-start", response_class=HTMLResponse)
def clean_fleet_update_real_start(
    request: Request,
    vehicle_id: int,
    real_start_date: str = Form(""),
    return_url: str = Form(""),
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_return_url = return_url.strip()
    if not clean_return_url.startswith("/v2-clean/") or clean_return_url.startswith("//"):
        clean_return_url = f"/v2-clean/fleet/{vehicle_id}"

    clean_value = real_start_date.strip()
    parsed_date = parse_optional_date(clean_value) if clean_value else None
    if clean_value and not parsed_date:
        separator = "&" if "?" in clean_return_url else "?"
        return RedirectResponse(f"{clean_return_url}{separator}error=invalid_real_start", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/v2-clean/fleet", status_code=303)
        before = vehicle_manual_values(db, vehicle.id)
        stored_value = parsed_date.isoformat() if parsed_date else ""
        upsert_vehicle_manual_field(db, vehicle.id, "real_start_date", stored_value, user_id)
        record_audit(
            db,
            action="vehicle.real_start_date.updated",
            entity_type="vehicle",
            entity_id=vehicle.id,
            detail=f"Início real atualizado para {stored_value or 'por validar'}",
            before_json={"real_start_date": before.get("real_start_date")},
            after_json={"real_start_date": stored_value},
            user_id=user_id,
        )
        db.commit()

    separator = "&" if "?" in clean_return_url else "?"
    return RedirectResponse(f"{clean_return_url}{separator}saved=real_start", status_code=303)


@web_router.post("/v2-clean/workshop-entry", response_class=HTMLResponse)
async def clean_workshop_entry_save(request: Request):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    form = await request.form()
    process_id = parse_int_from_text(str(form.get("process_id") or ""))
    action = str(form.get("action") or "save")
    now = datetime.now(UTC)
    user_id = get_web_user_id(request)
    is_historical = str(form.get("process_mode") or "").strip().lower() == "historical"
    submitted_plate = normalize_identifier(str(form.get("plate") or ""))

    if not process_id and not submitted_plate:
        suffix = clean_workshop_query_suffix(historical=is_historical, new_entry=True)
        separator = "&" if suffix else "?"
        return RedirectResponse(f"/v2-clean/workshop-entry{suffix}{separator}error=missing_plate", status_code=303)

    with SessionLocal() as db:
        process: WorkshopPhasedProcess | None = None
        if process_id:
            process = db.get(WorkshopPhasedProcess, process_id)
            if not process:
                suffix = clean_workshop_query_suffix(historical=is_historical, new_entry=True)
                return RedirectResponse(f"/v2-clean/workshop-entry{suffix}", status_code=303)
            if clean_workshop_process_is_readonly(process):
                return RedirectResponse(f"{clean_workshop_process_url(process)}&readonly=1", status_code=303)
        else:
            process = clean_workshop_create_process(
                db,
                request=request,
                plate=submitted_plate,
                historical=is_historical,
            )
            process_id = process.id

        if submitted_plate and submitted_plate != (process.plate_snapshot or ""):
            vehicle = clean_workshop_find_vehicle(db, plate=submitted_plate)
            process.vehicle_id = vehicle.id if vehicle else None
            process.plate_snapshot = submitted_plate
            process.title = f"{clean_workshop_process_reference(process)} · {submitted_plate}"

        phase = clean_workshop_get_phase(db, process.id, "entrada")
        if not phase:
            phase = WorkshopPhasedProcessPhase(
                process_id=process.id,
                phase_code="entrada",
                name="Entrada",
                status="pending_review",
                sort_order=1,
                started_at=now,
                data_json={},
            )
            db.add(phase)
            db.flush()

        entry_reasons = [str(value) for value in form.getlist("entry_reasons") if str(value).strip()]
        physical_checks = {
            code: str(form.get(code) or "not_checked")
            for code in CLEAN_WORKSHOP_ENTRY_PHYSICAL_CHECKS
        }
        minimum_checks = {
            code: str(form.get(code) or "not_checked")
            for code in CLEAN_WORKSHOP_ENTRY_MINIMUM_CHECKS
        }
        stored_uploads = await clean_workshop_store_entry_uploads(process.id, form)
        entry_data = dict(phase.data_json or {})
        existing_uploads = entry_data.get("uploads")
        if not isinstance(existing_uploads, list):
            existing_uploads = []
        entry_data.update(
            {
                "entry_reasons": entry_reasons,
                "short_description": str(form.get("short_description") or "").strip(),
                "requested_service": str(form.get("requested_service") or "").strip(),
                "entry_km": str(form.get("entry_km") or "").strip(),
                "entry_km_source": "manual" if str(form.get("entry_km") or "").strip() else "",
                "reported_by": str(form.get("reported_by") or "").strip(),
                "priority": str(form.get("priority") or "").strip(),
                "can_drive": str(form.get("can_drive") or "").strip(),
                "historical_intervention_date": str(form.get("historical_intervention_date") or "").strip(),
                "historical_km": str(form.get("historical_km") or "").strip(),
                "historical_supplier": str(form.get("historical_supplier") or "").strip(),
                "historical_confidence": str(form.get("historical_confidence") or "").strip(),
                "physical_checks": physical_checks,
                "physical_check_note": str(form.get("physical_check_note") or "").strip(),
                "expected_exit": str(form.get("expected_exit") or "").strip(),
                "validation_notes": str(form.get("validation_notes") or "").strip(),
                "minimum_checks": minimum_checks,
                "uploads": [*existing_uploads, *stored_uploads],
                "saved_at": now.isoformat(),
                "saved_by_id": user_id,
            }
        )
        if action == "advance" and parse_int_from_text(entry_data.get("entry_km")) is None:
            phase.data_json = entry_data
            phase.status = "in_progress"
            process.current_phase_code = "entrada"
            db.commit()
            return RedirectResponse(f"/v2-clean/workshop-entry?process_id={process_id}&error=missing_km", status_code=303)
        phase.data_json = entry_data
        phase.status = "completed" if action == "advance" else "in_progress"
        phase.started_at = phase.started_at or now
        if action == "advance":
            phase.completed_at = now
            phase.completed_by_id = user_id
            process.current_phase_code = "validacao"
            validation_phase = clean_workshop_get_phase(db, process.id, "validacao")
            if validation_phase and validation_phase.status == "not_started":
                validation_phase.status = "pending_review"
                validation_phase.started_at = now
        else:
            process.current_phase_code = "entrada"

        entry_km = parse_int_from_text(entry_data.get("entry_km"))
        if entry_km is not None:
            process.initial_km = entry_km
        process.priority = str(entry_data.get("priority") or "Normal").lower()
        process.initial_observation = (
            str(entry_data.get("short_description") or entry_data.get("requested_service") or "").strip()
            or process.initial_observation
        )
        process.metadata_json = {
            **(process.metadata_json or {}),
            "entry_reasons": entry_reasons,
            "can_drive": entry_data.get("can_drive"),
            "expected_exit": entry_data.get("expected_exit"),
        }
        db.commit()

    if action == "advance":
        return RedirectResponse(f"/v2-clean/workshop/validacao?process_id={process_id}", status_code=303)
    return RedirectResponse(f"/v2-clean/workshop-entry?process_id={process_id}&saved=1", status_code=303)


@web_router.get("/v2-clean/workshop-entry", response_class=HTMLResponse)
def clean_workshop_entry(
    request: Request,
    process_id: int | None = None,
    vehicle_id: int | None = None,
    plate: str | None = None,
    historical: bool = False,
    new: bool = False,
    saved: bool = False,
    error: str | None = None,
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    user_name = "Utilizador atual"
    user_id = get_web_user_id(request)
    if user_id:
        with SessionLocal() as db:
            user = db.get(User, user_id)
            if user:
                user_name = user.name or user.email
    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id) if process_id else None
        saved_entry: dict[str, object] = {}
        if process:
            historical = process.creation_mode == "historical"
            query_suffix = clean_workshop_query_suffix(process_id=process.id)
            vehicle_context = clean_workshop_context_for_process(db, process)
            entry_phase = clean_workshop_get_phase(db, process.id, "entrada")
            saved_entry = dict(entry_phase.data_json or {}) if entry_phase and entry_phase.data_json else {}
            if (
                saved_entry.get("entry_km")
                and saved_entry.get("entry_km_source") != "manual"
                and clean_km(saved_entry.get("entry_km")) == clean_km(vehicle_context.get("entry_km"))
            ):
                saved_entry["entry_km"] = ""
        else:
            query_suffix = clean_workshop_query_suffix(
                vehicle_id=vehicle_id,
                plate=plate,
                historical=historical,
            )
            vehicle_context = clean_workshop_vehicle_context(db, vehicle_id=vehicle_id, plate=plate)
        workshop_admin = clean_workshop_admin_context(db, request, process)
    return templates.TemplateResponse(
        request,
        "clean_workshop_entry.html",
        {
            "entry_reasons": CLEAN_WORKSHOP_ENTRY_REASONS,
            "current_entry_timestamp": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "current_user_name": user_name,
            "workshop_steps": clean_workshop_steps(query_suffix),
            "vehicle_context": vehicle_context,
            "is_historical": historical,
            "is_new_entry": False,
            "workshop_process": process,
            "workshop_admin": workshop_admin,
            "active_step": "entrada",
            "next_phase_url": f"/v2-clean/workshop/validacao{query_suffix}",
            "new_entry_url": f"/v2-clean/workshop-entry{clean_workshop_query_suffix(vehicle_id=vehicle_id, plate=plate)}",
            "new_historical_url": f"/v2-clean/workshop-entry{clean_workshop_query_suffix(vehicle_id=vehicle_id, plate=plate, historical=True)}",
            "saved_entry": saved_entry,
            "entry_substep_status": clean_workshop_entry_substep_status(saved_entry),
            "saved": saved,
            "error": error,
        },
    )


@web_router.get("/v2-clean/workshop/{phase}", response_class=HTMLResponse)
def clean_workshop_phase(
    request: Request,
    phase: str,
    process_id: int | None = None,
    vehicle_id: int | None = None,
    plate: str | None = None,
    selected_report_id: int | None = None,
    historical: bool = False,
    new: bool = False,
    error: str | None = None,
):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    if new and not process_id:
        query_suffix = clean_workshop_query_suffix(vehicle_id=vehicle_id, plate=plate, historical=historical, new_entry=True)
        return RedirectResponse(f"/v2-clean/workshop-entry{query_suffix}", status_code=303)
    query_suffix = clean_workshop_query_suffix(process_id=process_id, vehicle_id=vehicle_id, plate=plate, historical=historical)
    if phase in {"entrada", "entry"}:
        return RedirectResponse(f"/v2-clean/workshop-entry{query_suffix}", status_code=303)
    phase = CLEAN_WORKSHOP_PHASE_ALIASES.get(phase, phase)
    phase_config = CLEAN_WORKSHOP_PHASES.get(phase)
    if not phase_config:
        return RedirectResponse(f"/v2-clean/workshop-entry{query_suffix}", status_code=303)
    phase_data: dict[str, object] = {}
    phase_form: dict[str, object] = {}
    entry_form: dict[str, object] = {}
    validation_prerequisites: list[dict[str, str | None]] = []
    technical_reports: list[WorkshopPhasedTechnicalReport] = []
    technical_reading_groups: list[dict[str, object]] = []
    vehicle_detail_href = "/v2-clean/fleet"
    vehicle_documents_href = "/v2-clean/fleet"
    task_board_href = "/task-board/manage"
    audit_href = "/v2-clean/processes"
    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id) if process_id else None
        if process:
            historical = process.creation_mode == "historical"
            query_suffix = clean_workshop_query_suffix(process_id=process.id)
            vehicle_context = clean_workshop_context_for_process(db, process)
            if process.vehicle_id:
                vehicle_detail_href = f"/v2-clean/fleet/{process.vehicle_id}"
                vehicle_documents_href = f"/v2-clean/fleet/{process.vehicle_id}/documents"
                history_audit = db.scalar(
                    select(VehicleHistoryAudit)
                    .where(VehicleHistoryAudit.vehicle_id == process.vehicle_id, VehicleHistoryAudit.status != "closed")
                    .order_by(VehicleHistoryAudit.updated_at.desc(), VehicleHistoryAudit.id.desc())
                )
                if history_audit:
                    audit_href = f"/fleet/{history_audit.vehicle_id}/history-audits/{history_audit.id}"
            technical_reports = db.scalars(
                select(WorkshopPhasedTechnicalReport)
                .where(WorkshopPhasedTechnicalReport.process_id == process.id)
                .order_by(WorkshopPhasedTechnicalReport.id.desc())
            ).all()
            phase_row = clean_workshop_get_phase(db, process.id, phase)
            if phase_row and isinstance(phase_row.data_json, dict):
                phase_data = dict(phase_row.data_json)
                raw_form = phase_data.get("form_snapshot")
                if isinstance(raw_form, dict):
                    phase_form = raw_form
            entry_phase = clean_workshop_get_phase(db, process.id, "entrada")
            if entry_phase and isinstance(entry_phase.data_json, dict):
                entry_form = dict(entry_phase.data_json)
            validation_prerequisites = clean_workshop_validation_prerequisites(db, process, vehicle_context)
        else:
            vehicle_context = clean_workshop_vehicle_context(db, vehicle_id=vehicle_id, plate=plate)
            validation_prerequisites = clean_workshop_validation_prerequisites(db, None, vehicle_context)
        workshop_admin = clean_workshop_admin_context(db, request, process)
    technical_reading_groups = clean_workshop_technical_reading_groups(technical_reports)
    saved_substeps = clean_workshop_saved_substeps(phase_data)
    phase_uploads = phase_data.get("uploads") if isinstance(phase_data.get("uploads"), list) else []
    selected_reading_report_id = str(selected_report_id) if selected_report_id else ""
    if selected_reading_report_id and not any(
        str(group.get("report_id")) == selected_reading_report_id for group in technical_reading_groups
    ):
        selected_reading_report_id = ""
    if not selected_reading_report_id and technical_reading_groups:
        selected_reading_report_id = str(technical_reading_groups[0].get("report_id") or "")
    phase_nav = clean_workshop_phase_nav(phase, query_suffix)
    prerequisite_warning_count = sum(1 for item in validation_prerequisites if item.get("impact_class") == "warn")
    return templates.TemplateResponse(
        request,
        "clean_workshop_phase.html",
        {
            "phase_key": phase,
            "phase": phase_config,
            "workshop_steps": clean_workshop_steps(query_suffix),
            "vehicle_context": vehicle_context,
            "is_historical": historical,
            "workshop_process": process,
            "workshop_admin": workshop_admin,
            "active_step": phase,
            "phase_data": phase_data,
            "phase_form": phase_form,
            "phase_uploads": phase_uploads,
            "validation_service_rows": clean_workshop_validation_rows(phase_form, entry_form),
            "validation_substep_status": clean_workshop_validation_substep_status(
                phase_form,
                phase_saved=bool(phase_data.get("saved_at")),
                prerequisite_warning_count=prerequisite_warning_count,
                saved_substeps=saved_substeps,
            ),
            "validation_prerequisites": validation_prerequisites,
            "validation_observation": clean_form_value(phase_form, "validation_observation"),
            "technical_reports": technical_reports,
            "technical_report_summary": clean_workshop_technical_report_summary(technical_reports),
            "technical_reading_rows": clean_workshop_technical_reading_rows(technical_reports),
            "technical_reading_groups": technical_reading_groups,
            "selected_reading_report_id": selected_reading_report_id,
            "diagnostic_substep_status": clean_workshop_diagnostic_substep_status(technical_reports),
            "diagnostic_form_status": clean_workshop_diagnostic_form_status(
                phase_form,
                technical_reports,
                saved_substeps,
            ),
            "inspection_form_status": clean_workshop_inspection_form_status(phase_form, saved_substeps),
            "audit_form_status": clean_workshop_audit_form_status(phase_form, saved_substeps),
            "repair_form_status": clean_workshop_repair_form_status(phase_form, saved_substeps),
            "closure_form_status": clean_workshop_closure_form_status(phase_form, saved_substeps),
            "vehicle_detail_href": vehicle_detail_href,
            "vehicle_documents_href": vehicle_documents_href,
            "task_board_href": task_board_href,
            "audit_href": audit_href,
            "phase_error": CLEAN_WORKSHOP_PHASE_ERROR_MESSAGES.get(error or ""),
            "phase_print_report": {
                "validacao": ("diagnostic-order", "Imprimir ordem de diagnóstico"),
                "auditoria": ("audit-validation", "Imprimir relatório de auditoria"),
                "reparacao": ("repair-order", "Imprimir ordem de reparação"),
                "fecho": ("final-report", "Imprimir relatório final"),
            }.get(phase),
            **phase_nav,
        },
    )


CLEAN_WORKSHOP_PRINT_REPORTS = {
    "diagnostic-order": {
        "document_number": "1/4",
        "title": "Ordem de Diagnóstico Técnico",
        "stage": "Saída da Validação Administrativa",
        "status": "Para execução",
    },
    "audit-validation": {
        "document_number": "2/4",
        "title": "Relatório para Auditoria e Validação",
        "stage": "Saída do Diagnóstico e Inspeção",
        "status": "Em validação",
    },
    "repair-order": {
        "document_number": "3/4",
        "title": "Ordem de Reparação",
        "stage": "Saída da Auditoria e Validação",
        "status": "Autorizado",
    },
    "final-report": {
        "document_number": "4/4",
        "title": "Relatório Final do Processo",
        "stage": "Validação e Fecho",
        "status": "Versão final",
    },
}


def clean_workshop_phase_form_for_print(
    db: Session,
    process_id: int,
    phase_code: str,
) -> dict[str, object]:
    phase = clean_workshop_get_phase(db, process_id, phase_code)
    if not phase or not isinstance(phase.data_json, dict):
        return {}
    if phase_code == "entrada":
        return dict(phase.data_json)
    snapshot = phase.data_json.get("form_snapshot")
    return dict(snapshot) if isinstance(snapshot, dict) else {}


@web_router.get("/v2-clean/workshop/{process_id}/print/{report_type}", response_class=HTMLResponse)
def clean_workshop_print_report(request: Request, process_id: int, report_type: str):
    denied = clean_experience_denied(request)
    if denied:
        return denied
    report_config = CLEAN_WORKSHOP_PRINT_REPORTS.get(report_type)
    if not report_config:
        return Response(status_code=404)

    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return Response(status_code=404)
        vehicle_context = clean_workshop_context_for_process(db, process)
        phase_forms = {
            "entrada": clean_workshop_phase_form_for_print(db, process.id, "entrada"),
            **{
                phase_code: clean_workshop_phase_form_for_print(db, process.id, phase_code)
                for phase_code in CLEAN_WORKSHOP_PHASES
            },
        }
        reports = db.scalars(
            select(WorkshopPhasedTechnicalReport)
            .where(
                WorkshopPhasedTechnicalReport.process_id == process.id,
                ~WorkshopPhasedTechnicalReport.status.in_({"voided", "superseded"}),
            )
            .order_by(WorkshopPhasedTechnicalReport.id)
        ).all()
        alerts = db.scalars(
            select(WorkshopPhasedProcessAlert)
            .where(WorkshopPhasedProcessAlert.process_id == process.id)
            .order_by(WorkshopPhasedProcessAlert.id)
        ).all()
        process_services = db.scalars(
            select(WorkshopPhasedProcessService)
            .where(WorkshopPhasedProcessService.process_id == process.id)
            .order_by(WorkshopPhasedProcessService.sort_order, WorkshopPhasedProcessService.id)
        ).all()
        history_services: list[VehicleHistoryAuditService] = []
        if process.vehicle_id:
            history_services = db.scalars(
                select(VehicleHistoryAuditService)
                .join(VehicleHistoryAudit, VehicleHistoryAudit.id == VehicleHistoryAuditService.audit_id)
                .where(VehicleHistoryAudit.vehicle_id == process.vehicle_id)
                .order_by(
                    VehicleHistoryAuditService.service_date.desc(),
                    VehicleHistoryAuditService.id.desc(),
                )
                .limit(8)
            ).all()

        repair_form = phase_forms.get("reparacao", {})
        material_rows = []
        for index in range(1, 9):
            material_rows.append(
                {
                    "material": clean_form_value(repair_form, f"repair_material_{index}_name"),
                    "reference": clean_form_value(repair_form, f"repair_material_{index}_reference"),
                    "quantity": clean_form_value(repair_form, f"repair_material_{index}_quantity"),
                    "origin": clean_form_value(repair_form, f"repair_material_{index}_origin"),
                }
            )

        return templates.TemplateResponse(
            request,
            "clean_workshop_print_report.html",
            {
                "report_type": report_type,
                "report": report_config,
                "process": process,
                "vehicle_context": vehicle_context,
                "entry": phase_forms.get("entrada", {}),
                "validation": phase_forms.get("validacao", {}),
                "diagnostic": phase_forms.get("diagnostico", {}),
                "inspection": phase_forms.get("inspecao", {}),
                "audit": phase_forms.get("auditoria", {}),
                "repair": repair_form,
                "closure": phase_forms.get("fecho", {}),
                "technical_reports": reports,
                "technical_readings": clean_workshop_technical_reading_rows(reports),
                "process_alerts": alerts,
                "process_services": process_services,
                "history_services": history_services,
                "material_rows": material_rows,
                "printed_at": datetime.now().strftime("%d/%m/%Y %H:%M"),
                "return_url": clean_workshop_process_url(process),
            },
        )


@web_router.post("/v2-clean/workshop/{process_id}/cancel", response_class=HTMLResponse)
def clean_workshop_cancel_process(
    request: Request,
    process_id: int,
    reason: str = Form(""),
    observation: str = Form(""),
    task_action: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    clean_reason = reason.strip()
    clean_observation = observation.strip()

    now = datetime.now(UTC)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        process_url = clean_workshop_process_url(process)
        if not clean_reason or task_action not in {"keep", "cancel"}:
            return RedirectResponse(f"{process_url}&admin_error=cancel_required", status_code=303)
        if not can_manage_admin(db, user):
            return RedirectResponse(f"{process_url}&admin_error=forbidden", status_code=303)
        if process.status == "closed":
            return RedirectResponse(f"{process_url}&admin_error=reopen_closed_first", status_code=303)
        if process.status == "cancelled":
            return RedirectResponse(f"{process_url}&cancelled=1", status_code=303)

        prior_status = process.status
        metadata = dict(process.metadata_json or {})
        status_history = list(metadata.get("status_history") or [])
        cancellation = {
            "active": True,
            "reason": clean_reason,
            "observation": clean_observation,
            "cancelled_at": now.isoformat(),
            "cancelled_by_id": user_id,
            "cancelled_by": (user.name or user.email) if user else f"Utilizador #{user_id}",
            "prior_status": prior_status,
            "prior_phase": process.current_phase_code or "entrada",
            "task_action": task_action,
        }
        status_history.append({"from": prior_status, "to": "cancelled", **cancellation})
        metadata["cancellation"] = cancellation
        metadata["status_history"] = status_history
        process.metadata_json = metadata
        process.status = "cancelled"
        process.closed_at = now

        open_tasks = db.scalars(
            select(Task).where(
                Task.entity_type == "workshop_phased_process",
                Task.entity_id == str(process.id),
                Task.closed_at.is_(None),
                ~Task.status.in_(TASK_ARCHIVE_STATUSES),
            )
        ).all()
        if task_action == "cancel":
            for task in open_tasks:
                old_status = task.status
                task.status = "cancelled"
                task.closed_at = now
                db.add(
                    TaskHistory(
                        task_id=task.id,
                        user_id=user_id,
                        field_name="status",
                        old_value=old_status,
                        new_value="cancelled",
                    )
                )

        open_alerts = db.scalars(
            select(WorkshopPhasedProcessAlert).where(
                WorkshopPhasedProcessAlert.process_id == process.id,
                WorkshopPhasedProcessAlert.status == "open",
            )
        ).all()
        for alert in open_alerts:
            alert.status = "resolved"
            alert.resolved_at = now
            alert.resolved_by_id = user_id

        record_audit(
            db,
            action="workshop.process.cancelled",
            entity_type="workshop_phased_process",
            entity_id=process.id,
            detail=f"Processo cancelado: {clean_reason}",
            user_id=user_id,
            before_json={"status": prior_status, "open_tasks": len(open_tasks)},
            after_json={"status": "cancelled", "task_action": task_action, "observation": clean_observation},
        )
        db.commit()
        return RedirectResponse(f"{process_url}&cancelled=1", status_code=303)


@web_router.post("/v2-clean/workshop/{process_id}/reopen", response_class=HTMLResponse)
def clean_workshop_reopen_process(
    request: Request,
    process_id: int,
    justification: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    clean_justification = justification.strip()

    now = datetime.now(UTC)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        process_url = clean_workshop_process_url(process)
        if not clean_justification:
            return RedirectResponse(f"{process_url}&admin_error=reopen_required", status_code=303)
        if not can_manage_admin(db, user):
            return RedirectResponse(f"{process_url}&admin_error=forbidden", status_code=303)
        if process.status not in {"closed", "cancelled"}:
            return RedirectResponse(f"{process_url}&admin_error=not_final", status_code=303)

        old_status = process.status
        metadata = dict(process.metadata_json or {})
        cancellation = dict(metadata.get("cancellation") or {})
        restored_status = str(cancellation.get("prior_status") or "open") if old_status == "cancelled" else "open"
        if restored_status in {"closed", "cancelled"}:
            restored_status = "open"
        status_history = list(metadata.get("status_history") or [])
        reopening = {
            "from": old_status,
            "to": restored_status,
            "justification": clean_justification,
            "reopened_at": now.isoformat(),
            "reopened_by_id": user_id,
            "reopened_by": (user.name or user.email) if user else f"Utilizador #{user_id}",
        }
        status_history.append(reopening)
        if cancellation:
            cancellation.update({"active": False, **reopening})
            metadata["cancellation"] = cancellation
        metadata["status_history"] = status_history
        process.metadata_json = metadata
        process.status = restored_status
        process.closed_at = None

        record_audit(
            db,
            action="workshop.process.reopened",
            entity_type="workshop_phased_process",
            entity_id=process.id,
            detail=f"Processo reaberto: {clean_justification}",
            user_id=user_id,
            before_json={"status": old_status},
            after_json={"status": restored_status},
        )
        db.commit()
        return RedirectResponse(f"{process_url}&reopened=1", status_code=303)


@web_router.post("/v2-clean/workshop/{process_id}/records", response_class=HTMLResponse)
def clean_workshop_create_record(
    request: Request,
    process_id: int,
    record_type: str = Form("task"),
    phase: str = Form("entrada"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    is_problem = record_type == "problem"
    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        if clean_workshop_process_is_readonly(process):
            return RedirectResponse(f"{clean_workshop_process_url(process)}&readonly=1", status_code=303)

        phase_label = CLEAN_WORKSHOP_PHASES.get(phase, {}).get("title", phase.title())
        process_ref = f"OFI-{process.created_at.year if process.created_at else datetime.now().year}-{process.id:06d}"
        plate = process.plate_snapshot or "Sem matrícula"
        kind_label = "Problema" if is_problem else "Tarefa"
        task = Task(
            title=f"{kind_label} oficina · {plate} · {phase_label}",
            description=(
                f"Criado a partir do processo {process_ref}, fase {phase_label}. "
                "Completar descrição, responsável e prazo no Centro de Tarefas."
            ),
            task_type="workshop_problem" if is_problem else "workshop_task",
            source="workshop_v2_clean",
            category="workshop",
            subcategory="problem" if is_problem else "workshop_process",
            status="new",
            priority="high" if is_problem else "normal",
            plate=process.plate_snapshot,
            external_source_id=f"workshop:{process.id}:{phase}:{record_type}:{datetime.now(UTC).timestamp()}",
            entity_type="workshop_phased_process",
            entity_id=str(process.id),
            team_id=default_team_id(db, "workshop"),
            created_by_id=user_id,
        )
        db.add(task)
        db.flush()
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        record_audit(
            db,
            action="task.create",
            entity_type="task",
            entity_id=task.id,
            detail=f"{kind_label} criado a partir de {process_ref} ({phase_label})",
            user_id=user_id,
        )
        db.commit()
        task_id = task.id

    return RedirectResponse(f"/task-board/{task_id}", status_code=303)


@web_router.post("/v2-clean/workshop/{phase}/save", response_class=HTMLResponse)
async def clean_workshop_phase_save(request: Request, phase: str):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    phase = CLEAN_WORKSHOP_PHASE_ALIASES.get(phase, phase)
    phase_config = CLEAN_WORKSHOP_PHASES.get(phase)
    if not phase_config:
        return RedirectResponse("/v2-clean/workshop", status_code=303)

    form = await request.form()
    process_id = parse_int_from_text(str(form.get("process_id") or ""))
    if not process_id:
        return RedirectResponse(clean_workshop_phase_path(phase), status_code=303)

    action = str(form.get("action") or "save")
    current_substep = str(form.get("current_substep") or "").strip()
    known_substeps = clean_workshop_substeps(phase)
    if current_substep not in known_substeps:
        current_substep = known_substeps[0] if known_substeps else ""
    now = datetime.now(UTC)
    user_id = get_web_user_id(request)

    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        if clean_workshop_process_is_readonly(process):
            return RedirectResponse(f"{clean_workshop_process_url(process)}&readonly=1", status_code=303)

        phase_row = clean_workshop_get_phase(db, process.id, phase)
        if not phase_row:
            step_index = next(
                (index for index, step in enumerate(CLEAN_WORKSHOP_STEP_DEFS, start=1) if step["key"] == phase),
                1,
            )
            phase_row = WorkshopPhasedProcessPhase(
                process_id=process.id,
                phase_code=phase,
                name=str(phase_config["title"]),
                status="pending_review",
                sort_order=step_index,
                started_at=now,
                data_json={},
            )
            db.add(phase_row)
            db.flush()

        form_snapshot: dict[str, object] = {}
        raw_form_state = form.get("form_state_json")
        if isinstance(raw_form_state, str) and raw_form_state.strip():
            try:
                decoded_state = json.loads(raw_form_state)
            except json.JSONDecodeError:
                decoded_state = None
            if isinstance(decoded_state, dict):
                for key, value in decoded_state.items():
                    if key in {"action", "process_id", "form_state_json", "current_substep"}:
                        continue
                    if isinstance(value, list):
                        form_snapshot[key] = [str(item) for item in value if item is not None]
                    elif value is None:
                        form_snapshot[key] = ""
                    else:
                        form_snapshot[key] = str(value)
        if not form_snapshot:
            for key in form.keys():
                if key in {"action", "process_id", "form_state_json", "current_substep"}:
                    continue
                values = [str(value) for value in form.getlist(key)]
                form_snapshot[key] = values if len(values) > 1 else (values[0] if values else "")

        phase_data = dict(phase_row.data_json or {})
        stored_uploads = await clean_workshop_store_phase_uploads(
            db,
            process,
            phase,
            form,
            user_id,
        )
        for upload in stored_uploads:
            status_update = CLEAN_WORKSHOP_UPLOAD_STATUS_UPDATES.get(str(upload.get("field") or ""))
            if status_update:
                form_snapshot[status_update[0]] = status_update[1]
        existing_uploads = phase_data.get("uploads")
        if not isinstance(existing_uploads, list):
            existing_uploads = []
        if stored_uploads:
            phase_data["uploads"] = [*existing_uploads, *stored_uploads]
        existing_snapshot = (
            dict(phase_data.get("form_snapshot") or {})
            if isinstance(phase_data.get("form_snapshot"), dict)
            else {}
        )
        if action in {"save_substep", "advance_substep"}:
            existing_snapshot.update(form_snapshot)
            form_snapshot = existing_snapshot

        saved_substeps = clean_workshop_saved_substeps(phase_data)
        if current_substep and action in {"save", "save_substep", "advance_substep", "advance"}:
            saved_substeps.add(current_substep)
        phase_data.update(
            {
                "form_snapshot": form_snapshot,
                "saved_substeps": sorted(saved_substeps),
                "saved_at": now.isoformat(),
                "saved_by_id": user_id,
                "last_action": action,
            }
        )
        phase_row.data_json = phase_data
        phase_row.started_at = phase_row.started_at or now

        if action == "advance":
            phase_reports = (
                db.scalars(
                    select(WorkshopPhasedTechnicalReport).where(
                        WorkshopPhasedTechnicalReport.process_id == process.id
                    )
                ).all()
                if phase == "diagnostico"
                else []
            )
            advance_error = clean_workshop_phase_advance_error(phase, form_snapshot, phase_reports)
            if advance_error:
                phase_row.status = "in_progress"
                process.current_phase_code = phase
                db.commit()
                redirect_url = (
                    f"{clean_workshop_phase_path(phase)}?process_id={process.id}"
                    f"&error={advance_error}"
                )
                if current_substep:
                    redirect_url = f"{redirect_url}#{current_substep}"
                return RedirectResponse(redirect_url, status_code=303)

            saved_substeps.update(known_substeps)
            phase_data["saved_substeps"] = sorted(saved_substeps)
            phase_row.data_json = phase_data
            phase_row.status = "completed"
            phase_row.completed_at = now
            phase_row.completed_by_id = user_id
            next_phase = clean_workshop_next_phase_key(phase)
            if next_phase:
                process.current_phase_code = next_phase
                next_phase_row = clean_workshop_get_phase(db, process.id, next_phase)
                if next_phase_row and next_phase_row.status == "not_started":
                    next_phase_row.status = "pending_review"
                    next_phase_row.started_at = now
                redirect_url = f"{clean_workshop_phase_path(next_phase)}?process_id={process.id}"
            else:
                process.status = "closed"
                process.closed_at = now
                redirect_url = f"{clean_workshop_phase_path(phase)}?process_id={process.id}&saved=1"
        elif action in {"save_substep", "advance_substep"}:
            target_substep = clean_workshop_next_substep_key(phase, current_substep) if current_substep else None
            if target_substep:
                phase_row.status = "in_progress"
                process.current_phase_code = phase
                redirect_url = f"{clean_workshop_phase_path(phase)}?process_id={process.id}&saved=1#{target_substep}"
            else:
                phase_reports = (
                    db.scalars(
                        select(WorkshopPhasedTechnicalReport).where(
                            WorkshopPhasedTechnicalReport.process_id == process.id
                        )
                    ).all()
                    if phase == "diagnostico"
                    else []
                )
                advance_error = clean_workshop_phase_advance_error(phase, form_snapshot, phase_reports)
                if advance_error:
                    phase_row.status = "in_progress"
                    process.current_phase_code = phase
                    db.commit()
                    redirect_url = (
                        f"{clean_workshop_phase_path(phase)}?process_id={process.id}"
                        f"&error={advance_error}"
                    )
                    if current_substep:
                        redirect_url = f"{redirect_url}#{current_substep}"
                    return RedirectResponse(redirect_url, status_code=303)

                saved_substeps.update(known_substeps)
                phase_data["saved_substeps"] = sorted(saved_substeps)
                phase_row.data_json = phase_data
                phase_row.status = "completed"
                phase_row.completed_at = now
                phase_row.completed_by_id = user_id
                next_phase = clean_workshop_next_phase_key(phase)
                if next_phase:
                    process.current_phase_code = next_phase
                    next_phase_row = clean_workshop_get_phase(db, process.id, next_phase)
                    if next_phase_row and next_phase_row.status == "not_started":
                        next_phase_row.status = "pending_review"
                        next_phase_row.started_at = now
                    redirect_url = f"{clean_workshop_phase_path(next_phase)}?process_id={process.id}"
                else:
                    process.status = "closed"
                    process.closed_at = now
                    redirect_url = f"{clean_workshop_phase_path(phase)}?process_id={process.id}&saved=1"
        else:
            phase_row.status = "in_progress"
            process.current_phase_code = phase
            redirect_url = f"{clean_workshop_phase_path(phase)}?process_id={process.id}&saved=1"
            if current_substep:
                redirect_url = f"{redirect_url}#{current_substep}"

        db.commit()

    return RedirectResponse(redirect_url, status_code=303)


@web_router.post("/v2-clean/workshop/{process_id}/technical-reports/upload", response_class=HTMLResponse)
async def clean_workshop_technical_report_upload(
    request: Request,
    process_id: int,
    report_code: str = Form(...),
    report_file: UploadFile = File(...),
    replace_report_id: int | None = Form(None),
):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    selected_report_code = report_code if report_code in CLEAN_WORKSHOP_REPORT_CODES else "other_reading"
    filename = Path(report_file.filename or "relatorio.pdf").name
    content = await report_file.read()
    if not content:
        return RedirectResponse(f"/v2-clean/workshop/diagnostico?process_id={process_id}&upload_error=empty", status_code=303)

    digest = hashlib.sha256(content).hexdigest()
    suffix = Path(filename).suffix or ".pdf"
    now = datetime.now(UTC)
    user_id = get_web_user_id(request)
    classification_error: str | None = None
    report_meta: dict[str, Any] = {}
    uploaded_report_id: int | None = None
    try:
        report_meta = classify_workshop_report_from_bytes(content, filename)
    except (RuntimeError, ValueError) as exc:
        classification_error = str(exc)

    detected_report_code = str(report_meta.get("report_code") or "").strip()
    clean_report_code = (
        detected_report_code
        if selected_report_code == "other_reading" and detected_report_code in CLEAN_WORKSHOP_REPORT_CODES
        else selected_report_code
    )
    report_label = (
        clean_workshop_report_display_label(clean_report_code, "Relatório de diagnóstico do veículo")
        if selected_report_code != "other_reading"
        else str(report_meta.get("report_name") or clean_workshop_report_display_label(clean_report_code, "Relatório de diagnóstico do veículo"))
    )
    reading_origin = str(report_meta.get("machine_origin") or "unknown_machine")
    reading_origin_detail = str(report_meta.get("machine_label") or "Origem por rever")
    suggested_file_name = str(report_meta.get("suggested_file_name") or "")
    stored_name = suggested_file_name or f"{clean_report_code}_{digest[:12]}{suffix}"

    with SessionLocal() as db:
        process = db.get(WorkshopPhasedProcess, process_id)
        if not process:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        if clean_workshop_process_is_readonly(process):
            return RedirectResponse(f"{clean_workshop_process_url(process)}&readonly=1", status_code=303)

        plate_value = (process.plate_snapshot or "").strip().upper()
        plate_folder = re.sub(r"[^A-Z0-9_-]+", "_", plate_value or f"PROCESSO_{process.id}")
        upload_dir = APP_PROJECT_ROOT / "uploads" / "vehicle_documents" / plate_folder / "diagnosticos"
        upload_dir.mkdir(parents=True, exist_ok=True)
        stored_name = Path(stored_name).name
        stored_path = upload_dir / stored_name
        if stored_path.exists():
            safe_stem = stored_path.stem
            stored_name = f"{safe_stem}_{digest[:8]}{stored_path.suffix or suffix}"
            stored_path = upload_dir / stored_name
        stored_path.write_bytes(content)

        extracted_values: dict[str, Any] = {}
        status = "pending_validation"
        extraction_error: str | None = None
        try:
            extracted_values = extract_workshop_report_values_from_bytes(content, clean_report_code, filename)
        except (RuntimeError, ValueError) as exc:
            status = "unable_to_read"
            extraction_error = str(exc)

        phase_row = clean_workshop_get_phase(db, process.id, "diagnostico")
        if phase_row and phase_row.status == "not_started":
            phase_row.status = "pending_review"
            phase_row.started_at = now
        document = db.scalar(select(Document).where(Document.storage_path == str(stored_path)))
        if document is None:
            document_identifier = (
                str(report_meta.get("vehicle_identifier") or "").strip()
                or plate_value
                or str(process.id)
            )
            document = Document(
                title=f"Diagnóstico - {report_label} - {document_identifier}",
                document_type="workshop_diagnostic",
                classification="technical",
                source="workshop_v2_clean",
                entry_channel="upload",
                source_subject=report_label,
                original_name=filename,
                file_name=stored_name,
                file_type=suffix.lstrip(".") or None,
                file_size=len(content),
                storage_provider="local",
                storage_path=str(stored_path),
                storage_key=digest,
                folder_path=suggest_workshop_process_document_folder(process, vehicle, "01_Diagnosticos"),
                status="unclassified",
                vehicle_id=process.vehicle_id,
                plate=process.plate_snapshot,
                uploaded_by_id=user_id,
            )
            db.add(document)
            db.flush()
            db.add(
                DocumentLink(
                    document_id=document.id,
                    entity_type="workshop_phased_process",
                    entity_id=str(process.id),
                    category=clean_report_code,
                )
            )
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="document.workshop_v2_upload_associated",
                    new_value=f"process={process.id}; report={clean_report_code}",
                    user_id=user_id,
                )
            )
        replacement_report = None
        if replace_report_id:
            replacement_report = db.get(WorkshopPhasedTechnicalReport, replace_report_id)
            if (
                not replacement_report
                or replacement_report.process_id != process.id
                or replacement_report.report_code != clean_report_code
                or replacement_report.status in {"voided", "superseded"}
            ):
                replacement_report = None
            else:
                replacement_report.status = "superseded"
                replacement_report.correction_json = {
                    "source": "v2-clean-replaced",
                    "replaced_at": now.isoformat(),
                    "replaced_by_id": user_id,
                }

        report = WorkshopPhasedTechnicalReport(
            process_id=process.id,
            phase_id=phase_row.id if phase_row else None,
            report_code=clean_report_code,
            report_name=report_label,
            reading_origin=reading_origin,
            reading_origin_detail=reading_origin_detail,
            report_moment="initial",
            status=status,
            original_document_id=document.id,
            original_link=str(stored_path),
            raw_values_json={
                "selected_report_code": selected_report_code,
                "detected_report_code": detected_report_code or None,
                "canonical_report_code": report_meta.get("canonical_report_code"),
                "detected_report_name": report_meta.get("report_name"),
                "machine_origin": report_meta.get("machine_origin"),
                "machine_prefix": report_meta.get("machine_prefix"),
                "machine_label": report_meta.get("machine_label"),
                "vehicle_identifier": report_meta.get("vehicle_identifier"),
                "vin_candidates": report_meta.get("vin_candidates"),
                "plate_candidates": report_meta.get("plate_candidates"),
                "report_date": report_meta.get("report_date"),
                "report_time": report_meta.get("report_time"),
                "path_hint": report_meta.get("path_hint"),
                "review_bucket": report_meta.get("review_bucket"),
                "storage_group": report_meta.get("storage_group"),
                "duplicate_key": report_meta.get("duplicate_key"),
                "possible_duplicate_key": report_meta.get("possible_duplicate_key"),
                "text_source": report_meta.get("text_source"),
                "suggested_file_name": suggested_file_name or None,
                "original_name": filename,
                "stored_name": stored_name,
                "sha256": digest,
                "document_id": document.id,
                "classification_error": classification_error,
                "extraction_error": extraction_error,
            },
            extracted_values_json=extracted_values,
            validated_values_json=None,
            correction_json=None,
            added_by_id=user_id,
            observations="Carregado na experiência v2-clean.",
        )
        db.add(report)
        db.flush()
        if replacement_report:
            replacement_report.correction_json = {
                **(replacement_report.correction_json or {}),
                "replaced_by_report_id": report.id,
            }
        uploaded_report_id = report.id
        db.add(
            DocumentLink(
                document_id=document.id,
                entity_type="workshop_phased_technical_report",
                entity_id=str(report.id),
                category=clean_report_code,
            )
        )
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="document.workshop_report_uploaded",
                new_value=status,
                user_id=user_id,
            )
        )
        process.current_phase_code = "diagnostico"
        db.commit()

    return RedirectResponse(
        f"/v2-clean/workshop/diagnostico?process_id={process_id}&report_uploaded=1&selected_report_id={uploaded_report_id or ''}#leituras",
        status_code=303,
    )


@web_router.get("/v2-clean/workshop/technical-reports/{report_id}/file")
def clean_workshop_technical_report_file(request: Request, report_id: int):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    with SessionLocal() as db:
        report = db.get(WorkshopPhasedTechnicalReport, report_id)
        if not report or not report.original_link:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        file_path = Path(str(report.original_link))
        if not file_path.is_absolute():
            file_path = APP_PROJECT_ROOT / file_path
        if not file_path.exists() or not file_path.is_file():
            return RedirectResponse(
                f"/v2-clean/workshop/diagnostico?process_id={report.process_id}&file_missing=1#leituras",
                status_code=303,
            )
        raw_values = report.raw_values_json if isinstance(report.raw_values_json, dict) else {}
        filename = str(raw_values.get("original_name") or file_path.name)
    return FileResponse(file_path, filename=filename)


@web_router.post("/v2-clean/workshop/technical-reports/{report_id}/validate")
async def clean_workshop_technical_report_validate(request: Request, report_id: int):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    form = await request.form()
    validation_mode = str(form.get("validation_mode") or "save_all")
    now = datetime.now(UTC)
    user_id = get_web_user_id(request)
    process_id: int | None = None
    selected_report_id: int | None = None

    with SessionLocal() as db:
        report = db.get(WorkshopPhasedTechnicalReport, report_id)
        if not report:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        process = db.get(WorkshopPhasedProcess, report.process_id)
        if clean_workshop_process_is_readonly(process):
            return RedirectResponse(f"{clean_workshop_process_url(process)}&readonly=1", status_code=303)
        selected_report_id = report.id

        report_ids = [str(value) for value in form.getlist("reading_report_id")]
        field_codes = [str(value) for value in form.getlist("reading_field_code")]
        corrected_values = [str(value) for value in form.getlist("reading_corrected_value")]
        statuses = [str(value) for value in form.getlist("reading_status")]
        observations = [str(value) for value in form.getlist("reading_observation")]

        validated_values = dict(report.validated_values_json or {}) if isinstance(report.validated_values_json, dict) else {}
        for index, form_report_id in enumerate(report_ids):
            if form_report_id != str(report.id):
                continue
            field_code = field_codes[index] if index < len(field_codes) else "manual_reading"
            corrected_value = corrected_values[index] if index < len(corrected_values) else ""
            status_value = statuses[index] if index < len(statuses) else "Por validar"
            observation = observations[index] if index < len(observations) else ""
            extracted_values = report.extracted_values_json if isinstance(report.extracted_values_json, dict) else {}
            validated_values[field_code] = {
                "extracted_value": extracted_values.get(field_code),
                "corrected_value": corrected_value.strip(),
                "status": status_value,
                "observation": observation.strip(),
                "validated_at": now.isoformat(),
                "validated_by_id": user_id,
            }

        if validation_mode == "accept_all":
            extracted_values = report.extracted_values_json if isinstance(report.extracted_values_json, dict) else {}
            field_codes_to_confirm = list(extracted_values) or ["manual_reading"]
            for field_code in field_codes_to_confirm:
                existing = validated_values.get(str(field_code))
                existing = dict(existing) if isinstance(existing, dict) else {}
                corrected_value = str(existing.get("corrected_value") or "").strip()
                validated_values[str(field_code)] = {
                    "extracted_value": extracted_values.get(str(field_code)),
                    "corrected_value": corrected_value,
                    "status": "Corrigido" if corrected_value else "OK",
                    "observation": str(existing.get("observation") or "").strip(),
                    "validated_at": now.isoformat(),
                    "validated_by_id": user_id,
                }
        elif validation_mode == "mark_unreadable":
            validated_values["manual_reading"] = {
                "extracted_value": None,
                "corrected_value": "",
                "status": "Não legível",
                "observation": "Leitura automática sem dados utilizáveis.",
                "validated_at": now.isoformat(),
                "validated_by_id": user_id,
            }

        report.validated_values_json = validated_values
        report.correction_json = {
            "source": "v2-clean",
            "updated_at": now.isoformat(),
            "updated_by_id": user_id,
        }
        report.validated_by_id = user_id
        extracted_values = report.extracted_values_json if isinstance(report.extracted_values_json, dict) else {}
        terminal_statuses = {"OK", "Corrigido", "Não legível", "Não aplicável"}
        field_statuses = [
            str((validated_values.get(str(field_code)) or {}).get("status") or "Por validar")
            for field_code in extracted_values
        ]
        if not field_statuses:
            field_statuses = [
                str((validated_values.get("manual_reading") or {}).get("status") or "Por validar")
            ]
        report_is_complete = bool(field_statuses) and all(status in terminal_statuses for status in field_statuses)
        report.validated_at = now if report_is_complete else None
        if not report_is_complete:
            report.status = "pending_validation"
        elif any(item.get("corrected_value") for item in validated_values.values() if isinstance(item, dict)):
            report.status = "corrected_manually"
        else:
            report.status = "validated_manually"

        process = db.get(WorkshopPhasedProcess, report.process_id)
        if process:
            process.current_phase_code = "diagnostico"
        db.commit()
        process_id = report.process_id

    return RedirectResponse(
        f"/v2-clean/workshop/diagnostico?process_id={process_id}&report_validated=1&selected_report_id={selected_report_id or ''}#leituras",
        status_code=303,
    )


@web_router.post("/v2-clean/workshop/technical-reports/{report_id}/void")
def clean_workshop_technical_report_void(request: Request, report_id: int):
    denied = clean_experience_denied(request)
    if denied:
        return denied

    now = datetime.now(UTC)
    user_id = get_web_user_id(request)
    with SessionLocal() as db:
        report = db.get(WorkshopPhasedTechnicalReport, report_id)
        if not report:
            return RedirectResponse("/v2-clean/workshop", status_code=303)
        process = db.get(WorkshopPhasedProcess, report.process_id)
        if clean_workshop_process_is_readonly(process):
            return RedirectResponse(f"{clean_workshop_process_url(process)}&readonly=1", status_code=303)
        process_id = report.process_id
        if report.status not in {"voided", "superseded"}:
            report.status = "voided"
            report.validated_at = None
            report.correction_json = {
                **(report.correction_json or {}),
                "source": "v2-clean-removed",
                "removed_at": now.isoformat(),
                "removed_by_id": user_id,
            }
            if report.original_document_id:
                db.add(
                    DocumentEvent(
                        document_id=report.original_document_id,
                        action="document.workshop_report_removed_from_process",
                        old_value=f"report={report.id}; status=active",
                        new_value=f"report={report.id}; status=voided",
                        user_id=user_id,
                    )
                )
            record_audit(
                db,
                action="workshop.report.void",
                entity_type="workshop_phased_technical_report",
                entity_id=report.id,
                detail=f"Relatório removido do processo {process_id}; documento preservado no arquivo.",
                user_id=user_id,
            )
            db.commit()

    return RedirectResponse(
        f"/v2-clean/workshop/diagnostico?process_id={process_id}&report_removed=1#relatorios",
        status_code=303,
    )


@web_router.get("/admin", response_class=HTMLResponse)
def admin_page(
    request: Request,
    user_created: str | None = None,
    access_updated: str | None = None,
    permissions_updated: str | None = None,
    error: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)
        if not can_manage_admin(db, user):
            return RedirectResponse("/", status_code=303)
        pilot_feedback_items = db.scalars(
            select(PilotFeedback).order_by(PilotFeedback.id.desc()).limit(20)
        ).all()
        pilot_feedback_user_ids = {item.user_id for item in pilot_feedback_items if item.user_id}
        pilot_feedback_users = (
            db.scalars(select(User).where(User.id.in_(pilot_feedback_user_ids))).all()
            if pilot_feedback_user_ids
            else []
        )
        pilot_feedback_counts = {
            "total": db.scalar(select(func.count()).select_from(PilotFeedback)) or 0,
            "open": db.scalar(
                select(func.count()).select_from(PilotFeedback).where(PilotFeedback.status == "open")
            )
            or 0,
            "tasks": db.scalar(
                select(func.count()).select_from(PilotFeedback).where(PilotFeedback.source_area == "tasks")
            )
            or 0,
            "workshop": db.scalar(
                select(func.count()).select_from(PilotFeedback).where(PilotFeedback.source_area == "workshop")
            )
            or 0,
        }
        users = db.scalars(select(User).order_by(User.name, User.email).limit(100)).all()
        roles = db.scalars(select(Role).order_by(Role.name, Role.code)).all()
        permissions = [
            permission
            for permission in db.scalars(select(Permission).order_by(Permission.code)).all()
            if not permission.code.startswith("tasks.management.")
        ]
        organizational_units = db.scalars(
            select(OrganizationalUnit)
            .where(OrganizationalUnit.active.is_(True))
            .order_by(OrganizationalUnit.sort_order, OrganizationalUnit.name)
        ).all()
        user_role_rows = db.execute(
            select(UserRole.user_id, Role.code)
            .join(Role, Role.id == UserRole.role_id)
            .where(UserRole.user_id.in_([item.id for item in users]))
        ).all()
        user_unit_rows = db.execute(
            select(UserOrganizationalUnit.user_id, OrganizationalUnit.code)
            .join(OrganizationalUnit, OrganizationalUnit.id == UserOrganizationalUnit.organizational_unit_id)
            .where(UserOrganizationalUnit.user_id.in_([item.id for item in users]))
        ).all()
        role_permission_rows = db.execute(
            select(RolePermission.role_id, Permission.code)
            .join(Permission, Permission.id == RolePermission.permission_id)
        ).all()
        user_roles_by_id: dict[int, set[str]] = {}
        for row in user_role_rows:
            user_roles_by_id.setdefault(row[0], set()).add(row[1])
        user_units_by_id: dict[int, set[str]] = {}
        for row in user_unit_rows:
            user_units_by_id.setdefault(row[0], set()).add(row[1])
        role_permissions_by_id: dict[int, set[str]] = {}
        for row in role_permission_rows:
            role_permissions_by_id.setdefault(row[0], set()).add(row[1])
        return templates.TemplateResponse(
            request,
            "admin.html",
            {
                "user": user,
                "users": users,
                "roles": roles,
                "permissions_catalog": permissions,
                "organizational_units": organizational_units,
                "user_roles_by_id": user_roles_by_id,
                "user_units_by_id": user_units_by_id,
                "role_permissions_by_id": role_permissions_by_id,
                "permissions": sorted(get_user_permission_codes(db, user)),
                "authorized_units": sorted(get_user_authorized_unit_codes(db, user)),
                "pilot_feedback_items": pilot_feedback_items,
                "pilot_feedback_counts": pilot_feedback_counts,
                "pilot_feedback_user_by_id": {item.id: item for item in pilot_feedback_users},
                "pilot_feedback_kind_labels": PILOT_FEEDBACK_KIND_LABELS,
                "pilot_feedback_source_labels": PILOT_FEEDBACK_SOURCE_LABELS,
                "implementation_roadmap": IMPLEMENTATION_ROADMAP,
                "task_classification_access_rules": TASK_CLASSIFICATION_ACCESS_RULES,
                "admin_user_roles": ADMIN_USER_ROLES,
                "user_created": user_created,
                "access_updated": access_updated,
                "permissions_updated": permissions_updated,
                "error": error,
            },
        )


def can_manage_admin(db, user: User | None) -> bool:
    if not user:
        return False
    permissions = get_user_permission_codes(db, user)
    return bool({"admin.manage", "users.manage", "settings.manage"} & permissions)


@web_router.post("/admin/users", response_class=HTMLResponse)
def admin_create_user(
    request: Request,
    name: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
    role_code: str = Form("operator"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_name = name.strip()
    clean_email = email.strip().lower()
    clean_password = password.strip()
    allowed_roles = {code for code, _ in ADMIN_USER_ROLES}
    if role_code not in allowed_roles:
        role_code = "operator"

    if not clean_name or not clean_email or not clean_password:
        return RedirectResponse("/admin?error=Preenche%20nome%2C%20email%20e%20password.", status_code=303)
    if "@" not in clean_email:
        return RedirectResponse("/admin?error=Email%20invalido.", status_code=303)
    if len(clean_password) < 8:
        return RedirectResponse("/admin?error=A%20password%20deve%20ter%20pelo%20menos%208%20caracteres.", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        if not current_user:
            return RedirectResponse("/login", status_code=303)
        if not can_manage_admin(db, current_user):
            return RedirectResponse("/", status_code=303)
        existing = db.scalar(select(User).where(User.email == clean_email))
        if existing:
            return RedirectResponse("/admin?error=Já%20existe%20um%20utilizador%20com%20esse%20email.", status_code=303)

        new_user = create_user(
            db,
            name=clean_name,
            email=clean_email,
            password=clean_password,
            role_codes=[role_code],
            organizational_unit_codes=["carfast", "workshop"],
        )
        record_audit(
            db,
            action="admin.user.created",
            entity_type="user",
            entity_id=new_user.id,
            detail=f"Utilizador criado na administracao: {new_user.email}",
            after_json={"role": role_code, "units": ["carfast", "workshop"]},
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/admin?user_created=1", status_code=303)


@web_router.post("/admin/users/{target_user_id}/access", response_class=HTMLResponse)
def admin_update_user_access(
    request: Request,
    target_user_id: int,
    role_codes: list[str] = Form(default=[]),
    unit_codes: list[str] = Form(default=[]),
    active: str | None = Form(default=None),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        target_user = db.get(User, target_user_id)
        if not current_user or not target_user:
            return RedirectResponse("/admin?error=Utilizador%20não%20encontrado.", status_code=303)
        if not can_manage_admin(db, current_user):
            return RedirectResponse("/", status_code=303)

        valid_roles = db.scalars(select(Role).where(Role.code.in_(role_codes))).all() if role_codes else []
        valid_units = (
            db.scalars(select(OrganizationalUnit).where(OrganizationalUnit.code.in_(unit_codes))).all()
            if unit_codes
            else []
        )
        if target_user.id == current_user.id and active != "on":
            return RedirectResponse(
                "/admin?error=Não%20podes%20desativar%20o%20teu%20próprio%20utilizador.",
                status_code=303,
            )

        before = {
            "active": target_user.active,
            "roles": sorted(
                row[0]
                for row in db.execute(
                    select(Role.code).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == target_user.id)
                ).all()
            ),
            "units": sorted(
                row[0]
                for row in db.execute(
                    select(OrganizationalUnit.code)
                    .join(UserOrganizationalUnit, UserOrganizationalUnit.organizational_unit_id == OrganizationalUnit.id)
                    .where(UserOrganizationalUnit.user_id == target_user.id)
                ).all()
            ),
        }
        target_user.active = active == "on"
        db.execute(delete(UserRole).where(UserRole.user_id == target_user.id))
        db.execute(delete(UserOrganizationalUnit).where(UserOrganizationalUnit.user_id == target_user.id))
        for role in valid_roles:
            db.add(UserRole(user_id=target_user.id, role_id=role.id))
        for unit in valid_units:
            db.add(UserOrganizationalUnit(user_id=target_user.id, organizational_unit_id=unit.id))

        after = {
            "active": target_user.active,
            "roles": sorted(role.code for role in valid_roles),
            "units": sorted(unit.code for unit in valid_units),
        }
        record_audit(
            db,
            action="admin.user.access.updated",
            entity_type="user",
            entity_id=target_user.id,
            detail=f"Acessos atualizados: {target_user.email}",
            before_json=before,
            after_json=after,
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/admin?access_updated=1", status_code=303)


@web_router.post("/admin/roles/{role_id}/permissions", response_class=HTMLResponse)
def admin_update_role_permissions(
    request: Request,
    role_id: int,
    permission_codes: list[str] = Form(default=[]),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        role = db.get(Role, role_id)
        if not current_user or not role:
            return RedirectResponse("/admin?error=Perfil%20não%20encontrado.", status_code=303)
        if not can_manage_admin(db, current_user):
            return RedirectResponse("/", status_code=303)
        if role.code == "admin":
            return RedirectResponse(
                "/admin?error=O%20perfil%20Admin%20mantém%20todas%20as%20permissões%20por%20segurança.",
                status_code=303,
            )

        before_permissions = sorted(
            row[0]
            for row in db.execute(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == role.id)
            ).all()
        )
        valid_permissions = (
            db.scalars(select(Permission).where(Permission.code.in_(permission_codes))).all()
            if permission_codes
            else []
        )
        db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
        for permission in valid_permissions:
            db.add(RolePermission(role_id=role.id, permission_id=permission.id))

        after_permissions = sorted(permission.code for permission in valid_permissions)
        record_audit(
            db,
            action="admin.role.permissions.updated",
            entity_type="role",
            entity_id=role.id,
            detail=f"Permissões atualizadas para o perfil: {role.code}",
            before_json={"permissions": before_permissions},
            after_json={"permissions": after_permissions},
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/admin?permissions_updated=1", status_code=303)


@web_router.get("/pilot-feedback/new", response_class=HTMLResponse)
def pilot_feedback_form(
    request: Request,
    kind: str = "question",
    source_area: str = "workshop",
    entity_type: str = "",
    entity_id: str = "",
    return_url: str = "",
    saved: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if kind not in PILOT_FEEDBACK_KIND_LABELS:
        kind = "question"
    return templates.TemplateResponse(
        request,
        "pilot_feedback_form.html",
        {
            "kind": kind,
            "kind_label": PILOT_FEEDBACK_KIND_LABELS[kind],
            "source_area": source_area,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "return_url": return_url,
            "saved": saved,
            "kind_labels": PILOT_FEEDBACK_KIND_LABELS,
        },
    )


@web_router.get("/manual", response_class=HTMLResponse)
def app_manual_page(request: Request, return_url: str = ""):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    safe_return_url = return_url if return_url.startswith("/") else ""
    return templates.TemplateResponse(
        request,
        "app_manual.html",
        {
            "return_url": safe_return_url,
        },
    )


@web_router.post("/pilot-feedback", response_class=HTMLResponse)
def pilot_feedback_create(
    request: Request,
    kind: str = Form("question"),
    source_area: str = Form("workshop"),
    entity_type: str = Form(""),
    entity_id: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    attachment_url: str = Form(""),
    current_url: str = Form(""),
    return_url: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if kind not in PILOT_FEEDBACK_KIND_LABELS:
        kind = "question"

    clean_subject = subject.strip()
    clean_body = body.strip() or "Registo criado sem detalhe."
    clean_attachment_url = attachment_url.strip()
    if clean_attachment_url:
        clean_body = f"{clean_body}\n\nAnexo / evidência: {clean_attachment_url}"
    with SessionLocal() as db:
        item = PilotFeedback(
            kind=kind,
            status="open",
            source_area=source_area.strip() or None,
            entity_type=entity_type.strip() or None,
            entity_id=entity_id.strip() or None,
            subject=clean_subject or PILOT_FEEDBACK_KIND_LABELS[kind],
            body=clean_body,
            current_url=current_url.strip() or None,
            user_id=user_id,
        )
        db.add(item)
        db.flush()
        record_audit(
            db,
            action="pilot.feedback.created",
            entity_type="pilot_feedback",
            entity_id=item.id,
            detail=f"Feedback de piloto registado: {PILOT_FEEDBACK_KIND_LABELS[kind]}",
            after_json={
                "kind": kind,
                "source_area": item.source_area,
                "linked_entity_type": item.entity_type,
                "linked_entity_id": item.entity_id,
            },
            user_id=user_id,
        )
        db.commit()

    if return_url.startswith("/"):
        return RedirectResponse(add_query_flag(return_url, "feedback_saved", "1"), status_code=303)
    return RedirectResponse(f"/pilot-feedback/new?kind={kind}&saved=1", status_code=303)


@web_router.get("/fleet", response_class=HTMLResponse)
def vehicles_page(request: Request, q: str | None = None, scope: str = "active", imported: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        stmt = select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)
        if scope not in {"active", "for_sale", "sold", "all"}:
            scope = "active"
        sold_filter = or_(Vehicle.lifecycle_status == "sold", Vehicle.operational_status == "sold")
        if scope == "active":
            stmt = stmt.where(Vehicle.active.is_(True), ~sold_filter)
        elif scope == "for_sale":
            stmt = stmt.where(Vehicle.lifecycle_status == "for_sale")
        elif scope == "sold":
            stmt = stmt.where(sold_filter)
        if q:
            normalized = q.strip().upper().replace(" ", "")
            stmt = stmt.where(
                (Vehicle.plate == normalized)
                | (Vehicle.vin == normalized)
                | (Vehicle.rentway_unit_nr == normalized)
                | Vehicle.brand.ilike(f"%{q}%")
                | Vehicle.model.ilike(f"%{q}%")
            )
        vehicles = sorted(db.scalars(stmt).all(), key=rentway_unit_sort_key, reverse=True)[:100]
        last_fleet_import = db.scalar(
            select(ImportBatch)
            .where(ImportBatch.import_type == "rentway_fleet")
            .order_by(ImportBatch.id.desc())
            .limit(1)
        )
        for_sale_count = db.scalar(
            select(func.count()).select_from(Vehicle).where(Vehicle.lifecycle_status == "for_sale")
        ) or 0
        return templates.TemplateResponse(
            request,
            "vehicles.html",
            {
                "vehicles": vehicles,
                "q": q or "",
                "scope": scope,
                "imported": imported,
                "last_fleet_import": last_fleet_import,
                "for_sale_count": for_sale_count,
            },
        )


@web_router.get("/fleet/trade-list", response_class=HTMLResponse)
def fleet_trade_list(
    request: Request,
    q: str | None = None,
    state: str | None = None,
    brand_model: str | None = None,
    year: str | None = None,
    km_min: str | None = None,
    km_max: str | None = None,
    current_status: str | None = None,
    location: str | None = None,
    pending: str | None = None,
    decision: str | None = None,
    responsible: str | None = None,
    finance_entity: str | None = None,
    current_cost_min: str | None = None,
    current_cost_max: str | None = None,
    debt_min: str | None = None,
    debt_max: str | None = None,
    blocked: str | None = None,
    updated: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    filters = {
        "q": q or "",
        "state": state or "",
        "brand_model": brand_model or "",
        "year": year or "",
        "km_min": km_min or "",
        "km_max": km_max or "",
        "current_status": current_status or "",
        "location": location or "",
        "pending": pending or "",
        "decision": decision or "",
        "responsible": responsible or "",
        "finance_entity": finance_entity or "",
        "current_cost_min": current_cost_min or "",
        "current_cost_max": current_cost_max or "",
        "debt_min": debt_min or "",
        "debt_max": debt_max or "",
        "blocked": blocked or "",
    }

    with SessionLocal() as db:
        sold_filter = or_(Vehicle.lifecycle_status == "sold", Vehicle.operational_status == "sold")
        vehicles = db.scalars(
            select(Vehicle)
            .where(Vehicle.active.is_(True), ~sold_filter)
            .order_by(Vehicle.id.desc())
            .limit(5000)
        ).all()
        vehicle_ids = [vehicle.id for vehicle in vehicles]
        snapshots = {
            snapshot.vehicle_id: snapshot
            for snapshot in db.scalars(
                select(VehicleExternalSnapshot).where(
                    VehicleExternalSnapshot.vehicle_id.in_(vehicle_ids),
                    VehicleExternalSnapshot.source_system == "rentway",
                )
            ).all()
        } if vehicle_ids else {}
        manual_fields_by_vehicle: dict[int, dict[str, object]] = {vehicle_id: {} for vehicle_id in vehicle_ids}
        if vehicle_ids:
            for field in db.scalars(
                select(VehicleManualField).where(
                    VehicleManualField.vehicle_id.in_(vehicle_ids),
                    VehicleManualField.field_code.in_(CARFAST_MANAGEMENT_FIELD_CODES),
                )
            ).all():
                manual_fields_by_vehicle.setdefault(field.vehicle_id, {})[field.field_code] = field.value_json

        rows = []
        for vehicle in vehicles:
            snapshot = snapshots.get(vehicle.id)
            rentway_context = rentway_commercial_context(snapshot)
            finance = current_cost_from_snapshot(snapshot)
            manual = manual_fields_by_vehicle.get(vehicle.id, {})
            block_reason = str(manual.get("sale_block_reason") or "")
            if block_reason == "outro" and manual.get("sale_block_reason_other"):
                block_reason_label = str(manual.get("sale_block_reason_other"))
            else:
                block_reason_label = SALE_BLOCK_REASON_LABELS.get(block_reason, "-")
            state_code = str(manual.get("trade_list_state") or "candidata")
            decision_code = str(manual.get("trade_decision") or "")
            row = {
                "vehicle": vehicle,
                "rentway": rentway_context,
                "manual": manual,
                "finance": finance,
                "km": parse_decimal_text(rentway_context.get("km")),
                "sale_blocked": bool(manual.get("sale_blocked")),
                "block_reason_label": block_reason_label,
                "state": state_code,
                "state_label": TRADE_LIST_STATE_LABELS.get(state_code, state_code),
                "decision": decision_code,
                "decision_label": TRADE_DECISION_LABELS.get(decision_code, decision_code or "Sem decisão"),
                "responsible": str(manual.get("trade_responsible") or ""),
                "pending_items": str(manual.get("trade_pending_items") or ""),
                "finance_entity": str(manual.get("finance_entity") or rentway_context.get("finance_entity") or ""),
                "debt_value": parse_decimal_text(manual.get("debt_value")),
                "selected_for_sale": bool(manual.get("trade_selected_for_sale")),
                "sale_price": str(manual.get("trade_sale_price") or ""),
                "ready_for_final": bool(decision_code and manual.get("trade_decision_reason") and manual.get("trade_responsible")),
            }
            rows.append(row)

        def includes(value, needle: str) -> bool:
            return needle.lower() in str(value or "").lower()

        filtered_rows = []
        for row in rows:
            vehicle = row["vehicle"]
            haystack = " ".join(
                str(item or "")
                for item in [
                    vehicle.plate,
                    vehicle.rentway_unit_nr,
                    vehicle.vin,
                    vehicle.brand,
                    vehicle.model,
                    vehicle.version,
                    row["rentway"].get("current_status"),
                    row["rentway"].get("document_nr"),
                    row["rentway"].get("client"),
                    row["rentway"].get("rental_station"),
                    row["finance_entity"],
                    row["responsible"],
                ]
            )
            if filters["q"] and not includes(haystack, filters["q"]):
                continue
            if filters["state"] and row["state"] != filters["state"]:
                continue
            if filters["brand_model"] and not includes(f"{vehicle.brand or ''} {vehicle.model or ''}", filters["brand_model"]):
                continue
            if filters["year"] and str(vehicle.year or "") != filters["year"]:
                continue
            if filters["current_status"] and row["rentway"].get("current_status") != filters["current_status"]:
                continue
            if filters["location"] and row["rentway"].get("rental_station") != filters["location"]:
                continue
            if filters["pending"] == "with" and not row["pending_items"]:
                continue
            if filters["pending"] == "without" and row["pending_items"]:
                continue
            if filters["decision"] and row["decision"] != filters["decision"]:
                continue
            if filters["responsible"] and row["responsible"] != filters["responsible"]:
                continue
            if filters["finance_entity"] and row["finance_entity"] != filters["finance_entity"]:
                continue
            if filters["blocked"] == "yes" and not row["sale_blocked"]:
                continue
            if filters["blocked"] == "no" and row["sale_blocked"]:
                continue
            km_value = row["km"]
            if filters["km_min"] and (km_value is None or km_value < (parse_decimal_text(filters["km_min"]) or 0)):
                continue
            if filters["km_max"] and (km_value is None or km_value > (parse_decimal_text(filters["km_max"]) or 0)):
                continue
            current_cost = row["finance"].get("current_cost")
            min_cost = parse_decimal_text(filters["current_cost_min"])
            max_cost = parse_decimal_text(filters["current_cost_max"])
            if min_cost is not None and (current_cost is None or current_cost < min_cost):
                continue
            if max_cost is not None and (current_cost is None or current_cost > max_cost):
                continue
            min_debt = parse_decimal_text(filters["debt_min"])
            max_debt = parse_decimal_text(filters["debt_max"])
            if min_debt is not None and (row["debt_value"] is None or row["debt_value"] < min_debt):
                continue
            if max_debt is not None and (row["debt_value"] is None or row["debt_value"] > max_debt):
                continue
            filtered_rows.append(row)

        summary = {
            "total": len(filtered_rows),
            "blocked": sum(1 for row in filtered_rows if row["sale_blocked"]),
            "approved": sum(1 for row in filtered_rows if row["state"] == "aprovada"),
            "ready": sum(1 for row in filtered_rows if row["ready_for_final"]),
            "pending_info": sum(1 for row in filtered_rows if row["state"] == "pendente_informacao" or row["pending_items"]),
        }
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name.asc())).all()
        return templates.TemplateResponse(
            request,
            "vehicle_trade_list.html",
            {
                "rows": sorted(filtered_rows, key=lambda item: rentway_unit_sort_key(item["vehicle"]), reverse=True)[:500],
                "summary": summary,
                "filters": filters,
                "state_options": TRADE_LIST_STATES,
                "decision_options": TRADE_DECISIONS,
                "users": users,
                "format_eur": format_eur,
                "current_status_options": sorted(
                    {row["rentway"].get("current_status") for row in rows if row["rentway"].get("current_status")}
                ),
                "year_options": sorted(
                    {vehicle.year for vehicle in vehicles if vehicle.year},
                    reverse=True,
                ),
                "location_options": sorted(
                    {row["rentway"].get("rental_station") for row in rows if row["rentway"].get("rental_station")}
                ),
                "finance_entity_options": finance_entity_options(db),
                "updated": updated,
            },
        )


@web_router.post("/fleet/trade-list/update", response_class=HTMLResponse)
async def fleet_trade_list_update(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse("/fleet/trade-list", status_code=303)

    form = await request.form()
    return_url = str(form.get("return_url") or "/fleet/trade-list")
    if not return_url.startswith("/") or return_url.startswith("//"):
        return_url = "/fleet/trade-list"

    vehicle_ids = []
    for value in form.getlist("vehicle_ids"):
        try:
            vehicle_ids.append(int(str(value)))
        except ValueError:
            continue
    selected_ids = set()
    for value in form.getlist("selected_vehicle_ids"):
        try:
            selected_ids.add(int(str(value)))
        except ValueError:
            continue

    with SessionLocal() as db:
        changed = 0
        for vehicle_id in vehicle_ids:
            vehicle = db.get(Vehicle, vehicle_id)
            if not vehicle:
                continue
            previous = vehicle_manual_values(db, vehicle_id)
            selected = vehicle_id in selected_ids
            raw_price = str(form.get(f"sale_price_{vehicle_id}") or "").strip()[:80]
            upsert_vehicle_manual_field(db, vehicle_id, "trade_selected_for_sale", selected, user_id)
            upsert_vehicle_manual_field(db, vehicle_id, "trade_sale_price", raw_price, user_id)
            current = {
                "trade_selected_for_sale": selected,
                "trade_sale_price": raw_price,
            }
            if previous.get("trade_selected_for_sale") != selected or str(previous.get("trade_sale_price") or "") != raw_price:
                changed += 1
                record_audit(
                    db,
                    action="vehicle.trade_list.updated",
                    entity_type="vehicle",
                    entity_id=vehicle_id,
                    detail=f"Lista para Comércio atualizada: {vehicle.plate or vehicle_id}",
                    before_json={
                        "trade_selected_for_sale": previous.get("trade_selected_for_sale"),
                        "trade_sale_price": previous.get("trade_sale_price"),
                    },
                    after_json=current,
                    user_id=user_id,
                )
        db.commit()
    return RedirectResponse(add_query_flag(return_url, "updated", str(changed)), status_code=303)


@web_router.get("/fleet/{vehicle_id}", response_class=HTMLResponse)
def vehicle_detail(
    request: Request,
    vehicle_id: int,
    saved: str | None = None,
    task_created: str | None = None,
    document_created: str | None = None,
    error: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)

        snapshot = db.scalar(
            select(VehicleExternalSnapshot)
            .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
            .order_by(VehicleExternalSnapshot.updated_at.desc())
        )
        carfast_management = vehicle_manual_values(db, vehicle.id)
        carfast_finance = current_cost_from_snapshot(snapshot)
        vehicle_rules = vehicle_rule_context(snapshot, carfast_management)
        events = db.scalars(
            select(VehicleOperationalStatusEvent)
            .where(VehicleOperationalStatusEvent.vehicle_id == vehicle.id)
            .order_by(VehicleOperationalStatusEvent.created_at.desc())
            .limit(20)
        ).all()
        vehicle_tasks = db.scalars(
            select(Task)
            .where(
                Task.entity_type == "vehicle",
                Task.entity_id == str(vehicle.id),
                Task.closed_at.is_(None),
            )
            .order_by(Task.id.desc())
        ).all()
        workshop_processes = db.scalars(
            select(WorkshopProcess)
            .where(
                WorkshopProcess.vehicle_id == vehicle.id,
                WorkshopProcess.closed_at.is_(None),
            )
            .order_by(WorkshopProcess.id.desc())
        ).all()
        technical_readings = db.scalars(
            select(WorkshopTechnicalReading)
            .where(WorkshopTechnicalReading.vehicle_id == vehicle.id)
            .order_by(
                WorkshopTechnicalReading.reading_date.is_(None),
                WorkshopTechnicalReading.reading_date.desc(),
                WorkshopTechnicalReading.id.desc(),
            )
            .limit(20)
        ).all()
        technical_readings_count = db.scalar(
            select(func.count()).select_from(WorkshopTechnicalReading).where(
                WorkshopTechnicalReading.vehicle_id == vehicle.id
            )
        ) or 0
        process_ids = {item.process_id for item in technical_readings if item.process_id}
        reading_process_by_id = {
            item.id: item
            for item in db.scalars(
                select(WorkshopProcess).where(WorkshopProcess.id.in_(process_ids))
            ).all()
        } if process_ids else {}
        documents = db.scalars(
            select(Document)
            .where(or_(Document.vehicle_id == vehicle.id, Document.plate == (vehicle.plate or "")))
            .order_by(Document.id.desc())
            .limit(20)
        ).all()
        history_audits = db.scalars(
            select(VehicleHistoryAudit)
            .where(VehicleHistoryAudit.vehicle_id == vehicle.id)
            .order_by(VehicleHistoryAudit.id.desc())
            .limit(10)
        ).all()
        active_users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
        return templates.TemplateResponse(
            request,
            "vehicle_detail.html",
            {
                "vehicle": vehicle,
                "snapshot": snapshot,
                "vehicle_context": rentway_vehicle_context(snapshot),
                "rentway_context": rentway_commercial_context(snapshot),
                "carfast_management": carfast_management,
                "carfast_finance": carfast_finance,
                "vehicle_rules": vehicle_rules,
                "vehicle_rule_categories": VEHICLE_RULE_CATEGORIES,
                "can_manage_carfast": can_manage_carfast_fleet(request),
                "trade_list_states": TRADE_LIST_STATES,
                "trade_decisions": TRADE_DECISIONS,
                "sale_block_reasons": SALE_BLOCK_REASONS,
                "sale_block_reason_labels": SALE_BLOCK_REASON_LABELS,
                "finance_entity_options": finance_entity_options(
                    db,
                    str(carfast_management.get("finance_entity") or ""),
                ),
                "format_eur": format_eur,
                "events": events,
                "vehicle_tasks": vehicle_tasks,
                "workshop_processes": workshop_processes,
                "technical_readings": technical_readings,
                "technical_readings_count": technical_readings_count,
                "reading_process_by_id": reading_process_by_id,
                "documents": documents,
                "history_audits": history_audits,
                "history_audit_phase_labels": HISTORY_AUDIT_PHASE_LABELS,
                "history_audit_status_labels": HISTORY_AUDIT_STATUS_LABELS,
                "active_users": active_users,
                "document_status_labels": DOCUMENT_STATUS_LABELS,
                "document_area_labels": DOCUMENT_AREA_LABELS,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "workshop_status_labels": WORKSHOP_STATUS_LABELS,
                "technical_reading_type_labels": WORKSHOP_READING_TYPE_LABELS,
                "technical_reading_field_labels": TECHNICAL_READING_COMPARE_LABELS,
                "saved": saved,
                "task_created": task_created,
                "document_created": document_created,
                "error": error,
            },
        )


@web_router.post("/fleet/{vehicle_id}/history-audits", response_class=HTMLResponse)
def create_vehicle_history_audit(
    request: Request,
    vehicle_id: int,
    reason: str = Form(""),
    priority: str = Form("normal"),
    responsible_user_id: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}?error=Sem%20permissão.", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)
        process_type = ensure_history_audit_process_type(db)
        internal_reference = next_history_audit_reference(db)
        management_process = ManagementProcess(
            process_type_id=process_type.id,
            internal_reference=internal_reference,
            title=f"Auditoria técnica {vehicle.plate or vehicle.id}",
            status="open",
            phase="document_collection",
            priority=priority or "normal",
            plate=vehicle.plate,
            opened_on=date.today(),
            raw_summary_json={"vehicle_id": vehicle.id, "kind": "vehicle_history_audit"},
        )
        db.add(management_process)
        db.flush()
        audit = VehicleHistoryAudit(
            management_process_id=management_process.id,
            vehicle_id=vehicle.id,
            plate=vehicle.plate or "",
            status="building",
            phase="document_collection",
            responsible_user_id=parse_optional_int(responsible_user_id),
            priority=priority or "normal",
            reason=reason.strip() or None,
            confidence_level="medium",
            opened_at=datetime.now(UTC),
        )
        db.add(audit)
        db.flush()
        add_history(
            db,
            management_process.id,
            action="vehicle_history_audit.created",
            entity_type="vehicle_history_audit",
            entity_id=audit.id,
            new_value=audit.reason,
            detail=f"Auditoria criada para {vehicle.plate or vehicle.id}",
            user_id=user_id,
        )
        record_audit(
            db,
            action="vehicle.history_audit.created",
            entity_type="vehicle",
            entity_id=vehicle.id,
            detail=f"Auditoria de histórico criada: {internal_reference}",
            user_id=user_id,
        )
        db.commit()
        audit_id = audit.id

    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)


@web_router.get("/fleet/{vehicle_id}/history-audits/{audit_id}", response_class=HTMLResponse)
def vehicle_history_audit_detail(request: Request, vehicle_id: int, audit_id: int):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not can_view_fleet(request):
        return RedirectResponse("/fleet", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not vehicle or not audit or audit.vehicle_id != vehicle.id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        documents = db.scalars(
            select(VehicleHistoryAuditDocument)
            .where(VehicleHistoryAuditDocument.audit_id == audit.id)
            .order_by(VehicleHistoryAuditDocument.id.desc())
        ).all()
        services = db.scalars(
            select(VehicleHistoryAuditService)
            .where(VehicleHistoryAuditService.audit_id == audit.id)
            .order_by(VehicleHistoryAuditService.service_date.desc().nullslast(), VehicleHistoryAuditService.id.desc())
        ).all()
        issues = db.scalars(
            select(VehicleHistoryAuditIssue)
            .where(VehicleHistoryAuditIssue.audit_id == audit.id)
            .order_by(VehicleHistoryAuditIssue.id.desc())
        ).all()
        readings = db.scalars(
            select(VehicleHistoryAuditReading)
            .where(VehicleHistoryAuditReading.audit_id == audit.id)
            .order_by(VehicleHistoryAuditReading.id.desc())
        ).all()
        truth = db.scalar(
            select(VehicleHistoryAuditTruth).where(VehicleHistoryAuditTruth.audit_id == audit.id)
        )
        rules = db.scalars(
            select(VehicleHistoryAuditRule)
            .where(VehicleHistoryAuditRule.audit_id == audit.id)
            .order_by(VehicleHistoryAuditRule.id.desc())
        ).all()
        source_documents = db.scalars(
            select(Document)
            .where(or_(Document.vehicle_id == vehicle.id, Document.plate == (vehicle.plate or "")))
            .order_by(Document.id.desc())
            .limit(80)
        ).all()
        active_users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)).all()
        management_process = db.get(ManagementProcess, audit.management_process_id) if audit.management_process_id else None
        return templates.TemplateResponse(
            request,
            "vehicle_history_audit_detail.html",
            {
                "vehicle": vehicle,
                "audit": audit,
                "management_process": management_process,
                "documents": documents,
                "services": services,
                "issues": issues,
                "readings": readings,
                "truth": truth,
                "rules": rules,
                "source_documents": source_documents,
                "active_users": active_users,
                "phase_options": HISTORY_AUDIT_PHASES,
                "phase_labels": HISTORY_AUDIT_PHASE_LABELS,
                "status_labels": HISTORY_AUDIT_STATUS_LABELS,
                "confidence_labels": HISTORY_AUDIT_CONFIDENCE_LABELS,
                "document_types": HISTORY_AUDIT_DOCUMENT_TYPES,
                "extractable_report_codes": HISTORY_AUDIT_EXTRACTABLE_REPORTS,
                "service_families": HISTORY_AUDIT_SERVICE_FAMILIES,
                "issue_types": HISTORY_AUDIT_ISSUE_TYPES,
                "issue_status_labels": HISTORY_AUDIT_ISSUE_STATUS_LABELS,
                "rule_types": HISTORY_AUDIT_RULE_TYPES,
                "can_edit": can_manage_carfast_fleet(request),
            },
        )


@web_router.post("/fleet/{vehicle_id}/history-audits/{audit_id}/update", response_class=HTMLResponse)
def update_vehicle_history_audit(
    request: Request,
    vehicle_id: int,
    audit_id: int,
    phase: str = Form("document_collection"),
    status: str = Form("open"),
    priority: str = Form("normal"),
    confidence_level: str = Form("medium"),
    summary: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)
    with SessionLocal() as db:
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not audit or audit.vehicle_id != vehicle_id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        audit.phase = phase
        audit.status = status
        audit.priority = priority
        audit.confidence_level = confidence_level
        audit.summary = summary.strip() or None
        if status == "closed" and not audit.closed_at:
            audit.closed_at = datetime.now(UTC)
        if audit.management_process_id:
            process = db.get(ManagementProcess, audit.management_process_id)
            if process:
                process.phase = phase
                process.status = "closed" if status == "closed" else "open"
                process.priority = priority
                if status == "closed" and not process.closed_at:
                    process.closed_at = datetime.now(UTC)
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}?updated=1", status_code=303)


@web_router.post("/fleet/{vehicle_id}/history-audits/{audit_id}/documents", response_class=HTMLResponse)
def add_vehicle_history_audit_document(
    request: Request,
    vehicle_id: int,
    audit_id: int,
    title: str = Form(""),
    document_type: str = Form("other"),
    source: str = Form("history_audit"),
    moment: str = Form("unknown"),
    link: str = Form(""),
    extraction_status: str = Form("pending"),
    confidence_level: str = Form("medium"),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not vehicle or not audit or audit.vehicle_id != vehicle.id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        clean_link = link.strip()
        document = None
        if clean_link:
            document = Document(
                title=title.strip() or f"Auditoria histórico - {document_type}",
                document_type=document_type,
                classification="technical" if document_type in {"technical_report", "bsi", "lubrication", "telecharge", "service_box", "tsb"} else "audit",
                source="history_audit",
                original_name=Path(clean_link).name or title.strip() or "documento_auditoria",
                file_name=Path(clean_link).name or title.strip() or "documento_auditoria",
                file_type=Path(clean_link).suffix.lstrip(".") or None,
                storage_provider="external",
                storage_path=clean_link,
                external_url=clean_link if clean_link.startswith(("http://", "https://")) else None,
                folder_path=suggest_document_folder_path(
                    "fleet",
                    audit.started_at.date() if audit.started_at else date.today(),
                    vehicle.plate,
                    document_type,
                    vin=vehicle.vin,
                    workshop_process_ref="Sem_Processo",
                ),
                status="associated",
                vehicle_id=vehicle.id,
                plate=vehicle.plate,
                uploaded_by_id=user_id,
            )
            db.add(document)
            db.flush()
            db.add(DocumentLink(document_id=document.id, entity_type="vehicle_history_audit", entity_id=str(audit.id), category=document_type))
            db.add(DocumentEvent(document_id=document.id, action="document.associated_to_history_audit", new_value=clean_link, user_id=user_id))
        db.add(
            VehicleHistoryAuditDocument(
                audit_id=audit.id,
                document_id=document.id if document else None,
                plate=audit.plate,
                document_type=document_type,
                source=source,
                moment=moment,
                link=clean_link or None,
                extraction_status=extraction_status,
                confidence_level=confidence_level,
                notes=notes.strip() or None,
            )
        )
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}?added=document", status_code=303)


@web_router.post("/fleet/{vehicle_id}/history-audits/{audit_id}/technical-reports", response_class=HTMLResponse)
async def add_vehicle_history_audit_technical_report(
    request: Request,
    vehicle_id: int,
    audit_id: int,
    report_file: UploadFile = File(...),
    report_code: str = Form("other"),
    moment: str = Form("history"),
    confidence_level: str = Form("medium"),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)

    content = await report_file.read()
    filename = Path(report_file.filename or "relatorio.pdf").name
    clean_report_code = report_code if report_code in HISTORY_AUDIT_REPORT_LABELS else "other"
    extracted_values: dict = {}
    extraction_error: str | None = None
    extraction_status = "classified_manual"
    if clean_report_code in HISTORY_AUDIT_EXTRACTABLE_REPORTS:
        try:
            extracted_values = extract_workshop_report_values_from_bytes(content, clean_report_code, filename)
            extraction_status = "extracted_pending_validation" if extracted_values else "no_values_found"
        except Exception as exc:  # noqa: BLE001
            extraction_status = "extraction_failed_manual_validation"
            extraction_error = str(exc)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not vehicle or not audit or audit.vehicle_id != vehicle.id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        file_hash = hashlib.sha256(content).hexdigest() if content else None
        document_title = f"{HISTORY_AUDIT_REPORT_LABELS.get(clean_report_code, 'Relatório técnico')} - {vehicle.plate or vehicle.id}"
        document = Document(
            title=document_title,
            document_type=clean_report_code,
            classification="technical",
            source="history_audit",
            original_name=filename,
            file_name=filename,
            file_type=Path(filename).suffix.lstrip(".") or None,
            file_size=len(content) if content else None,
            storage_provider="history_audit_upload",
            storage_path=f"history-audit-upload://{audit.id}/{filename}",
            storage_key=file_hash,
            folder_path=suggest_document_folder_path(
                "fleet",
                audit.started_at.date() if audit.started_at else date.today(),
                vehicle.plate,
                clean_report_code,
                vin=vehicle.vin,
                workshop_process_ref="Sem_Processo",
            ),
            status="associated" if not extraction_error else "pending_manual_validation",
            vehicle_id=vehicle.id,
            plate=vehicle.plate,
            uploaded_by_id=user_id,
        )
        db.add(document)
        db.flush()
        audit_document = VehicleHistoryAuditDocument(
            audit_id=audit.id,
            document_id=document.id,
            plate=audit.plate,
            document_type=clean_report_code,
            source="history_audit",
            moment=moment,
            link=document.storage_path,
            extraction_status=extraction_status,
            confidence_level=confidence_level,
            extracted_values_json=extracted_values or None,
            extraction_error=extraction_error,
            notes=notes.strip() or None,
        )
        db.add(audit_document)
        db.flush()
        db.add(
            DocumentLink(
                document_id=document.id,
                entity_type="vehicle_history_audit",
                entity_id=str(audit.id),
                category=clean_report_code,
            )
        )
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="document.history_audit_report_uploaded",
                new_value=extraction_status,
                user_id=user_id,
            )
        )
        for row in history_audit_reading_rows(clean_report_code, extracted_values):
            db.add(
                VehicleHistoryAuditReading(
                    audit_id=audit.id,
                    audit_document_id=audit_document.id,
                    field_code=row["field_code"] or "",
                    field_label=row["field_label"] or row["field_code"] or "",
                    extracted_value=row["extracted_value"],
                    corrected_value=None,
                    unit=row["unit"],
                    status="pending_validation",
                    observation=None,
                    confidence_level=confidence_level,
                )
            )
        audit.phase = "technical_loading"
        if extraction_error:
            audit.status = "in_progress"
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}?added=technical_report", status_code=303)


@web_router.post("/fleet/{vehicle_id}/history-audits/{audit_id}/services", response_class=HTMLResponse)
def add_vehicle_history_audit_service(
    request: Request,
    vehicle_id: int,
    audit_id: int,
    service_date: str = Form(""),
    km: str = Form(""),
    supplier: str = Form(""),
    family: str = Form("other"),
    subtype: str = Form(""),
    quantity: str = Form(""),
    axle: str = Form(""),
    side: str = Form(""),
    document_id: str = Form(""),
    confidence_level: str = Form("medium"),
    notes: str = Form(""),
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)
    with SessionLocal() as db:
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not audit or audit.vehicle_id != vehicle_id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        db.add(
            VehicleHistoryAuditService(
                audit_id=audit.id,
                service_date=parse_optional_date(service_date),
                km=parse_optional_int(km),
                supplier=supplier.strip() or None,
                family=family,
                subtype=subtype.strip() or None,
                quantity=quantity.strip() or None,
                axle=axle.strip() or None,
                side=side.strip() or None,
                document_id=parse_optional_int(document_id),
                confidence_level=confidence_level,
                notes=notes.strip() or None,
            )
        )
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}?added=service", status_code=303)


@web_router.post("/fleet/{vehicle_id}/history-audits/{audit_id}/issues", response_class=HTMLResponse)
def add_vehicle_history_audit_issue(
    request: Request,
    vehicle_id: int,
    audit_id: int,
    issue_type: str = Form("other"),
    description: str = Form(...),
    administrative_source: str = Form(""),
    technical_source: str = Form(""),
    severity: str = Form("medium"),
    status: str = Form("new"),
    evidence: str = Form(""),
    recommended_action: str = Form(""),
    decision: str = Form(""),
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)
    with SessionLocal() as db:
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not audit or audit.vehicle_id != vehicle_id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        db.add(
            VehicleHistoryAuditIssue(
                audit_id=audit.id,
                issue_type=issue_type,
                description=description.strip(),
                administrative_source=administrative_source.strip() or None,
                technical_source=technical_source.strip() or None,
                severity=severity,
                status=status,
                evidence=evidence.strip() or None,
                recommended_action=recommended_action.strip() or None,
                decision=decision.strip() or None,
            )
        )
        if status in {"to_discuss", "em_discussao"}:
            audit.status = "validation"
            audit.phase = "discussion"
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}?added=issue", status_code=303)


@web_router.post("/fleet/{vehicle_id}/history-audits/{audit_id}/truth", response_class=HTMLResponse)
def save_vehicle_history_audit_truth(
    request: Request,
    vehicle_id: int,
    audit_id: int,
    assumed_start_date: str = Form(""),
    last_reliable_km: str = Form(""),
    last_valid_maintenance: str = Form(""),
    estimated_maintenance_count: str = Form(""),
    bsi_status: str = Form(""),
    telecharge_status: str = Form(""),
    assumed_version: str = Form(""),
    plan_to_follow: str = Form(""),
    pending_items: str = Form(""),
    confidence_level: str = Form("medium"),
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)
    with SessionLocal() as db:
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not audit or audit.vehicle_id != vehicle_id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        truth = db.scalar(select(VehicleHistoryAuditTruth).where(VehicleHistoryAuditTruth.audit_id == audit.id))
        if not truth:
            truth = VehicleHistoryAuditTruth(audit_id=audit.id)
            db.add(truth)
        truth.assumed_start_date = parse_optional_date(assumed_start_date)
        truth.last_reliable_km = parse_optional_int(last_reliable_km)
        truth.last_valid_maintenance = last_valid_maintenance.strip() or None
        truth.estimated_maintenance_count = parse_optional_int(estimated_maintenance_count)
        truth.bsi_status = bsi_status.strip() or None
        truth.telecharge_status = telecharge_status.strip() or None
        truth.assumed_version = assumed_version.strip() or None
        truth.plan_to_follow = plan_to_follow.strip() or None
        truth.pending_items = pending_items.strip() or None
        truth.confidence_level = confidence_level
        audit.phase = "assumed_truth"
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}?saved=truth", status_code=303)


@web_router.post("/fleet/{vehicle_id}/history-audits/{audit_id}/rules", response_class=HTMLResponse)
def add_vehicle_history_audit_rule(
    request: Request,
    vehicle_id: int,
    audit_id: int,
    rule_type: str = Form("other"),
    rule: str = Form(...),
    mandatory: str | None = Form(None),
    applies_when: str = Form(""),
    status: str = Form("active"),
    observation: str = Form(""),
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}", status_code=303)
    with SessionLocal() as db:
        audit = db.get(VehicleHistoryAudit, audit_id)
        if not audit or audit.vehicle_id != vehicle_id:
            return RedirectResponse(f"/fleet/{vehicle_id}", status_code=303)
        db.add(
            VehicleHistoryAuditRule(
                audit_id=audit.id,
                rule_type=rule_type,
                rule=rule.strip(),
                mandatory=mandatory == "on",
                applies_when=applies_when.strip() or None,
                status=status,
                observation=observation.strip() or None,
            )
        )
        audit.phase = "future_rules"
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}/history-audits/{audit_id}?added=rule", status_code=303)


@web_router.post("/fleet/{vehicle_id}/carfast-management", response_class=HTMLResponse)
def update_vehicle_carfast_management(
    request: Request,
    vehicle_id: int,
    sale_blocked: str | None = Form(None),
    sale_block_reason: str = Form(""),
    sale_block_reason_other: str = Form(""),
    real_start_date: str = Form(""),
    rule_category: str = Form(""),
    maintenance_interval_km: str = Form(""),
    maintenance_interval_months: str = Form(""),
    maintenance_last_valid_km: str = Form(""),
    maintenance_last_valid_date: str = Form(""),
    finance_entity: str = Form(""),
    debt_value: str = Form(""),
    trade_list_state: str = Form("candidata"),
    trade_pending_items: str = Form(""),
    trade_decision: str = Form(""),
    trade_decision_reason: str = Form(""),
    trade_responsible: str = Form(""),
    trade_sale_price: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not can_manage_carfast_fleet(request):
        return RedirectResponse(f"/fleet/{vehicle_id}?error=Sem%20permissão.", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)

        normalized_state = trade_list_state if trade_list_state in TRADE_LIST_STATE_LABELS else "candidata"
        normalized_decision = trade_decision if trade_decision in TRADE_DECISION_LABELS else ""
        normalized_reason = sale_block_reason if sale_block_reason in SALE_BLOCK_REASON_LABELS else ""
        normalized_rule_category = rule_category if rule_category in VEHICLE_RULE_CATEGORY_LABELS else ""
        new_values = {
            "real_start_date": real_start_date.strip()[:40],
            "rule_category": normalized_rule_category,
            "maintenance_interval_km": maintenance_interval_km.strip()[:80],
            "maintenance_interval_months": maintenance_interval_months.strip()[:80],
            "maintenance_last_valid_km": maintenance_last_valid_km.strip()[:80],
            "maintenance_last_valid_date": maintenance_last_valid_date.strip()[:40],
            "sale_blocked": sale_blocked == "1",
            "sale_block_reason": normalized_reason,
            "sale_block_reason_other": sale_block_reason_other.strip()[:500],
            "finance_entity": finance_entity.strip()[:160],
            "debt_value": debt_value.strip()[:80],
            "trade_list_state": normalized_state,
            "trade_pending_items": trade_pending_items.strip()[:1000],
            "trade_decision": normalized_decision,
            "trade_decision_reason": trade_decision_reason.strip()[:1000],
            "trade_responsible": trade_responsible.strip()[:160],
            "trade_sale_price": trade_sale_price.strip()[:80],
        }
        previous_values = vehicle_manual_values(db, vehicle.id)
        for field_code, value in new_values.items():
            upsert_vehicle_manual_field(db, vehicle.id, field_code, value, user_id)
        record_audit(
            db,
            action="vehicle.carfast_management.updated",
            entity_type="vehicle",
            entity_id=vehicle.id,
            detail=f"Gestão CarFast atualizada: {vehicle.plate or vehicle.id}",
            before_json=previous_values,
            after_json=new_values,
            user_id=user_id,
        )
        db.commit()
    return RedirectResponse(f"/fleet/{vehicle_id}?saved=1", status_code=303)


@web_router.get("/fleet/{vehicle_id}/technical-history", response_class=HTMLResponse)
def vehicle_technical_history(
    request: Request,
    vehicle_id: int,
    report_type: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)

        snapshot = db.scalar(
            select(VehicleExternalSnapshot)
            .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
            .order_by(VehicleExternalSnapshot.updated_at.desc())
        )
        readings = db.scalars(
            select(WorkshopTechnicalReading)
            .where(WorkshopTechnicalReading.vehicle_id == vehicle.id)
            .order_by(
                WorkshopTechnicalReading.reading_date.asc(),
                WorkshopTechnicalReading.id.asc(),
            )
        ).all()
        tabs = technical_history_tabs(readings)
        selected_type = report_type if report_type in {item["code"] for item in tabs} else None
        if not selected_type and tabs:
            selected_type = str(tabs[0]["code"])
        matrix = technical_history_matrix(readings, selected_type) if selected_type else {"readings": [], "rows": []}
        return templates.TemplateResponse(
            request,
            "vehicle_technical_history.html",
            {
                "vehicle": vehicle,
                "vehicle_context": rentway_vehicle_context(snapshot),
                "tabs": tabs,
                "selected_type": selected_type,
                "selected_label": WORKSHOP_READING_TYPE_LABELS.get(selected_type or "", selected_type or ""),
                "matrix": matrix,
                "total_readings": len(readings),
                "technical_reading_type_labels": WORKSHOP_READING_TYPE_LABELS,
                "technical_reading_field_labels": TECHNICAL_READING_COMPARE_LABELS,
                "compact_reading_label": compact_reading_label,
                "technical_history_url": f"/fleet/{vehicle.id}/technical-history",
            },
        )


@web_router.get("/workshop/{process_id}/technical-history", response_class=HTMLResponse)
def workshop_process_technical_history(
    request: Request,
    process_id: int,
    report_type: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop/manage", status_code=303)

        vehicle = db.get(Vehicle, process.vehicle_id)
        if not vehicle:
            return RedirectResponse(f"/workshop/{process.id}", status_code=303)

        snapshot = db.scalar(
            select(VehicleExternalSnapshot)
            .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
            .order_by(VehicleExternalSnapshot.updated_at.desc())
        )
        readings = db.scalars(
            select(WorkshopTechnicalReading)
            .where(WorkshopTechnicalReading.vehicle_id == vehicle.id)
            .order_by(
                WorkshopTechnicalReading.reading_date.asc(),
                WorkshopTechnicalReading.id.asc(),
            )
        ).all()
        tabs = technical_history_tabs(readings)
        selected_type = report_type if report_type in {item["code"] for item in tabs} else None
        if not selected_type and tabs:
            selected_type = str(tabs[0]["code"])
        matrix = technical_history_matrix(readings, selected_type) if selected_type else {"readings": [], "rows": []}
        return templates.TemplateResponse(
            request,
            "vehicle_technical_history.html",
            {
                "vehicle": vehicle,
                "vehicle_context": rentway_vehicle_context(snapshot),
                "tabs": tabs,
                "selected_type": selected_type,
                "selected_label": WORKSHOP_READING_TYPE_LABELS.get(selected_type or "", selected_type or ""),
                "matrix": matrix,
                "total_readings": len(readings),
                "technical_reading_type_labels": WORKSHOP_READING_TYPE_LABELS,
                "technical_reading_field_labels": TECHNICAL_READING_COMPARE_LABELS,
                "compact_reading_label": compact_reading_label,
                "technical_history_active_menu": "workshop",
                "technical_history_eyebrow": "Processo de oficina",
                "technical_history_subtitle": f"Consulta técnica no Processo #{process.id}",
                "technical_history_url": f"/workshop/{process.id}/technical-history",
                "technical_history_back_url": f"/workshop/{process.id}",
                "technical_history_back_label": "Voltar ao processo",
            },
        )


@web_router.post("/fleet/{vehicle_id}/events", response_class=HTMLResponse)
def vehicle_add_event(
    request: Request,
    vehicle_id: int,
    note: str = Form(...),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_note = note.strip()
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)
        if not clean_note:
            snapshot = db.scalar(
                select(VehicleExternalSnapshot)
                .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
                .order_by(VehicleExternalSnapshot.updated_at.desc())
            )
            events = db.scalars(
                select(VehicleOperationalStatusEvent)
                .where(VehicleOperationalStatusEvent.vehicle_id == vehicle.id)
                .order_by(VehicleOperationalStatusEvent.created_at.desc())
                .limit(20)
            ).all()
            vehicle_tasks = db.scalars(
                select(Task)
                .where(
                    Task.entity_type == "vehicle",
                    Task.entity_id == str(vehicle.id),
                    Task.closed_at.is_(None),
                )
                .order_by(Task.id.desc())
            ).all()
            workshop_processes = db.scalars(
                select(WorkshopProcess)
                .where(
                    WorkshopProcess.vehicle_id == vehicle.id,
                    WorkshopProcess.closed_at.is_(None),
                )
                .order_by(WorkshopProcess.id.desc())
            ).all()
            return templates.TemplateResponse(
                request,
                "vehicle_detail.html",
                {
                    "vehicle": vehicle,
                    "snapshot": snapshot,
                    "events": events,
                    "vehicle_tasks": vehicle_tasks,
                    "workshop_processes": workshop_processes,
                    "workshop_status_labels": WORKSHOP_STATUS_LABELS,
                    "saved": None,
                    "task_created": None,
                    "error": "Escreve uma nota antes de gravar.",
                },
                status_code=400,
            )

        db.add(
            VehicleOperationalStatusEvent(
                vehicle_id=vehicle.id,
                status=vehicle.operational_status or "note",
                occurred_at=datetime.now(UTC),
                source="internal",
                note=clean_note,
            )
        )
        record_audit(
            db,
            action="vehicle.event.created",
            entity_type="vehicle",
            entity_id=vehicle.id,
            detail=f"Nota interna adicionada a {vehicle.plate or vehicle.id}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/fleet/{vehicle_id}?saved=1", status_code=303)


@web_router.post("/fleet/{vehicle_id}/tasks", response_class=HTMLResponse)
def vehicle_create_task(
    request: Request,
    vehicle_id: int,
    title: str = Form(...),
    priority: str = Form("normal"),
    description: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_title = title.strip()
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)

        if not clean_title:
            snapshot = db.scalar(
                select(VehicleExternalSnapshot)
                .where(VehicleExternalSnapshot.vehicle_id == vehicle.id)
                .order_by(VehicleExternalSnapshot.updated_at.desc())
            )
            events = db.scalars(
                select(VehicleOperationalStatusEvent)
                .where(VehicleOperationalStatusEvent.vehicle_id == vehicle.id)
                .order_by(VehicleOperationalStatusEvent.created_at.desc())
                .limit(20)
            ).all()
            vehicle_tasks = db.scalars(
                select(Task)
                .where(
                    Task.entity_type == "vehicle",
                    Task.entity_id == str(vehicle.id),
                    Task.closed_at.is_(None),
                )
                .order_by(Task.id.desc())
            ).all()
            workshop_processes = db.scalars(
                select(WorkshopProcess)
                .where(
                    WorkshopProcess.vehicle_id == vehicle.id,
                    WorkshopProcess.closed_at.is_(None),
                )
                .order_by(WorkshopProcess.id.desc())
            ).all()
            return templates.TemplateResponse(
                request,
                "vehicle_detail.html",
                {
                    "vehicle": vehicle,
                    "snapshot": snapshot,
                    "events": events,
                    "vehicle_tasks": vehicle_tasks,
                    "workshop_processes": workshop_processes,
                    "workshop_status_labels": WORKSHOP_STATUS_LABELS,
                    "saved": None,
                    "task_created": None,
                    "error": "Indica um título para a tarefa.",
                },
                status_code=400,
            )

        task = Task(
            title=clean_title,
            description=description.strip() or None,
            task_type="workshop_task",
            source="manual",
            category="workshop",
            subcategory=default_task_subcategory("workshop"),
            status="new",
            priority=priority,
            team_id=default_team_id(db, "workshop"),
            entity_type="vehicle",
            entity_id=str(vehicle.id),
            plate=vehicle.plate,
            created_by_id=user_id,
        )
        db.add(task)
        db.flush()
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        record_audit(
            db,
            action="task.create",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa criada para viatura {vehicle.plate or vehicle.id}: {task.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/fleet/{vehicle_id}?task_created=1", status_code=303)


@web_router.post("/fleet/{vehicle_id}/documents", response_class=HTMLResponse)
def vehicle_create_document(
    request: Request,
    vehicle_id: int,
    title: str = Form(""),
    status: str = Form("received"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    supplier_name: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        vehicle = db.get(Vehicle, vehicle_id)
        if not vehicle:
            return RedirectResponse("/fleet", status_code=303)
        try:
            add_document_record(
                db,
                title=title,
                classification="workshop",
                document_type="workshop_other",
                status=status,
                document_date=parse_optional_date(document_date),
                source=source,
                entry_channel=entry_channel,
                source_sender=source_sender,
                source_subject=source_subject,
                url_original=url_original,
                url_archive=url_archive,
                plate=vehicle.plate or "",
                vehicle_id=vehicle.id,
                supplier_name=supplier_name,
                customer_name="",
                task_id=None,
                workshop_process_id=None,
                notes=notes,
                user_id=user_id,
            )
        except ValueError:
            return RedirectResponse(f"/fleet/{vehicle_id}?error=Indica%20título%20e%20link.", status_code=303)
        db.commit()

    return RedirectResponse(f"/fleet/{vehicle_id}?document_created=1", status_code=303)


@web_router.get("/workshop", response_class=HTMLResponse)
def workshop_center_page(
    request: Request,
    created: str | None = None,
    closed: str | None = None,
    feedback_saved: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        user = db.get(User, user_id)
        open_query = select(func.count()).select_from(WorkshopProcess).where(WorkshopProcess.closed_at.is_(None))
        open_count = db.scalar(open_query) or 0
        waiting_parts_count = db.scalar(
            open_query.where(WorkshopProcess.status == "waiting_parts")
        ) or 0
        waiting_analysis_count = db.scalar(
            open_query.where(WorkshopProcess.status == "waiting_analysis")
        ) or 0
        vehicles_preview = sorted(
            db.scalars(select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)).all(),
            key=rentway_unit_sort_key,
            reverse=True,
        )[:3]
        return templates.TemplateResponse(
            request,
            "workshop_center.html",
            {
                "open_count": open_count,
                "waiting_parts_count": waiting_parts_count,
                "waiting_analysis_count": waiting_analysis_count,
                "vehicles_preview": vehicles_preview,
                "can_access_workshop_tasks": user_can_access_task_workspace(db, user, "workshop"),
                "workshop_tasks_url": task_workspace_manage_url("workshop"),
                "created": created,
                "closed": closed,
                "feedback_saved": feedback_saved,
            },
        )


@web_router.get("/workshop/new", response_class=HTMLResponse)
def workshop_new_page(request: Request, error: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        vehicles = sorted(
            db.scalars(select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)).all(),
            key=rentway_unit_sort_key,
            reverse=True,
        )
        return templates.TemplateResponse(
            request,
            "workshop_new.html",
            {
                "vehicles": vehicles,
                "error": task_detail_error_message(error),
                "opening_types": WORKSHOP_OPENING_TYPES,
                "opening_type_labels": WORKSHOP_OPENING_LABELS,
                "service_families": WORKSHOP_SERVICE_FAMILIES,
                "service_details": WORKSHOP_SERVICE_DETAILS,
                "service_axes": WORKSHOP_SERVICE_AXES,
                "service_detail_families": WORKSHOP_SERVICE_DETAIL_FAMILIES,
                "service_axis_families": WORKSHOP_SERVICE_AXIS_FAMILIES,
            },
        )


@web_router.get("/workshop/manage", response_class=HTMLResponse)
def workshop_manage_page(
    request: Request,
    created: str | None = None,
    closed: str | None = None,
    feedback_saved: str | None = None,
    scope: str = "open",
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        if scope not in {"open", "closed", "all"}:
            scope = "open"
        process_stmt = select(WorkshopProcess)
        if scope == "open":
            process_stmt = process_stmt.where(WorkshopProcess.closed_at.is_(None))
        elif scope == "closed":
            process_stmt = process_stmt.where(WorkshopProcess.closed_at.is_not(None))
        processes = db.scalars(process_stmt.order_by(WorkshopProcess.id.desc()).limit(100)).all()
        process_counts = {
            "open": db.scalar(
                select(func.count()).select_from(WorkshopProcess).where(WorkshopProcess.closed_at.is_(None))
            )
            or 0,
            "closed": db.scalar(
                select(func.count()).select_from(WorkshopProcess).where(WorkshopProcess.closed_at.is_not(None))
            )
            or 0,
        }
        process_counts["all"] = process_counts["open"] + process_counts["closed"]
        vehicles = sorted(
            db.scalars(select(Vehicle).order_by(Vehicle.id.desc()).limit(5000)).all(),
            key=rentway_unit_sort_key,
            reverse=True,
        )
        vehicle_by_id = {item.id: item for item in vehicles}
        return templates.TemplateResponse(
            request,
            "workshop.html",
            {
                "processes": processes,
                "vehicle_by_id": vehicle_by_id,
                "created": created,
                "closed": closed,
                "feedback_saved": feedback_saved,
                "status_labels": WORKSHOP_STATUS_LABELS,
                "decision_labels": WORKSHOP_DECISION_LABELS,
                "opening_type_labels": WORKSHOP_OPENING_LABELS,
                "scope": scope,
                "process_counts": process_counts,
            },
        )


@web_router.post("/workshop", response_class=HTMLResponse)
@web_router.post("/workshop/new", response_class=HTMLResponse)
def workshop_create(
    request: Request,
    vehicle_id: str = Form(""),
    title: str = Form(""),
    opening_type: str = Form("walk_in"),
    priority: str = Form("normal"),
    km_entry: str = Form(""),
    expected_exit_on: str = Form(""),
    service_family: str = Form(""),
    service_detail: str = Form(""),
    service_axis: str = Form("not_defined"),
    service_note: str = Form(""),
    service_family_multi: list[str] = Form([]),
    service_detail_multi: list[str] = Form([]),
    service_axis_multi: list[str] = Form([]),
    service_note_multi: list[str] = Form([]),
    note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_title = title.strip()
    service_entries = normalize_workshop_service_entries(
        service_family_multi,
        service_detail_multi,
        service_axis_multi,
        service_note_multi,
        fallback_family=service_family,
        fallback_detail=service_detail,
        fallback_axis=service_axis,
        fallback_note=service_note,
    )
    parsed_vehicle_id = parse_optional_int(vehicle_id)
    with SessionLocal() as db:
        vehicle = db.get(Vehicle, parsed_vehicle_id) if parsed_vehicle_id else None
        vehicle_blocked_statuses = {
            (vehicle.lifecycle_status or "").strip().lower(),
            (vehicle.operational_status or "").strip().lower(),
        } if vehicle else set()
        if not vehicle or vehicle_blocked_statuses.intersection(WORKSHOP_BLOCKED_VEHICLE_STATUSES):
            error_message = (
                "A viatura selecionada já não está elegível para reparação interna."
                if vehicle
                else "Escolhe a viatura para ligar o processo ao histórico correto."
            )
            return templates.TemplateResponse(
                request,
                "workshop_new.html",
                {
                    "error": error_message,
                    "opening_types": WORKSHOP_OPENING_TYPES,
                    "opening_type_labels": WORKSHOP_OPENING_LABELS,
                    "service_families": WORKSHOP_SERVICE_FAMILIES,
                    "service_details": WORKSHOP_SERVICE_DETAILS,
                    "service_axes": WORKSHOP_SERVICE_AXES,
                    "service_detail_families": WORKSHOP_SERVICE_DETAIL_FAMILIES,
                    "service_axis_families": WORKSHOP_SERVICE_AXIS_FAMILIES,
                },
                status_code=400,
            )

        expected_date = parse_optional_date(expected_exit_on)
        fallback_title = note.strip().splitlines()[0][:120] if note.strip() else ""
        service_generated_title = workshop_service_title(service_entries, clean_title)
        clean_title = service_generated_title or fallback_title or f"Processo oficina - {vehicle.plate or vehicle.id}"
        process = WorkshopProcess(
            vehicle_id=vehicle.id,
            title=clean_title,
            opening_type=opening_type,
            status="opening",
            priority=priority,
            source="internal",
            opened_by_id=user_id,
            opened_on=date.today(),
            expected_exit_on=expected_date,
            km_entry=parse_optional_int(km_entry),
            note=note.strip() or None,
        )
        db.add(process)
        db.flush()
        process.document_folder_path = suggest_workshop_process_folder_path(process, vehicle)
        for clean_service_family, clean_service_detail, clean_service_axis, clean_service_note in service_entries:
            db.add(
                WorkshopProcessService(
                    process_id=process.id,
                    vehicle_id=vehicle.id,
                    service_family=clean_service_family,
                    service_detail=clean_service_detail,
                    service_axis=clean_service_axis,
                    status="to_assess",
                    note=clean_service_note or None,
                    created_by_id=user_id,
                )
            )
        record_audit(
            db,
            action="workshop.process.created",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Processo de oficina criado para {vehicle.plate or vehicle.id}: {process.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse("/workshop/manage?created=1", status_code=303)


TECHNICAL_READING_COMPARE_LABELS = {
    "maintenance_last_reset_km": "KM última reposição manutenção",
    "maintenance_km_until_next": "KM até próxima manutenção",
    "maintenance_days_until_next": "Dias até próxima manutenção",
    "maintenance_days_since_last_reset": "Dias desde última reposição de manutenção",
    "maintenance_last_reset_date_estimated": "Data estimada última reposição",
    "maintenance_days_since_first_circulation": "Dias desde início de circulação",
    "maintenance_first_circulation_date_estimated": "Data estimada início de circulação",
    "maintenance_temporal_limit_exceeded": "Limite temporal ultrapassado",
    "maintenance_distance_limit_exceeded": "Limite quilométrico ultrapassado",
    "maintenance_count": "Nº manutenções efetuadas",
    "maintenance_threshold_km": "Limiar manutenção",
    "maintenance_duration_months": "Duração manutenção",
    "maintenance_first_start_km": "Início primeira manutenção",
    "maintenance_first_duration_months": "Duração antes primeira manutenção",
    "maintenance_management_mode": "Gestão manutenção",
    "maintenance_next_due_date": "Data prevista próxima manutenção",
    "maintenance_days_since_last_estimated": "Dias estimados desde última manutenção",
    "maintenance_last_date_estimated": "Data estimada última manutenção",
    "machine_source": "Máquina / origem",
    "oil_dilution_rate": "Taxa de diluição do óleo",
    "oil_carbon_rate": "Taxa de carbono no óleo",
    "oil_anti_dilution_status": "Proteção anti-diluição",
    "engine_calculated_interval_km": "Intervalo calculado pelo calculador",
    "faults_present": "Existem defeitos",
    "fault_event_count": "Nº eventos de defeito",
    "critical_fault": "Defeito crítico",
    "fault_main_status": "Estado principal",
    "fault_characterization": "Caracterização",
    "fault_odometer_km": "KM associado ao defeito",
    "recommended_action": "Ação recomendada",
    "software_reference": "Referência software",
    "calibration_edition": "Edição calibração",
    "software_edition": "Edição software",
    "download_date": "Data telecarregamento",
    "download_count": "Nº telecarregamentos",
    "ecu_supplier": "Fornecedor calculador",
    "material_reference": "Referência material",
    "battery_voltage": "Tensão bateria",
    "fault_codes": "Códigos de erro",
    "bsi_notes": "Notas BSI",
    "systems_checked": "Sistemas verificados",
    "recommendation": "Recomendação",
    "flow_phase": "Fase do processo",
    "odometer_km": "KM",
}


def compact_reading_data(
    *,
    reading_date: date,
    maintenance_last_reset_km: str,
    maintenance_km_until_next: str,
    maintenance_days_until_next: str,
    maintenance_days_since_last_reset: str,
    maintenance_days_since_first_circulation: str,
    maintenance_temporal_limit_exceeded: str,
    maintenance_distance_limit_exceeded: str,
    maintenance_count: str,
    maintenance_threshold_km: str,
    maintenance_duration_months: str,
    maintenance_first_start_km: str,
    maintenance_first_duration_months: str,
    maintenance_management_mode: str,
    oil_dilution_rate: str,
    oil_carbon_rate: str,
    oil_anti_dilution_status: str,
    engine_calculated_interval_km: str,
    faults_present: str,
    critical_fault: str,
    fault_main_status: str,
    fault_characterization: str,
    fault_odometer_km: str,
    recommended_action: str,
    software_reference: str,
    calibration_edition: str,
    download_date: str,
    download_count: str,
    battery_voltage: str,
    fault_codes: str,
    bsi_notes: str,
    systems_checked: str,
    recommendation: str,
    flow_phase: str,
    machine_source: str,
) -> dict[str, str]:
    values = {
        "maintenance_last_reset_km": maintenance_last_reset_km.strip(),
        "maintenance_km_until_next": maintenance_km_until_next.strip(),
        "maintenance_days_until_next": maintenance_days_until_next.strip(),
        "maintenance_days_since_last_reset": maintenance_days_since_last_reset.strip(),
        "maintenance_days_since_first_circulation": maintenance_days_since_first_circulation.strip(),
        "maintenance_temporal_limit_exceeded": maintenance_temporal_limit_exceeded.strip(),
        "maintenance_distance_limit_exceeded": maintenance_distance_limit_exceeded.strip(),
        "maintenance_count": maintenance_count.strip(),
        "maintenance_threshold_km": maintenance_threshold_km.strip(),
        "maintenance_duration_months": maintenance_duration_months.strip(),
        "maintenance_first_start_km": maintenance_first_start_km.strip(),
        "maintenance_first_duration_months": maintenance_first_duration_months.strip(),
        "maintenance_management_mode": maintenance_management_mode.strip(),
        "oil_dilution_rate": oil_dilution_rate.strip(),
        "oil_carbon_rate": oil_carbon_rate.strip(),
        "oil_anti_dilution_status": oil_anti_dilution_status.strip(),
        "engine_calculated_interval_km": engine_calculated_interval_km.strip(),
        "faults_present": faults_present.strip(),
        "critical_fault": critical_fault.strip(),
        "fault_main_status": fault_main_status.strip(),
        "fault_characterization": fault_characterization.strip(),
        "fault_odometer_km": fault_odometer_km.strip(),
        "recommended_action": recommended_action.strip(),
        "software_reference": software_reference.strip(),
        "calibration_edition": calibration_edition.strip(),
        "download_date": download_date.strip(),
        "download_count": download_count.strip(),
        "battery_voltage": battery_voltage.strip(),
        "fault_codes": fault_codes.strip(),
        "bsi_notes": bsi_notes.strip(),
        "systems_checked": systems_checked.strip(),
        "recommendation": recommendation.strip(),
        "flow_phase": flow_phase.strip(),
        "machine_source": machine_source.strip(),
    }
    data = {key: value for key, value in values.items() if value}
    maintenance_days = parse_optional_int(maintenance_days_until_next)
    maintenance_months = parse_optional_int(maintenance_duration_months)
    if maintenance_days is not None:
        data["maintenance_next_due_date"] = (reading_date + timedelta(days=maintenance_days)).isoformat()
    maintenance_days_since_reset = parse_optional_int(maintenance_days_since_last_reset)
    if maintenance_days_since_reset is not None:
        data["maintenance_last_reset_date_estimated"] = (
            reading_date - timedelta(days=maintenance_days_since_reset)
        ).isoformat()
    maintenance_days_since_first_circulation_value = parse_optional_int(maintenance_days_since_first_circulation)
    if maintenance_days_since_first_circulation_value is not None:
        data["maintenance_first_circulation_date_estimated"] = (
            reading_date - timedelta(days=maintenance_days_since_first_circulation_value)
        ).isoformat()
    if maintenance_days is not None and maintenance_months is not None:
        plan_days = round(maintenance_months * 365 / 12)
        days_since_last = max(plan_days - maintenance_days, 0)
        data["maintenance_days_since_last_estimated"] = str(days_since_last)
        data["maintenance_last_date_estimated"] = (reading_date - timedelta(days=days_since_last)).isoformat()
    return data


def technical_reading_differences(
    current_data: dict[str, str],
    previous_reading: WorkshopTechnicalReading | None,
    current_odometer: int | None,
) -> dict[str, dict[str, str | int | None]]:
    if not previous_reading:
        return {}

    differences: dict[str, dict[str, str | int | None]] = {}
    previous_data = previous_reading.data_json or {}
    for key in sorted(set(current_data) | set(previous_data)):
        current_value = current_data.get(key)
        previous_value = previous_data.get(key)
        if current_value != previous_value:
            differences[key] = {
                "label": TECHNICAL_READING_COMPARE_LABELS.get(key, key),
                "previous": previous_value or "-",
                "current": current_value or "-",
            }
    if current_odometer != previous_reading.odometer_km:
        differences["odometer_km"] = {
            "label": TECHNICAL_READING_COMPARE_LABELS["odometer_km"],
            "previous": previous_reading.odometer_km,
            "current": current_odometer,
        }
    return differences


def normalize_technical_reading_phase(flow_phase: str | None) -> str:
    if flow_phase == "bsi_initial":
        return "initial"
    if flow_phase == "bsi_final":
        return "final"
    return flow_phase if flow_phase in WORKSHOP_READING_PHASES else "initial"


def technical_reading_snapshot(reading: WorkshopTechnicalReading) -> dict[str, object | None]:
    return {
        "reading_type": reading.reading_type,
        "reading_date": reading.reading_date.isoformat() if reading.reading_date else None,
        "odometer_km": reading.odometer_km,
        "summary": reading.summary,
        "data_json": reading.data_json or {},
        "storage_provider": reading.storage_provider,
        "external_url": reading.external_url,
        "status": reading.status,
        "replaced_by_id": reading.replaced_by_id,
        "void_reason": reading.void_reason,
    }


def technical_reading_form_values(reading: WorkshopTechnicalReading) -> dict[str, str]:
    data = reading.data_json or {}
    values = {key: str(value) for key, value in data.items() if value is not None}
    values.update(
        {
            "reading_type": reading.reading_type or "technical",
            "flow_phase": normalize_technical_reading_phase(str(data.get("flow_phase") or "")),
            "reading_date": reading.reading_date.isoformat() if reading.reading_date else "",
            "odometer_km": str(reading.odometer_km) if reading.odometer_km is not None else "",
            "summary": reading.summary or "",
            "external_url": reading.external_url or "",
            "storage_provider": reading.storage_provider or "external",
        }
    )
    return values


def compact_reading_data_from_form(form, reading_date: date) -> dict[str, str]:
    def field(name: str) -> str:
        value = form.get(name, "")
        return str(value or "")

    return compact_reading_data(
        reading_date=reading_date,
        maintenance_last_reset_km=field("maintenance_last_reset_km"),
        maintenance_km_until_next=field("maintenance_km_until_next"),
        maintenance_days_until_next=field("maintenance_days_until_next"),
        maintenance_days_since_last_reset=field("maintenance_days_since_last_reset"),
        maintenance_days_since_first_circulation=field("maintenance_days_since_first_circulation"),
        maintenance_temporal_limit_exceeded=field("maintenance_temporal_limit_exceeded"),
        maintenance_distance_limit_exceeded=field("maintenance_distance_limit_exceeded"),
        maintenance_count=field("maintenance_count"),
        maintenance_threshold_km=field("maintenance_threshold_km"),
        maintenance_duration_months=field("maintenance_duration_months"),
        maintenance_first_start_km=field("maintenance_first_start_km"),
        maintenance_first_duration_months=field("maintenance_first_duration_months"),
        maintenance_management_mode=field("maintenance_management_mode"),
        oil_dilution_rate=field("oil_dilution_rate"),
        oil_carbon_rate=field("oil_carbon_rate"),
        oil_anti_dilution_status=field("oil_anti_dilution_status"),
        engine_calculated_interval_km=field("engine_calculated_interval_km"),
        faults_present=field("faults_present"),
        critical_fault=field("critical_fault"),
        fault_main_status=field("fault_main_status"),
        fault_characterization=field("fault_characterization"),
        fault_odometer_km=field("fault_odometer_km"),
        recommended_action=field("recommended_action"),
        software_reference=field("software_reference"),
        calibration_edition=field("calibration_edition"),
        download_date=field("download_date"),
        download_count=field("download_count"),
        battery_voltage=field("battery_voltage"),
        fault_codes=field("fault_codes"),
        bsi_notes=field("bsi_notes"),
        systems_checked=field("systems_checked"),
        recommendation=field("recommendation"),
        flow_phase=normalize_technical_reading_phase(field("flow_phase")),
        machine_source=field("machine_source"),
    )


def normalize_workshop_service_fields(
    service_family: str,
    service_detail: str | None,
    service_axis: str | None,
) -> tuple[str, str | None, str]:
    allowed_service_families = {code for code, _ in WORKSHOP_SERVICE_FAMILIES}
    allowed_service_axes = {code for code, _ in WORKSHOP_SERVICE_AXES}
    if service_family not in allowed_service_families:
        return "", None, "not_defined"

    allowed_details = {
        code
        for code, _, family in WORKSHOP_SERVICE_DETAILS
        if family == service_family or (family == "any" and service_family in WORKSHOP_SERVICE_DETAIL_FAMILIES)
    }
    clean_detail = service_detail if service_detail in allowed_details else None
    clean_axis = (
        service_axis
        if service_family in WORKSHOP_SERVICE_AXIS_FAMILIES and service_axis in allowed_service_axes
        else "not_defined"
    )
    return service_family, clean_detail, clean_axis


def normalize_workshop_service_entries(
    service_families: list[str],
    service_details: list[str],
    service_axes: list[str],
    service_notes: list[str],
    fallback_family: str = "",
    fallback_detail: str | None = "",
    fallback_axis: str | None = "not_defined",
    fallback_note: str = "",
) -> list[tuple[str, str | None, str, str]]:
    entries: list[tuple[str, str | None, str, str]] = []
    if service_families:
        for index, family in enumerate(service_families):
            detail = service_details[index] if index < len(service_details) else ""
            axis = service_axes[index] if index < len(service_axes) else "not_defined"
            note = service_notes[index] if index < len(service_notes) else ""
            clean_family, clean_detail, clean_axis = normalize_workshop_service_fields(family, detail, axis)
            if clean_family:
                entries.append((clean_family, clean_detail, clean_axis, note.strip()))
        return entries

    clean_family, clean_detail, clean_axis = normalize_workshop_service_fields(
        fallback_family,
        fallback_detail,
        fallback_axis,
    )
    if clean_family:
        entries.append((clean_family, clean_detail, clean_axis, fallback_note.strip()))
    return entries


def workshop_service_title(service_entries: list[tuple[str, str | None, str, str]], other_title: str = "") -> str:
    if other_title.strip() and any(entry[0] == "other" for entry in service_entries):
        return other_title.strip()[:200]
    labels = [WORKSHOP_SERVICE_FAMILY_LABELS.get(family, family) for family, _, _, _ in service_entries]
    return "_".join(label for label in labels if label)[:200]


def canonical_vehicle_archive_name(plate: str | None, vin: str | None) -> str:
    clean_plate = ((plate or "")).strip().upper()
    clean_vin = ((vin or "")).strip().upper()
    if clean_plate and clean_vin:
        return f"{clean_plate}_{clean_vin}"
    if clean_plate:
        return clean_plate
    if clean_vin:
        return clean_vin
    return "_POR_ASSOCIAR"


def sanitize_archive_component(value: str | None, fallback: str) -> str:
    text = (value or "").strip()
    if not text:
        return fallback
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text or fallback


def vehicle_archive_base_folder(plate: str | None, vin: str | None) -> str:
    return f"Frota/{canonical_vehicle_archive_name(plate, vin)}"


def local_document_storage_folder(
    folder_path: str | None,
    *,
    plate: str | None,
    vin: str | None,
) -> Path:
    canonical_path = (folder_path or vehicle_archive_base_folder(plate, vin)).strip().strip("/")
    parts = [sanitize_archive_component(part, "_") for part in canonical_path.split("/") if part.strip()]
    return APP_PROJECT_ROOT.joinpath("uploads", "documents", *parts)


def suggest_workshop_process_folder_path(process: WorkshopProcess, vehicle: Vehicle | None) -> str:
    reference_year = (process.opened_on or date.today()).year
    process_ref = f"OF-{reference_year}-{process.id:05d}"
    archive_name = canonical_vehicle_archive_name(vehicle.plate if vehicle else "", vehicle.vin if vehicle else "")
    if archive_name != "_POR_ASSOCIAR":
        return f"Frota/{archive_name}/02_Documentacao_Tecnica/Processos/{process_ref}"
    return f"Frota/_POR_ASSOCIAR/02_Documentacao_Tecnica/Processos/{reference_year}/{process_ref}"


def suggest_workshop_process_document_folder(
    process: WorkshopProcess,
    vehicle: Vehicle | None,
    section: str,
) -> str:
    base_path = process.document_folder_path or suggest_workshop_process_folder_path(process, vehicle)
    return f"{base_path}/{section}"


def render_workshop_detail(
    request: Request,
    db,
    process: WorkshopProcess,
    *,
    noted: str | None = None,
    evidence_created: str | None = None,
    technical_reading_created: str | None = None,
    reception_saved: str | None = None,
    incident_created: str | None = None,
    document_created: str | None = None,
    document_zone_saved: str | None = None,
    feedback_saved: str | None = None,
    error: str | None = None,
    status_code: int = 200,
):
    vehicle = db.get(Vehicle, process.vehicle_id)
    notes = db.scalars(
        select(WorkshopProcessNote)
        .where(WorkshopProcessNote.process_id == process.id)
        .order_by(WorkshopProcessNote.created_at.desc())
    ).all()
    evidences = db.scalars(
        select(WorkshopProcessEvidence)
        .where(WorkshopProcessEvidence.process_id == process.id)
        .order_by(WorkshopProcessEvidence.id.desc())
    ).all()
    incidents = db.scalars(
        select(Incident)
        .where(Incident.workshop_process_id == process.id)
        .order_by(Incident.id.desc())
    ).all()
    incident_evidences = db.scalars(
        select(IncidentEvidence)
        .where(IncidentEvidence.incident_id.in_([item.id for item in incidents]))
        .order_by(IncidentEvidence.id.desc())
    ).all() if incidents else []
    incident_evidences_by_incident: dict[int, list[IncidentEvidence]] = {}
    for item in incident_evidences:
        incident_evidences_by_incident.setdefault(item.incident_id, []).append(item)
    documents = db.scalars(
        select(Document)
        .where(Document.workshop_process_id == process.id)
        .order_by(Document.id.desc())
        .limit(20)
    ).all()
    services = db.scalars(
        select(WorkshopProcessService)
        .where(WorkshopProcessService.process_id == process.id)
        .order_by(WorkshopProcessService.id)
    ).all()
    reception_service = services[0] if services else None
    reception_services_by_family: dict[str, WorkshopProcessService] = {}
    for service in services:
        reception_services_by_family.setdefault(service.service_family, service)
    reception_note_data = {
        "received_at": "",
        "service_note": "",
        "reception_note": "",
    }
    for note in notes:
        note_lines = (note.note or "").splitlines()
        if not note_lines or note_lines[0].strip() != "Receção confirmada.":
            continue
        for line in note_lines[1:]:
            if line.startswith("Data/hora entrada: "):
                raw_received_at = line.replace("Data/hora entrada: ", "", 1).strip()
                reception_note_data["received_at"] = "" if raw_received_at == "-" else raw_received_at
            elif line.startswith("Observação do serviço: "):
                reception_note_data["service_note"] = line.replace("Observação do serviço: ", "", 1).strip()
            elif line.startswith("Observação inicial: "):
                reception_note_data["reception_note"] = line.replace("Observação inicial: ", "", 1).strip()
        break
    technical_readings = db.scalars(
        select(WorkshopTechnicalReading)
        .where(WorkshopTechnicalReading.process_id == process.id)
        .order_by(
            WorkshopTechnicalReading.reading_date.is_(None),
            WorkshopTechnicalReading.reading_date.desc(),
            WorkshopTechnicalReading.id.desc(),
        )
    ).all()
    previous_technical_readings = db.scalars(
        select(WorkshopTechnicalReading)
        .where(
            WorkshopTechnicalReading.vehicle_id == process.vehicle_id,
            WorkshopTechnicalReading.status == "active",
            or_(
                WorkshopTechnicalReading.process_id.is_(None),
                WorkshopTechnicalReading.process_id != process.id,
            ),
        )
        .order_by(
            WorkshopTechnicalReading.reading_date.is_(None),
            WorkshopTechnicalReading.reading_date.desc(),
            WorkshopTechnicalReading.id.desc(),
        )
        .limit(5)
    ).all()
    phase_records = workshop_phase_records(notes, process, technical_readings)
    phase_activity = workshop_phase_activity(
        notes=notes,
        services=services,
        evidences=evidences,
        technical_readings=technical_readings,
    )
    phase_user_ids = {
        record.get("user_id")
        for record in phase_records.values()
        if record.get("user_id")
    }
    phase_users = (
        db.scalars(select(User).where(User.id.in_(phase_user_ids))).all()
        if phase_user_ids
        else []
    )
    phase_user_labels = {item.id: item.name or item.email for item in phase_users}
    vehicle_snapshot = db.scalar(
        select(VehicleExternalSnapshot)
        .where(VehicleExternalSnapshot.vehicle_id == process.vehicle_id)
        .order_by(VehicleExternalSnapshot.updated_at.desc())
    )
    workshop_flow_steps = workshop_flow_steps_for_vehicle(vehicle)
    workshop_flow_order = ["opening", "reception", *[step["code"] for step in workshop_flow_steps]]
    workshop_flow_titles = {step["code"]: step["title"] for step in workshop_flow_steps}
    completed_flow_statuses = {"opening"}
    if process.status == "reception" or process.opened_on or process.km_entry:
        completed_flow_statuses.add("reception")
    completed_flow_statuses.update(phase_records.keys())
    note_text = "\n".join(item.note or "" for item in notes)
    for code, label in WORKSHOP_STATUS_LABELS.items():
        if label and label in note_text:
            completed_flow_statuses.add(code)
    if technical_readings:
        for reading in technical_readings:
            flow_phase = (reading.data_json or {}).get("flow_phase")
            if flow_phase in WORKSHOP_READING_PHASES:
                completed_flow_statuses.add(WORKSHOP_READING_PHASES[flow_phase]["flow_status"])
            elif flow_phase in {"bsi_initial", "bsi_final"}:
                completed_flow_statuses.add(flow_phase)
        if not completed_flow_statuses.intersection({"bsi_initial", "bsi_final"}):
            completed_flow_statuses.add("bsi_initial")
    if process.status in workshop_flow_order:
        current_flow_index = workshop_flow_order.index(process.status)
    elif process.status == "diagnosis":
        current_flow_index = workshop_flow_order.index("bsi_initial")
    elif process.status in {"waiting_analysis", "waiting_parts", "in_progress", "validation"}:
        current_flow_index = workshop_flow_order.index("decision")
    else:
        current_flow_index = 0
    suggested_document_folder_path = process.document_folder_path or suggest_workshop_process_folder_path(process, vehicle)
    workshop_alerts = build_workshop_alerts(
        process=process,
        vehicle=vehicle,
        phase_records=phase_records,
        completed_flow_statuses=completed_flow_statuses,
        current_flow_index=current_flow_index,
        workshop_flow_order=workshop_flow_order,
        documents=documents,
        evidences=evidences,
        incidents=incidents,
        technical_readings=technical_readings,
        notes=notes,
    )
    return templates.TemplateResponse(
        request,
        "workshop_detail.html",
        {
            "process": process,
            "vehicle": vehicle,
            "vehicle_context": rentway_vehicle_context(vehicle_snapshot),
            "notes": notes,
            "evidences": evidences,
            "incidents": incidents,
            "incident_evidences_by_incident": incident_evidences_by_incident,
            "documents": documents,
            "services": services,
            "reception_service": reception_service,
            "reception_services_by_family": reception_services_by_family,
            "reception_note_data": reception_note_data,
            "technical_readings": technical_readings,
            "previous_technical_readings": previous_technical_readings,
            "phase_records": phase_records,
            "phase_activity": phase_activity,
            "phase_user_labels": phase_user_labels,
            "workshop_flow_steps": workshop_flow_steps,
            "workshop_flow_order": workshop_flow_order,
            "workshop_flow_titles": workshop_flow_titles,
            "is_stellantis_vehicle": is_stellantis_vehicle(vehicle),
            "completed_flow_statuses": completed_flow_statuses,
            "current_flow_index": current_flow_index,
            "noted": noted,
            "evidence_created": evidence_created,
            "technical_reading_created": technical_reading_created,
            "reception_saved": reception_saved,
            "incident_created": incident_created,
            "document_created": document_created,
            "document_zone_saved": document_zone_saved,
            "feedback_saved": feedback_saved,
            "error": error,
            "statuses": WORKSHOP_STATUSES,
            "decisions": WORKSHOP_DECISIONS,
            "evidence_types": WORKSHOP_EVIDENCE_TYPES,
            "evidence_categories": WORKSHOP_EVIDENCE_CATEGORIES,
            "evidence_statuses": WORKSHOP_EVIDENCE_STATUSES,
            "opening_type_labels": WORKSHOP_OPENING_LABELS,
            "status_labels": WORKSHOP_STATUS_LABELS,
            "decision_labels": WORKSHOP_DECISION_LABELS,
            "service_families": WORKSHOP_SERVICE_FAMILIES,
            "service_details": WORKSHOP_SERVICE_DETAILS,
            "service_axes": WORKSHOP_SERVICE_AXES,
            "service_detail_families": WORKSHOP_SERVICE_DETAIL_FAMILIES,
            "service_axis_families": WORKSHOP_SERVICE_AXIS_FAMILIES,
            "service_statuses": WORKSHOP_SERVICE_STATUSES,
            "service_family_labels": WORKSHOP_SERVICE_FAMILY_LABELS,
            "service_detail_labels": WORKSHOP_SERVICE_DETAIL_LABELS,
            "service_axis_labels": WORKSHOP_SERVICE_AXIS_LABELS,
            "service_status_labels": WORKSHOP_SERVICE_STATUS_LABELS,
            "evidence_type_labels": WORKSHOP_EVIDENCE_TYPE_LABELS,
            "evidence_category_labels": WORKSHOP_EVIDENCE_CATEGORY_LABELS,
            "evidence_status_labels": WORKSHOP_EVIDENCE_STATUS_LABELS,
            "technical_reading_types": WORKSHOP_READING_TYPES,
            "technical_reading_type_labels": WORKSHOP_READING_TYPE_LABELS,
            "technical_reading_field_labels": TECHNICAL_READING_COMPARE_LABELS,
            "technical_reading_phase_labels": WORKSHOP_READING_PHASE_DISPLAY_LABELS,
            "technical_reading_status_labels": WORKSHOP_READING_STATUS_LABELS,
            "incident_types": INCIDENT_TYPES,
            "incident_type_labels": INCIDENT_TYPE_LABELS,
            "incident_categories": INCIDENT_CATEGORIES,
            "incident_category_labels": INCIDENT_CATEGORY_LABELS,
            "incident_severities": INCIDENT_SEVERITIES,
            "incident_severity_labels": INCIDENT_SEVERITY_LABELS,
            "incident_status_labels": INCIDENT_STATUS_LABELS,
            "incident_evidence_types": INCIDENT_EVIDENCE_TYPES,
            "incident_evidence_type_labels": INCIDENT_EVIDENCE_TYPE_LABELS,
            "document_statuses": DOCUMENT_STATUSES,
            "document_status_labels": DOCUMENT_STATUS_LABELS,
            "document_area_labels": DOCUMENT_AREA_LABELS,
            "document_types": DOCUMENT_TYPES,
            "document_type_labels": DOCUMENT_TYPE_LABELS,
            "document_type_areas": DOCUMENT_TYPE_AREAS,
            "document_sources": DOCUMENT_SOURCES,
            "suggested_document_folder_path": suggested_document_folder_path,
            "workshop_alerts": workshop_alerts,
        },
        status_code=status_code,
    )


@web_router.get("/workshop/{process_id}", response_class=HTMLResponse)
def workshop_detail(
    request: Request,
    process_id: int,
    noted: str | None = None,
    evidence_created: str | None = None,
    technical_reading_created: str | None = None,
    reception_saved: str | None = None,
    incident_created: str | None = None,
    document_created: str | None = None,
    document_zone_saved: str | None = None,
    feedback_saved: str | None = None,
    error: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        return render_workshop_detail(
            request,
            db,
            process,
            noted=noted,
            evidence_created=evidence_created,
            technical_reading_created=technical_reading_created,
            reception_saved=reception_saved,
            incident_created=incident_created,
            document_created=document_created,
            document_zone_saved=document_zone_saved,
            feedback_saved=feedback_saved,
            error=error,
        )


@web_router.get("/workshop/{process_id}/report", response_class=HTMLResponse)
def workshop_report(request: Request, process_id: int):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop/manage", status_code=303)
        vehicle = db.get(Vehicle, process.vehicle_id)
        vehicle_snapshot = db.scalar(
            select(VehicleExternalSnapshot)
            .where(VehicleExternalSnapshot.vehicle_id == process.vehicle_id)
            .order_by(VehicleExternalSnapshot.updated_at.desc())
        )
        services = db.scalars(
            select(WorkshopProcessService)
            .where(WorkshopProcessService.process_id == process.id)
            .order_by(WorkshopProcessService.id)
        ).all()
        technical_readings = db.scalars(
            select(WorkshopTechnicalReading)
            .where(WorkshopTechnicalReading.process_id == process.id)
            .order_by(
                WorkshopTechnicalReading.reading_date.is_(None),
                WorkshopTechnicalReading.reading_date.desc(),
                WorkshopTechnicalReading.id.desc(),
            )
        ).all()
        evidences = db.scalars(
            select(WorkshopProcessEvidence)
            .where(WorkshopProcessEvidence.process_id == process.id)
            .order_by(WorkshopProcessEvidence.id.desc())
        ).all()
        incidents = db.scalars(
            select(Incident)
            .where(Incident.workshop_process_id == process.id)
            .order_by(Incident.id.desc())
        ).all()
        documents = db.scalars(
            select(Document)
            .where(Document.workshop_process_id == process.id)
            .order_by(Document.id.desc())
        ).all()
        notes = db.scalars(
            select(WorkshopProcessNote)
            .where(WorkshopProcessNote.process_id == process.id)
            .order_by(WorkshopProcessNote.created_at.asc())
        ).all()

        return templates.TemplateResponse(
            request,
            "workshop_report.html",
            {
                "process": process,
                "vehicle": vehicle,
                "vehicle_context": rentway_vehicle_context(vehicle_snapshot),
                "services": services,
                "technical_readings": technical_readings,
                "evidences": evidences,
                "incidents": incidents,
                "documents": documents,
                "notes": notes,
                "status_labels": WORKSHOP_STATUS_LABELS,
                "decision_labels": WORKSHOP_DECISION_LABELS,
                "opening_type_labels": WORKSHOP_OPENING_LABELS,
                "service_family_labels": WORKSHOP_SERVICE_FAMILY_LABELS,
                "service_detail_labels": WORKSHOP_SERVICE_DETAIL_LABELS,
                "service_axis_labels": WORKSHOP_SERVICE_AXIS_LABELS,
                "service_status_labels": WORKSHOP_SERVICE_STATUS_LABELS,
                "technical_reading_type_labels": WORKSHOP_READING_TYPE_LABELS,
                "technical_reading_field_labels": TECHNICAL_READING_COMPARE_LABELS,
                "technical_reading_phase_labels": WORKSHOP_READING_PHASE_DISPLAY_LABELS,
                "evidence_type_labels": WORKSHOP_EVIDENCE_TYPE_LABELS,
                "evidence_category_labels": WORKSHOP_EVIDENCE_CATEGORY_LABELS,
                "evidence_status_labels": WORKSHOP_EVIDENCE_STATUS_LABELS,
                "incident_type_labels": INCIDENT_TYPE_LABELS,
                "incident_category_labels": INCIDENT_CATEGORY_LABELS,
                "incident_severity_labels": INCIDENT_SEVERITY_LABELS,
                "document_status_labels": DOCUMENT_STATUS_LABELS,
                "document_area_labels": DOCUMENT_AREA_LABELS,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
            },
        )


@web_router.post("/workshop/{process_id}/notes", response_class=HTMLResponse)
def workshop_add_note(
    request: Request,
    process_id: int,
    note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_note = note.strip()
    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        if not clean_note:
            return RedirectResponse(f"/workshop/{process_id}", status_code=303)

        db.add(WorkshopProcessNote(process_id=process.id, user_id=user_id, note=clean_note))
        record_audit(
            db,
            action="workshop.process.note.created",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Nota adicionada ao processo de oficina: {process.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?noted=1", status_code=303)


@web_router.post("/workshop/{process_id}/reception", response_class=HTMLResponse)
def workshop_confirm_reception(
    request: Request,
    process_id: int,
    received_at: str = Form(""),
    km_entry: str = Form(""),
    service_family: str = Form(""),
    service_detail: str = Form(""),
    service_axis: str = Form("not_defined"),
    service_note: str = Form(""),
    service_family_multi: list[str] = Form([]),
    service_detail_multi: list[str] = Form([]),
    service_axis_multi: list[str] = Form([]),
    service_note_multi: list[str] = Form([]),
    reception_note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    parsed_km = parse_optional_int(km_entry)
    received_on = parse_optional_date(received_at.split("T", 1)[0] if received_at else "")
    service_entries = normalize_workshop_service_entries(
        service_family_multi,
        service_detail_multi,
        service_axis_multi,
        service_note_multi,
        fallback_family=service_family,
        fallback_detail=service_detail,
        fallback_axis=service_axis,
        fallback_note=service_note,
    )

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)

        old_status = process.status
        old_km = process.km_entry
        process.status = "reception"
        process.opened_on = received_on or process.opened_on or date.today()
        if parsed_km is not None:
            process.km_entry = parsed_km

        if service_entries:
            existing_services = db.scalars(
                select(WorkshopProcessService)
                .where(WorkshopProcessService.process_id == process.id)
                .order_by(WorkshopProcessService.id)
            ).all()
            for clean_family, clean_detail, clean_axis, entry_note in service_entries:
                reception_service = next(
                    (
                        service
                        for service in existing_services
                        if service.service_family == clean_family
                    ),
                    None,
                )
                if reception_service:
                    reception_service.service_detail = clean_detail
                    reception_service.service_axis = clean_axis
                    reception_service.note = entry_note or reception_service.note
                else:
                    new_service = WorkshopProcessService(
                        process_id=process.id,
                        vehicle_id=process.vehicle_id,
                        service_family=clean_family,
                        service_detail=clean_detail,
                        service_axis=clean_axis,
                        status="to_assess",
                        note=entry_note or None,
                        created_by_id=user_id,
                    )
                    db.add(new_service)
                    existing_services.append(new_service)

        note_lines = [
            "Receção confirmada.",
            f"Data/hora entrada: {received_at.strip() or '-'}",
            f"KM entrada: {parsed_km if parsed_km is not None else '-'}",
        ]
        if service_entries:
            note_lines.append("Serviços/motivos:")
            for clean_family, clean_detail, clean_axis, entry_note in service_entries:
                service_line = f"- {WORKSHOP_SERVICE_FAMILY_LABELS.get(clean_family, clean_family)}"
                if clean_detail:
                    service_line += f" - {WORKSHOP_SERVICE_DETAIL_LABELS.get(clean_detail, clean_detail)}"
                if clean_axis and clean_axis != "not_defined":
                    service_line += f" - {WORKSHOP_SERVICE_AXIS_LABELS.get(clean_axis, clean_axis)}"
                if entry_note:
                    service_line += f" | {entry_note}"
                note_lines.append(service_line)
        if service_note.strip():
            note_lines.append(f"Observação do serviço: {service_note.strip()}")
        if reception_note.strip():
            note_lines.append(f"Observação inicial: {reception_note.strip()}")
        db.add(WorkshopProcessNote(process_id=process.id, user_id=user_id, note="\n".join(note_lines)))

        record_audit(
            db,
            action="workshop.process.reception.confirmed",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Receção confirmada no processo: {process.title}",
            before_json={"status": old_status, "km_entry": old_km},
            after_json={
                "status": process.status,
                "opened_on": process.opened_on.isoformat() if process.opened_on else None,
                "km_entry": process.km_entry,
                "service_families": [entry[0] for entry in service_entries],
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?reception_saved=1", status_code=303)


@web_router.post("/workshop/{process_id}/services", response_class=HTMLResponse)
def workshop_add_service(
    request: Request,
    process_id: int,
    service_family: str = Form(""),
    service_detail: str = Form(""),
    service_axis: str = Form("not_defined"),
    status: str = Form("to_assess"),
    note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    allowed_service_statuses = {code for code, _ in WORKSHOP_SERVICE_STATUSES}
    clean_service_family, clean_service_detail, clean_service_axis = normalize_workshop_service_fields(
        service_family,
        service_detail,
        service_axis,
    )
    if not clean_service_family:
        return RedirectResponse(f"/workshop/{process_id}?error=Seleciona%20o%20serviço.", status_code=303)
    if status not in allowed_service_statuses:
        status = "to_assess"

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        service = WorkshopProcessService(
            process_id=process.id,
            vehicle_id=process.vehicle_id,
            service_family=clean_service_family,
            service_detail=clean_service_detail,
            service_axis=clean_service_axis,
            status=status,
            note=note.strip() or None,
            created_by_id=user_id,
        )
        db.add(service)
        db.flush()
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Serviço adicionado: "
                    f"{WORKSHOP_SERVICE_FAMILY_LABELS.get(clean_service_family, clean_service_family)}"
                    f"{' - ' + WORKSHOP_SERVICE_DETAIL_LABELS.get(clean_service_detail, clean_service_detail) if clean_service_detail else ''}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.process.service.created",
            entity_type="workshop_process_service",
            entity_id=service.id,
            detail=f"Serviço adicionado ao processo: {process.title}",
            after_json={
                "workshop_process_id": process.id,
                "vehicle_id": process.vehicle_id,
                "service_family": clean_service_family,
                "service_detail": clean_service_detail,
                "service_axis": clean_service_axis,
                "status": status,
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?noted=1", status_code=303)


@web_router.post("/workshop/{process_id}/evidences", response_class=HTMLResponse)
def workshop_add_evidence(
    request: Request,
    process_id: int,
    phase: str = Form(...),
    evidence_type: str = Form(...),
    anomaly_category: str = Form(...),
    status: str = Form("registered"),
    description: str = Form(""),
    external_url: str = Form(""),
    storage_provider: str = Form("external"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    allowed_phases = {code for code, _ in WORKSHOP_STATUSES}
    allowed_types = {code for code, _ in WORKSHOP_EVIDENCE_TYPES}
    allowed_categories = {code for code, _ in WORKSHOP_EVIDENCE_CATEGORIES}
    allowed_statuses = {code for code, _ in WORKSHOP_EVIDENCE_STATUSES}
    if phase not in allowed_phases:
        phase = "diagnosis"
    if evidence_type not in allowed_types:
        evidence_type = "photo"
    if anomaly_category not in allowed_categories:
        anomaly_category = "other"
    if status not in allowed_statuses:
        status = "registered"

    clean_description = description.strip()
    clean_url = external_url.strip()
    clean_provider = storage_provider.strip() or "external"

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        if not clean_description:
            clean_description = "Evidência registada sem descrição."

        evidence = WorkshopProcessEvidence(
            process_id=process.id,
            vehicle_id=process.vehicle_id,
            user_id=user_id,
            phase=phase,
            evidence_type=evidence_type,
            anomaly_category=anomaly_category,
            status=status,
            description=clean_description,
            storage_provider=clean_provider,
            external_url=clean_url or None,
        )
        db.add(evidence)
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Evidência registada: "
                    f"{WORKSHOP_EVIDENCE_CATEGORY_LABELS.get(anomaly_category, anomaly_category)} - "
                    f"{clean_description}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.process.evidence.created",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Evidência de anomalia registada: {process.title}",
            after_json={
                "phase": phase,
                "evidence_type": evidence_type,
                "anomaly_category": anomaly_category,
                "status": status,
                "has_external_url": bool(clean_url),
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?evidence_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/technical-readings", response_class=HTMLResponse)
def workshop_add_technical_reading(
    request: Request,
    process_id: int,
    reading_type: str = Form("technical"),
    reading_date: str = Form(""),
    odometer_km: str = Form(""),
    summary: str = Form(""),
    maintenance_last_reset_km: str = Form(""),
    maintenance_km_until_next: str = Form(""),
    maintenance_days_until_next: str = Form(""),
    maintenance_days_since_last_reset: str = Form(""),
    maintenance_days_since_first_circulation: str = Form(""),
    maintenance_temporal_limit_exceeded: str = Form(""),
    maintenance_distance_limit_exceeded: str = Form(""),
    maintenance_count: str = Form(""),
    maintenance_threshold_km: str = Form(""),
    maintenance_duration_months: str = Form(""),
    maintenance_first_start_km: str = Form(""),
    maintenance_first_duration_months: str = Form(""),
    maintenance_management_mode: str = Form(""),
    oil_dilution_rate: str = Form(""),
    oil_carbon_rate: str = Form(""),
    oil_anti_dilution_status: str = Form(""),
    engine_calculated_interval_km: str = Form(""),
    faults_present: str = Form(""),
    critical_fault: str = Form(""),
    fault_main_status: str = Form(""),
    fault_characterization: str = Form(""),
    fault_odometer_km: str = Form(""),
    recommended_action: str = Form(""),
    software_reference: str = Form(""),
    calibration_edition: str = Form(""),
    download_date: str = Form(""),
    download_count: str = Form(""),
    battery_voltage: str = Form(""),
    fault_codes: str = Form(""),
    bsi_notes: str = Form(""),
    systems_checked: str = Form(""),
    recommendation: str = Form(""),
    flow_phase: str = Form("bsi_initial"),
    machine_source: str = Form(""),
    external_url: str = Form(""),
    storage_provider: str = Form("external"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    if flow_phase not in WORKSHOP_READING_PHASES:
        return RedirectResponse(f"/workshop/{process_id}?error=Fase%20de%20leitura%20inválida.", status_code=303)
    allowed_reading_types = WORKSHOP_READING_PHASES[flow_phase]["allowed_types"]
    if reading_type not in allowed_reading_types:
        return RedirectResponse(
            f"/workshop/{process_id}?error=Tipo%20de%20relatório%20não%20permitido%20para%20esta%20fase.",
            status_code=303,
        )
    parsed_reading_date = parse_optional_date(reading_date) or date.today()
    reading_data = compact_reading_data(
        reading_date=parsed_reading_date,
        maintenance_last_reset_km=maintenance_last_reset_km,
        maintenance_km_until_next=maintenance_km_until_next,
        maintenance_days_until_next=maintenance_days_until_next,
        maintenance_days_since_last_reset=maintenance_days_since_last_reset,
        maintenance_days_since_first_circulation=maintenance_days_since_first_circulation,
        maintenance_temporal_limit_exceeded=maintenance_temporal_limit_exceeded,
        maintenance_distance_limit_exceeded=maintenance_distance_limit_exceeded,
        maintenance_count=maintenance_count,
        maintenance_threshold_km=maintenance_threshold_km,
        maintenance_duration_months=maintenance_duration_months,
        maintenance_first_start_km=maintenance_first_start_km,
        maintenance_first_duration_months=maintenance_first_duration_months,
        maintenance_management_mode=maintenance_management_mode,
        oil_dilution_rate=oil_dilution_rate,
        oil_carbon_rate=oil_carbon_rate,
        oil_anti_dilution_status=oil_anti_dilution_status,
        engine_calculated_interval_km=engine_calculated_interval_km,
        faults_present=faults_present,
        critical_fault=critical_fault,
        fault_main_status=fault_main_status,
        fault_characterization=fault_characterization,
        fault_odometer_km=fault_odometer_km,
        recommended_action=recommended_action,
        software_reference=software_reference,
        calibration_edition=calibration_edition,
        download_date=download_date,
        download_count=download_count,
        battery_voltage=battery_voltage,
        fault_codes=fault_codes,
        bsi_notes=bsi_notes,
        systems_checked=systems_checked,
        recommendation=recommendation,
        flow_phase=flow_phase,
        machine_source=machine_source,
    )
    clean_summary = summary.strip()
    clean_url = external_url.strip()
    clean_provider = storage_provider.strip() or "external"
    parsed_odometer = parse_optional_int(odometer_km)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        previous_reading = db.scalar(
            select(WorkshopTechnicalReading)
            .where(
                WorkshopTechnicalReading.vehicle_id == process.vehicle_id,
                WorkshopTechnicalReading.status == "active",
            )
            .order_by(
                WorkshopTechnicalReading.reading_date.is_(None),
                WorkshopTechnicalReading.reading_date.desc(),
                WorkshopTechnicalReading.id.desc(),
            )
            .limit(1)
        )
        differences = technical_reading_differences(reading_data, previous_reading, parsed_odometer)
        reading = WorkshopTechnicalReading(
            process_id=process.id,
            vehicle_id=process.vehicle_id,
            user_id=user_id,
            reading_type=reading_type,
            reading_date=parsed_reading_date,
            odometer_km=parsed_odometer,
            summary=clean_summary or None,
            data_json=reading_data or None,
            differences_json=differences or None,
            storage_provider=clean_provider,
            external_url=clean_url or None,
        )
        db.add(reading)
        db.flush()
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Leitura técnica registada: "
                    f"{WORKSHOP_READING_PHASES[flow_phase]['label']} - "
                    f"{WORKSHOP_READING_TYPE_LABELS.get(reading_type, reading_type)}"
                    f"{' - ' + clean_summary if clean_summary else ''}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.technical_reading.created",
            entity_type="workshop_technical_reading",
            entity_id=reading.id,
            detail=f"Leitura técnica registada no processo: {process.title}",
            after_json={
                "workshop_process_id": process.id,
                "vehicle_id": process.vehicle_id,
                "reading_type": reading_type,
                "flow_phase": flow_phase,
                "fields": sorted(reading_data),
                "has_external_url": bool(clean_url),
                "differences": bool(differences),
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?technical_reading_created=1", status_code=303)


@web_router.get("/workshop/{process_id}/technical-readings/{reading_id}/edit", response_class=HTMLResponse)
def workshop_edit_technical_reading(request: Request, process_id: int, reading_id: int):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        reading = db.get(WorkshopTechnicalReading, reading_id)
        if not process or not reading or reading.process_id != process.id:
            return RedirectResponse("/workshop", status_code=303)
        vehicle = db.get(Vehicle, process.vehicle_id)
        technical_readings = db.scalars(
            select(WorkshopTechnicalReading)
            .where(WorkshopTechnicalReading.process_id == process.id)
            .order_by(
                WorkshopTechnicalReading.reading_date.is_(None),
                WorkshopTechnicalReading.reading_date.desc(),
                WorkshopTechnicalReading.id.desc(),
            )
        ).all()
        form_values = technical_reading_form_values(reading)
        fixed_phase = normalize_technical_reading_phase(form_values.get("flow_phase"))
        return templates.TemplateResponse(
            request,
            "workshop_technical_reading_edit.html",
            {
                "process": process,
                "vehicle": vehicle,
                "reading": reading,
                "technical_readings": technical_readings,
                "technical_reading_types": WORKSHOP_READING_TYPES,
                "technical_reading_type_labels": WORKSHOP_READING_TYPE_LABELS,
                "technical_reading_status_labels": WORKSHOP_READING_STATUS_LABELS,
                "reading_form_values": form_values,
                "fixed_reading_phase": fixed_phase,
                "reading_allowed_types": WORKSHOP_READING_PHASES[fixed_phase]["allowed_types"],
                "reading_submit_label": "Guardar correção",
            },
        )


@web_router.post("/workshop/{process_id}/technical-readings/{reading_id}/update", response_class=HTMLResponse)
async def workshop_update_technical_reading(request: Request, process_id: int, reading_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    form = await request.form()
    flow_phase = normalize_technical_reading_phase(str(form.get("flow_phase") or ""))
    reading_type = str(form.get("reading_type") or "")
    if flow_phase not in WORKSHOP_READING_PHASES:
        return RedirectResponse(f"/workshop/{process_id}?error=Fase%20de%20leitura%20inválida.", status_code=303)
    if reading_type not in WORKSHOP_READING_PHASES[flow_phase]["allowed_types"]:
        return RedirectResponse(
            f"/workshop/{process_id}?error=Tipo%20de%20relatório%20não%20permitido%20para%20esta%20fase.",
            status_code=303,
        )

    parsed_reading_date = parse_optional_date(str(form.get("reading_date") or "")) or date.today()
    parsed_odometer = parse_optional_int(str(form.get("odometer_km") or ""))
    reading_data = compact_reading_data_from_form(form, parsed_reading_date)
    clean_summary = str(form.get("summary") or "").strip()
    clean_url = str(form.get("external_url") or "").strip()
    clean_provider = str(form.get("storage_provider") or "").strip() or "external"

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        reading = db.get(WorkshopTechnicalReading, reading_id)
        if not process or not reading or reading.process_id != process.id:
            return RedirectResponse("/workshop", status_code=303)
        if reading.status != "active":
            return RedirectResponse(
                f"/workshop/{process_id}?error=Só%20é%20possível%20editar%20leituras%20ativas.",
                status_code=303,
            )

        before = technical_reading_snapshot(reading)
        previous_reading = db.scalar(
            select(WorkshopTechnicalReading)
            .where(
                WorkshopTechnicalReading.vehicle_id == process.vehicle_id,
                WorkshopTechnicalReading.id != reading.id,
                WorkshopTechnicalReading.status == "active",
            )
            .order_by(
                WorkshopTechnicalReading.reading_date.is_(None),
                WorkshopTechnicalReading.reading_date.desc(),
                WorkshopTechnicalReading.id.desc(),
            )
            .limit(1)
        )
        differences = technical_reading_differences(reading_data, previous_reading, parsed_odometer)
        reading.reading_type = reading_type
        reading.reading_date = parsed_reading_date
        reading.odometer_km = parsed_odometer
        reading.summary = clean_summary or None
        reading.data_json = reading_data or None
        reading.differences_json = differences or None
        reading.storage_provider = clean_provider
        reading.external_url = clean_url or None
        reading.updated_by_id = user_id

        after = technical_reading_snapshot(reading)
        changed_fields = [field for field in after if before.get(field) != after.get(field)]
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Leitura técnica corrigida: "
                    f"{WORKSHOP_READING_TYPE_LABELS.get(reading_type, reading_type)}"
                    f" ({', '.join(changed_fields) if changed_fields else 'sem alterações relevantes'})."
                ),
            )
        )
        record_audit(
            db,
            action="workshop.technical_reading.updated",
            entity_type="workshop_technical_reading",
            entity_id=reading.id,
            detail=f"Leitura técnica corrigida no processo: {process.title}",
            before_json=before,
            after_json=after,
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?technical_reading_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/technical-readings/{reading_id}/void", response_class=HTMLResponse)
def workshop_void_technical_reading(
    request: Request,
    process_id: int,
    reading_id: int,
    reason: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_reason = reason.strip()
    if not clean_reason:
        return RedirectResponse(
            f"/workshop/{process_id}?error=Indica%20o%20motivo%20para%20anular%20a%20leitura.",
            status_code=303,
        )

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        reading = db.get(WorkshopTechnicalReading, reading_id)
        if not process or not reading or reading.process_id != process.id:
            return RedirectResponse("/workshop", status_code=303)
        if reading.status != "active":
            return RedirectResponse(
                f"/workshop/{process_id}?error=A%20leitura%20já%20não%20está%20ativa.",
                status_code=303,
            )
        before = technical_reading_snapshot(reading)
        reading.status = "voided"
        reading.void_reason = clean_reason
        reading.voided_by_id = user_id
        reading.voided_at = datetime.now(UTC)
        reading.updated_by_id = user_id
        after = technical_reading_snapshot(reading)
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Leitura técnica anulada: "
                    f"{WORKSHOP_READING_TYPE_LABELS.get(reading.reading_type, reading.reading_type)}. "
                    f"Motivo: {clean_reason}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.technical_reading.voided",
            entity_type="workshop_technical_reading",
            entity_id=reading.id,
            detail=f"Leitura técnica anulada no processo: {process.title}",
            before_json=before,
            after_json=after,
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?technical_reading_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/technical-readings/{reading_id}/replace", response_class=HTMLResponse)
def workshop_replace_technical_reading(
    request: Request,
    process_id: int,
    reading_id: int,
    reason: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_reason = reason.strip() or "Substituição por nova leitura corrigida."
    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        reading = db.get(WorkshopTechnicalReading, reading_id)
        if not process or not reading or reading.process_id != process.id:
            return RedirectResponse("/workshop", status_code=303)
        if reading.status != "active":
            return RedirectResponse(
                f"/workshop/{process_id}?error=Só%20é%20possível%20substituir%20leituras%20ativas.",
                status_code=303,
            )

        before = technical_reading_snapshot(reading)
        replacement = WorkshopTechnicalReading(
            process_id=reading.process_id,
            vehicle_id=reading.vehicle_id,
            user_id=user_id,
            reading_type=reading.reading_type,
            reading_date=reading.reading_date,
            odometer_km=reading.odometer_km,
            summary=reading.summary,
            data_json=dict(reading.data_json or {}),
            differences_json=dict(reading.differences_json or {}),
            storage_provider=reading.storage_provider,
            external_url=reading.external_url,
            status="active",
        )
        db.add(replacement)
        db.flush()
        reading.status = "replaced"
        reading.replaced_by_id = replacement.id
        reading.void_reason = clean_reason
        reading.updated_by_id = user_id
        after = technical_reading_snapshot(reading)

        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    "Leitura técnica substituída: "
                    f"{WORKSHOP_READING_TYPE_LABELS.get(reading.reading_type, reading.reading_type)}. "
                    f"Motivo: {clean_reason}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.technical_reading.replaced",
            entity_type="workshop_technical_reading",
            entity_id=reading.id,
            detail=f"Leitura técnica substituída no processo: {process.title}",
            before_json=before,
            after_json={**after, "replacement_id": replacement.id},
            user_id=user_id,
        )
        db.commit()
        replacement_id = replacement.id

    return RedirectResponse(
        f"/workshop/{process_id}/technical-readings/{replacement_id}/edit?replaced=1",
        status_code=303,
    )


@web_router.post("/workshop/{process_id}/incidents", response_class=HTMLResponse)
def workshop_create_incident(
    request: Request,
    process_id: int,
    title: str = Form(""),
    description: str = Form(""),
    incident_type: str = Form("technical"),
    category: str = Form("other"),
    severity: str = Form("medium"),
    evidence_type: str = Form("photo"),
    evidence_description: str = Form(""),
    evidence_url: str = Form(""),
    storage_provider: str = Form("external"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    if incident_type not in INCIDENT_TYPE_LABELS:
        incident_type = "technical"
    if category not in INCIDENT_CATEGORY_LABELS:
        category = "other"
    if severity not in INCIDENT_SEVERITY_LABELS:
        severity = "medium"
    if evidence_type not in INCIDENT_EVIDENCE_TYPE_LABELS:
        evidence_type = "photo"

    clean_description = description.strip()
    clean_evidence_description = evidence_description.strip()
    clean_evidence_url = evidence_url.strip()
    clean_provider = storage_provider.strip() or "external"

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        vehicle = db.get(Vehicle, process.vehicle_id)
        clean_title = title.strip()
        if not clean_title:
            clean_title = clean_description.splitlines()[0][:160] if clean_description else ""
        if not clean_title:
            clean_title = f"Incidente {INCIDENT_CATEGORY_LABELS.get(category, category)}"

        incident = Incident(
            title=clean_title,
            description=clean_description or None,
            incident_type=incident_type,
            category=category,
            severity=severity,
            status="new",
            source="workshop",
            vehicle_id=process.vehicle_id,
            workshop_process_id=process.id,
            plate=vehicle.plate if vehicle else None,
            created_by_id=user_id,
            occurred_at=datetime.now(UTC),
        )
        db.add(incident)
        db.flush()
        db.add(
            IncidentEvent(
                incident_id=incident.id,
                action="created",
                new_value=incident.title,
                user_id=user_id,
            )
        )
        if clean_evidence_url or clean_evidence_description:
            db.add(
                IncidentEvidence(
                    incident_id=incident.id,
                    evidence_type=evidence_type,
                    description=clean_evidence_description or None,
                    storage_provider=clean_provider,
                    external_url=clean_evidence_url or None,
                    user_id=user_id,
                )
            )
            db.add(
                IncidentEvent(
                    incident_id=incident.id,
                    action="evidence_added",
                    new_value=INCIDENT_EVIDENCE_TYPE_LABELS.get(evidence_type, evidence_type),
                    user_id=user_id,
                )
            )
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=f"Incidente criado: {incident.title}",
            )
        )
        record_audit(
            db,
            action="incident.created",
            entity_type="incident",
            entity_id=incident.id,
            detail=f"Incidente criado no processo de oficina: {incident.title}",
            after_json={
                "workshop_process_id": process.id,
                "vehicle_id": process.vehicle_id,
                "category": category,
                "severity": severity,
                "has_evidence": bool(clean_evidence_url or clean_evidence_description),
            },
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?incident_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/documents", response_class=HTMLResponse)
def workshop_create_document(
    request: Request,
    process_id: int,
    title: str = Form(""),
    document_type: str = Form("workshop_evidence"),
    status: str = Form("associated"),
    document_date: str = Form(""),
    source: str = Form("workshop"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    supplier_name: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        vehicle = db.get(Vehicle, process.vehicle_id)
        folder_path = process.document_folder_path or suggest_workshop_process_folder_path(process, vehicle)
        try:
            add_document_record(
                db,
                title=title,
                classification="workshop",
                document_type=document_type if document_type in DOCUMENT_TYPE_LABELS else "workshop_evidence",
                status=status,
                document_date=parse_optional_date(document_date),
                source=source,
                entry_channel=entry_channel,
                source_sender=source_sender,
                source_subject=source_subject,
                url_original=url_original,
                url_archive=url_archive,
                plate=(vehicle.plate if vehicle else "") or "",
                vehicle_id=process.vehicle_id,
                supplier_name=supplier_name,
                customer_name="",
                task_id=None,
                workshop_process_id=process.id,
                notes=notes or "Documento associado diretamente no processo de Oficina.",
                user_id=user_id,
                folder_path_override=folder_path,
            )
        except ValueError:
            return RedirectResponse(f"/workshop/{process_id}?error=Indica%20título%20e%20link.", status_code=303)
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?document_created=1", status_code=303)


@web_router.post("/workshop/{process_id}/document-zone", response_class=HTMLResponse)
def workshop_update_document_zone(
    request: Request,
    process_id: int,
    document_folder_path: str = Form(""),
    document_folder_url: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        vehicle = db.get(Vehicle, process.vehicle_id)
        clean_path = document_folder_path.strip() or suggest_workshop_process_folder_path(process, vehicle)
        clean_url = document_folder_url.strip() or None
        old_path = process.document_folder_path
        old_url = process.document_folder_url
        process.document_folder_path = clean_path
        process.document_folder_url = clean_url
        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=f"Zona documental atualizada.\nPasta sugerida: {clean_path}\nLink: {clean_url or '-'}",
            )
        )
        record_audit(
            db,
            action="workshop.document_zone.updated",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Zona documental atualizada no processo #{process.id}",
            before_json={"document_folder_path": old_path, "document_folder_url": old_url},
            after_json={"document_folder_path": clean_path, "document_folder_url": clean_url},
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/workshop/{process_id}?document_zone_saved=1", status_code=303)


@web_router.post("/workshop/{process_id}/flow")
def workshop_update_flow(
    request: Request,
    process_id: int,
    status: str = Form(""),
    decision: str = Form(""),
    decision_note: str = Form(""),
    history_result: str = Form(""),
    history_repair_orders_with_invoice: str = Form(""),
    history_repair_orders_with_invoice_detail: str = Form(""),
    history_invoice_without_work_order: str = Form(""),
    history_invoice_without_work_order_detail: str = Form(""),
    history_services_match_invoice: str = Form(""),
    history_services_match_invoice_detail: str = Form(""),
    servicebox_plan_obtained: str = Form(""),
    servicebox_plan_detail: str = Form(""),
    servicebox_simulation_done: str = Form(""),
    servicebox_simulation_detail: str = Form(""),
    servicebox_campaigns_checked: str = Form(""),
    servicebox_campaigns_detail: str = Form(""),
    servicebox_documents_attached: str = Form(""),
    servicebox_documents_detail: str = Form(""),
    check_brakes: str = Form(""),
    check_tyres: str = Form(""),
    check_lights: str = Form(""),
    check_wipers: str = Form(""),
    check_levels: str = Form(""),
    check_leaks: str = Form(""),
    check_noises: str = Form(""),
    check_battery: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if not process:
            return RedirectResponse("/workshop", status_code=303)
        allowed_statuses = {code for code, _ in WORKSHOP_STATUSES} | {process.status}
        allowed_decisions = {code for code, _ in WORKSHOP_DECISIONS}
        if status not in allowed_statuses:
            status = process.status
        if decision not in allowed_decisions:
            decision = process.decision or ""

        old_status = process.status
        old_decision = process.decision
        clean_decision_note = decision_note.strip()
        if status == "history_check":
            result_labels = {
                "consulted": "Histórico consultado",
                "no_history": "Sem histórico disponível",
            }
            answer_labels = {
                "yes": "Sim",
                "no": "Não",
                "na": "Não aplicável",
            }
            if (
                history_result not in result_labels
                or history_repair_orders_with_invoice not in answer_labels
                or history_invoice_without_work_order not in answer_labels
                or history_services_match_invoice not in answer_labels
            ):
                return RedirectResponse(
                    f"/workshop/{process_id}?error=Preenche%20todos%20os%20campos%20obrigatorios%20da%20verificacao%20de%20historico.",
                    status_code=303,
                )
            history_lines = []
            if history_result in result_labels:
                history_lines.append(f"Resultado da consulta: {result_labels[history_result]}.")
            history_checks = [
                (
                    "Folhas de obra de reparação com fatura",
                    history_repair_orders_with_invoice,
                    history_repair_orders_with_invoice_detail,
                ),
                (
                    "Fatura sem folha de obra",
                    history_invoice_without_work_order,
                    history_invoice_without_work_order_detail,
                ),
                (
                    "Serviços da folha de obra e serviço faturado correspondem",
                    history_services_match_invoice,
                    history_services_match_invoice_detail,
                ),
            ]
            for label, answer, detail in history_checks:
                if answer in answer_labels:
                    line = f"{label}: {answer_labels[answer]}"
                    clean_detail = detail.strip()
                    if clean_detail:
                        line = f"{line} - {clean_detail}"
                    history_lines.append(line)
            if clean_decision_note:
                history_lines.append(f"Observação: {clean_decision_note}")
            clean_decision_note = "\n".join(history_lines)
        elif status == "stellantis_service_box":
            answer_labels = {
                "yes": "Sim",
                "no": "Não",
                "na": "Não aplicável",
            }
            if (
                servicebox_plan_obtained not in answer_labels
                or servicebox_simulation_done not in answer_labels
                or servicebox_campaigns_checked not in answer_labels
                or servicebox_documents_attached not in answer_labels
            ):
                return RedirectResponse(
                    f"/workshop/{process_id}?error=Preenche%20todos%20os%20campos%20obrigatorios%20da%20verificacao%20Service%20Box.",
                    status_code=303,
                )
            servicebox_lines = []
            servicebox_checks = [
                (
                    "Plano de manutenção obtido no Service Box",
                    servicebox_plan_obtained,
                    servicebox_plan_detail,
                ),
                (
                    "Simulação por KM e idade efetuada",
                    servicebox_simulation_done,
                    servicebox_simulation_detail,
                ),
                (
                    "Campanhas técnicas verificadas",
                    servicebox_campaigns_checked,
                    servicebox_campaigns_detail,
                ),
                (
                    "Documentos de suporte anexados ao processo",
                    servicebox_documents_attached,
                    servicebox_documents_detail,
                ),
            ]
            for label, answer, detail in servicebox_checks:
                if answer in answer_labels:
                    line = f"{label}: {answer_labels[answer]}"
                    clean_detail = detail.strip()
                    if clean_detail:
                        line = f"{line} - {clean_detail}"
                    servicebox_lines.append(line)
            if clean_decision_note:
                servicebox_lines.append(f"Observação: {clean_decision_note}")
            clean_decision_note = "\n".join(servicebox_lines)
        elif status == "systematic_checks":
            check_labels = {
                "yes": "Sim",
                "no": "Não",
                "na": "Não aplicável",
            }
            required_checks = (
                check_brakes,
                check_tyres,
                check_lights,
                check_wipers,
                check_levels,
                check_leaks,
                check_noises,
                check_battery,
            )
            if any(answer not in check_labels for answer in required_checks):
                return RedirectResponse(
                    f"/workshop/{process_id}?error=Preenche%20todos%20os%20campos%20obrigatorios%20das%20verificacoes%20sistematicas.",
                    status_code=303,
                )
            check_lines = []
            safety_checks = [
                ("Travões verificados sem anomalia", check_brakes),
                ("Pneus verificados sem anomalia", check_tyres),
                ("Luzes exteriores verificadas sem anomalia", check_lights),
                ("Escovas / limpa-vidros verificados sem anomalia", check_wipers),
            ]
            mechanic_checks = [
                ("Níveis verificados sem anomalia", check_levels),
                ("Sem fugas visíveis", check_leaks),
                ("Sem ruídos anormais", check_noises),
                ("Bateria / arranque verificados sem anomalia", check_battery),
            ]
            if any(answer in check_labels for _, answer in safety_checks):
                check_lines.append("Segurança")
            for label, answer in safety_checks:
                if answer in check_labels:
                    check_lines.append(f"- {label}: {check_labels[answer]}")
            if any(answer in check_labels for _, answer in mechanic_checks):
                check_lines.append("Mecânica rápida")
            for label, answer in mechanic_checks:
                if answer in check_labels:
                    check_lines.append(f"- {label}: {check_labels[answer]}")
            if clean_decision_note:
                check_lines.append(f"Observações: {clean_decision_note}")
            clean_decision_note = "\n".join(check_lines)
        if (status != old_status or (decision or None) != old_decision) and not clean_decision_note:
            return RedirectResponse(
                f"/workshop/{process_id}?error=Descreve%20o%20passo%20executado%20antes%20de%20alterar%20o%20fluxo.",
                status_code=303,
            )
        process.status = status
        process.decision = decision or None
        process.decision_note = clean_decision_note or None
        if decision and decision != old_decision:
            process.decided_by_id = user_id
            process.decided_at = datetime.now(UTC)
        if status == "closed":
            process.closed_at = process.closed_at or datetime.now(UTC)
        else:
            process.closed_at = None

        db.add(
            WorkshopProcessNote(
                process_id=process.id,
                user_id=user_id,
                note=(
                    f"Fase registada: {status}\n"
                    "Fluxo atualizado: "
                    f"{WORKSHOP_STATUS_LABELS.get(old_status, old_status)} -> "
                    f"{WORKSHOP_STATUS_LABELS.get(status, status)}"
                    f"{chr(10) + clean_decision_note if clean_decision_note else ''}"
                ),
            )
        )
        record_audit(
            db,
            action="workshop.process.flow.updated",
            entity_type="workshop_process",
            entity_id=process.id,
            detail=f"Fluxo de oficina atualizado: {process.title}",
            before_json={"status": old_status, "decision": old_decision},
            after_json={"status": process.status, "decision": process.decision},
            user_id=user_id,
        )
        db.commit()

    if status == "closed":
        return RedirectResponse("/workshop/manage?closed=1", status_code=303)
    return RedirectResponse(f"/workshop/{process_id}?noted=1", status_code=303)


@web_router.post("/workshop/{process_id}/close")
def workshop_close(request: Request, process_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        process = db.get(WorkshopProcess, process_id)
        if process and not process.closed_at:
            process.status = "closed"
            process.closed_at = datetime.now(UTC)
            record_audit(
                db,
                action="workshop.process.closed",
                entity_type="workshop_process",
                entity_id=process.id,
                detail=f"Processo de oficina fechado: {process.title}",
                user_id=user_id,
            )
            db.commit()

    return RedirectResponse("/workshop/manage?closed=1", status_code=303)


@web_router.get("/imports/fleet", response_class=HTMLResponse)
def fleet_import_form(request: Request):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "fleet_import.html", {"error": None})


@web_router.post("/imports/fleet", response_class=HTMLResponse)
def fleet_import_submit(request: Request, file: UploadFile):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not file.filename.lower().endswith(".xlsx"):
        return templates.TemplateResponse(
            request,
            "fleet_import.html",
            {"error": "Carrega um ficheiro XLSX."},
            status_code=400,
        )

    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        with SessionLocal() as db:
            stats = import_rentway_fleet_xlsx(db, tmp_path, original_name=file.filename)
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(
        f"/fleet?imported={stats['created_rows']}+criadas,+{stats['updated_rows']}+atualizadas",
        status_code=303,
    )


@web_router.get("/imports/technical-history", response_class=HTMLResponse)
def technical_history_import_form(request: Request):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "technical_history_import.html",
        {
            "error": None,
            "columns": TECHNICAL_HISTORY_IMPORT_COLUMNS,
        },
    )


@web_router.get("/imports/technical-history/template.csv")
def technical_history_import_template(request: Request):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return Response(
        technical_history_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="carfast_historico_tecnico_template.csv"'},
    )


@web_router.post("/imports/technical-history", response_class=HTMLResponse)
def technical_history_import_submit(request: Request, file: UploadFile):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if not file.filename.lower().endswith((".xlsx", ".csv")):
        return templates.TemplateResponse(
            request,
            "technical_history_import.html",
            {
                "error": "Carrega um ficheiro XLSX ou CSV.",
                "columns": TECHNICAL_HISTORY_IMPORT_COLUMNS,
            },
            status_code=400,
        )

    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        with SessionLocal() as db:
            stats = import_workshop_technical_history_file(
                db,
                tmp_path,
                original_name=file.filename,
                imported_by_id=user_id,
            )
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(f"/imports/{stats['batch_id']}", status_code=303)


TASK_BULK_SESSION_KEY = "task_bulk_import_pending"
TRADE_DEBT_SESSION_KEY = "trade_debt_import_pending"


def trade_debt_form_context(
    request: Request,
    *,
    error: str | None = None,
    preview: dict | None = None,
    result: dict | None = None,
) -> dict:
    pending = request.session.get(TRADE_DEBT_SESSION_KEY) if hasattr(request, "session") else None
    return {
        "error": error,
        "preview": preview,
        "result": result,
        "pending": pending,
    }


@web_router.get("/imports/trade-debt", response_class=HTMLResponse)
def trade_debt_import_form(request: Request, reset: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = require_any_web_permission(request, "imports.run", "admin.manage")
    if denied:
        return denied
    if reset and hasattr(request, "session"):
        request.session.pop(TRADE_DEBT_SESSION_KEY, None)
    return templates.TemplateResponse(request, "trade_debt_import.html", trade_debt_form_context(request))


@web_router.post("/imports/trade-debt/preview", response_class=HTMLResponse)
def trade_debt_import_preview(request: Request, file: UploadFile):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = require_any_web_permission(request, "imports.run", "admin.manage")
    if denied:
        return denied
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        return templates.TemplateResponse(
            request,
            "trade_debt_import.html",
            trade_debt_form_context(request, error="Carrega um ficheiro XLSX."),
            status_code=400,
        )

    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        stored_path = store_trade_debt_upload(tmp_path, file.filename)
    finally:
        tmp_path.unlink(missing_ok=True)

    with SessionLocal() as db:
        try:
            preview = preview_trade_debt_import(db, stored_path)
        except ValueError as exc:
            stored_path.unlink(missing_ok=True)
            return templates.TemplateResponse(
                request,
                "trade_debt_import.html",
                trade_debt_form_context(request, error=str(exc)),
                status_code=400,
            )
    request.session[TRADE_DEBT_SESSION_KEY] = {
        "path": str(stored_path),
        "original_name": file.filename,
    }
    return templates.TemplateResponse(
        request,
        "trade_debt_import.html",
        trade_debt_form_context(request, preview=preview),
    )


@web_router.post("/imports/trade-debt/confirm", response_class=HTMLResponse)
def trade_debt_import_confirm(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = require_any_web_permission(request, "imports.run", "admin.manage")
    if denied:
        return denied
    pending = request.session.get(TRADE_DEBT_SESSION_KEY) if hasattr(request, "session") else None
    if not pending:
        return RedirectResponse("/imports/trade-debt", status_code=303)
    path = Path(pending["path"])
    if not path.exists():
        return templates.TemplateResponse(
            request,
            "trade_debt_import.html",
            trade_debt_form_context(request, error="O ficheiro pendente já não está disponível."),
            status_code=400,
        )
    with SessionLocal() as db:
        result = apply_trade_debt_import(
            db,
            path,
            pending["original_name"],
            user_id=user_id,
        )
    request.session.pop(TRADE_DEBT_SESSION_KEY, None)
    return templates.TemplateResponse(
        request,
        "trade_debt_import.html",
        trade_debt_form_context(request, result=result),
    )


def task_bulk_form_context(
    db,
    request: Request,
    *,
    error: str | None = None,
    preview: dict | None = None,
    result: dict | None = None,
    form_values: dict | None = None,
) -> dict:
    user_id = get_web_user_id(request)
    current_user = db.get(User, user_id) if user_id else None
    users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
    assignable_users = assignable_users_for_workspace(users, "operational")
    teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
    parent_task_types = user_accessible_task_type_codes(db, current_user)
    parent_tasks = []
    if parent_task_types:
        parent_tasks = db.scalars(
            select(Task)
            .where(
                Task.parent_task_id.is_(None),
                Task.closed_at.is_(None),
                Task.task_type.in_(tuple(parent_task_types)),
            )
            .order_by(Task.id.desc())
            .limit(120)
        ).all()
    default_values = {
        "mode": "create",
        "parent_title": "",
        "parent_task_id": "",
        "default_category": "operations",
        "default_priority": "normal",
        "assigned_to_id": "",
        "delegated_to": "",
        "due_on": "",
    }
    default_values.update(form_values or {})
    pending = request.session.get(TASK_BULK_SESSION_KEY) if hasattr(request, "session") else None
    return {
        "error": error,
        "preview": preview,
        "result": result,
        "pending": pending,
        "form_values": default_values,
        "task_bulk_fields": TASK_BULK_FIELDS,
        "parent_tasks": parent_tasks,
        "users": users,
        "assignable_users": assignable_users,
        "teams": teams,
        "task_categories": TASK_CATEGORIES,
        "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
        "priorities": PRIORITIES,
        "priority_labels": PRIORITY_DISPLAY_LABELS,
    }


def task_bulk_defaults_from_form(
    db,
    *,
    default_category: str,
    default_priority: str,
    assigned_to_id: str,
    delegated_to: str,
    due_on: str,
) -> dict:
    category = default_category if default_category in TASK_CATEGORY_LABELS else "operations"
    priority = default_priority if default_priority in PRIORITY_DISPLAY_LABELS else "normal"
    assigned_user_id = parse_optional_int(assigned_to_id)
    if assigned_user_id and not db.get(User, assigned_user_id):
        assigned_user_id = None
    delegated_user_id, delegated_team_id = parse_delegation_target(delegated_to)
    if delegated_user_id and not db.get(User, delegated_user_id):
        delegated_user_id = None
    if delegated_team_id and not db.get(Team, delegated_team_id):
        delegated_team_id = None
    assigned_user = db.get(User, assigned_user_id) if assigned_user_id else None
    task_type = "workshop_task" if category == "workshop" else "operational_task"
    return {
        "category": category,
        "subcategory": default_task_subcategory(category),
        "priority": priority,
        "assigned_to_id": assigned_user_id,
        "delegated_to_user_id": delegated_user_id,
        "delegated_to_team_id": delegated_team_id,
        "due_on": parse_optional_date(due_on),
        "responsible_label": assigned_user.name if assigned_user else "",
        "task_type": task_type,
    }


def task_bulk_workspace_for_defaults(defaults: dict, parent_task: Task | None) -> str:
    if parent_task:
        return workspace_for_task_type(parent_task.task_type)
    return "workshop" if defaults.get("task_type") == "workshop_task" else "operational"


@web_router.get("/imports/tasks", response_class=HTMLResponse)
def task_bulk_import_form(request: Request, reset: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = require_any_web_permission(request, "imports.run", "admin.manage")
    if denied:
        return denied
    if reset and hasattr(request, "session"):
        request.session.pop(TASK_BULK_SESSION_KEY, None)
    with SessionLocal() as db:
        return templates.TemplateResponse(request, "task_bulk_import.html", task_bulk_form_context(db, request))


@web_router.post("/imports/tasks/preview", response_class=HTMLResponse)
def task_bulk_import_preview(
    request: Request,
    file: UploadFile,
    mode: str = Form("create"),
    parent_title: str = Form(""),
    parent_task_id: str = Form(""),
    default_category: str = Form("operations"),
    default_priority: str = Form("normal"),
    assigned_to_id: str = Form(""),
    delegated_to: str = Form(""),
    due_on: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = require_any_web_permission(request, "imports.run", "admin.manage")
    if denied:
        return denied
    form_values = {
        "mode": mode,
        "parent_title": parent_title,
        "parent_task_id": parent_task_id,
        "default_category": default_category,
        "default_priority": default_priority,
        "assigned_to_id": assigned_to_id,
        "delegated_to": delegated_to,
        "due_on": due_on,
    }
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".csv")):
        with SessionLocal() as db:
            return templates.TemplateResponse(
                request,
                "task_bulk_import.html",
                task_bulk_form_context(db, request, error="Carrega um ficheiro XLSX ou CSV.", form_values=form_values),
                status_code=400,
            )

    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)

    try:
        stored_path = store_task_bulk_upload(tmp_path, file.filename)
    finally:
        tmp_path.unlink(missing_ok=True)

    with SessionLocal() as db:
        defaults = task_bulk_defaults_from_form(
            db,
            default_category=default_category,
            default_priority=default_priority,
            assigned_to_id=assigned_to_id,
            delegated_to=delegated_to,
            due_on=due_on,
        )
        parent_task = db.get(Task, parse_optional_int(parent_task_id)) if mode == "append" else None
        if mode == "create" and not parent_title.strip():
            return templates.TemplateResponse(
                request,
                "task_bulk_import.html",
                task_bulk_form_context(
                    db,
                    request,
                    error="Indica o título da tarefa mãe.",
                    form_values=form_values,
                ),
                status_code=400,
            )
        if mode == "append" and not parent_task:
            return templates.TemplateResponse(
                request,
                "task_bulk_import.html",
                task_bulk_form_context(
                    db,
                    request,
                    error="Seleciona uma tarefa mãe existente.",
                    form_values=form_values,
                ),
                status_code=400,
            )
        current_user = db.get(User, user_id)
        workspace = task_bulk_workspace_for_defaults(defaults, parent_task)
        if not user_can_access_task_workspace(db, current_user, workspace, write=True):
            return templates.TemplateResponse(
                request,
                "task_bulk_import.html",
                task_bulk_form_context(
                    db,
                    request,
                    error="Sem permissão para criar tarefas nesta área.",
                    form_values=form_values,
                ),
                status_code=403,
            )
        preview = preview_task_bulk_import(
            db,
            stored_path,
            defaults,
            parent_task_id=parent_task.id if parent_task else None,
            valid_categories=set(TASK_CATEGORY_LABELS),
        )
        request.session[TASK_BULK_SESSION_KEY] = {
            "path": str(stored_path),
            "original_name": file.filename,
            "mode": "append" if mode == "append" else "create",
            "parent_title": parent_title.strip(),
            "parent_task_id": str(parent_task.id) if parent_task else "",
            "default_category": default_category,
            "default_priority": default_priority,
            "assigned_to_id": assigned_to_id,
            "delegated_to": delegated_to,
            "due_on": due_on,
        }
        return templates.TemplateResponse(
            request,
            "task_bulk_import.html",
            task_bulk_form_context(db, request, preview=preview, form_values=form_values),
        )


@web_router.post("/imports/tasks/confirm", response_class=HTMLResponse)
def task_bulk_import_confirm(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = require_any_web_permission(request, "imports.run", "admin.manage")
    if denied:
        return denied
    pending = request.session.get(TASK_BULK_SESSION_KEY) if hasattr(request, "session") else None
    if not pending:
        return RedirectResponse("/imports/tasks", status_code=303)
    path = Path(pending["path"])
    if not path.exists():
        with SessionLocal() as db:
            return templates.TemplateResponse(
                request,
                "task_bulk_import.html",
                task_bulk_form_context(db, request, error="O ficheiro pendente já não está disponível."),
                status_code=400,
            )
    with SessionLocal() as db:
        defaults = task_bulk_defaults_from_form(
            db,
            default_category=pending["default_category"],
            default_priority=pending["default_priority"],
            assigned_to_id=pending["assigned_to_id"],
            delegated_to=pending["delegated_to"],
            due_on=pending["due_on"],
        )
        parent_task = db.get(Task, parse_optional_int(pending.get("parent_task_id"))) if pending["mode"] == "append" else None
        current_user = db.get(User, user_id)
        workspace = task_bulk_workspace_for_defaults(defaults, parent_task)
        if not user_can_access_task_workspace(db, current_user, workspace, write=True):
            return templates.TemplateResponse(
                request,
                "task_bulk_import.html",
                task_bulk_form_context(db, request, error="Sem permissão para criar tarefas nesta área."),
                status_code=403,
            )
        result = create_tasks_from_bulk_import(
            db,
            path,
            pending["original_name"],
            defaults,
            mode=pending["mode"],
            parent_task_id=parent_task.id if parent_task else None,
            parent_title=pending["parent_title"],
            valid_categories=set(TASK_CATEGORY_LABELS),
            user_id=user_id,
        )
        request.session.pop(TASK_BULK_SESSION_KEY, None)
        return templates.TemplateResponse(
            request,
            "task_bulk_import.html",
            task_bulk_form_context(db, request, result=result),
        )


def management_center_denied(request: Request, write: bool = False) -> RedirectResponse | None:
    permissions = ("management_center.write", "admin.manage") if write else ("management_center.read", "management_center.write", "admin.manage")
    return require_any_web_permission(request, *permissions)


MANAGEMENT_PENDING_LABELS = {
    "missing_ar": "AR em falta",
    "missing_minimum_data": "Dados mínimos em falta",
}

LIABILITY_LABELS = {
    "awaiting_responsibility": "Aguarda Responsabilidade",
    "culpado": "Culpado",
    "sem_culpa": "Sem Culpa",
    "50_50": "50 / 50",
    "na": "N/A",
}


def normalize_liability_value(raw_value: str | None) -> str | None:
    if raw_value is None:
        return None
    text = raw_value.strip()
    if not text:
        return None
    for code, label in LIABILITY_LABELS.items():
        if text == code:
            return code
        if text.lower() == label.lower():
            return code
    return None


def management_process_liability(process: ManagementProcess) -> str | None:
    raw = process.raw_summary_json
    if isinstance(raw, dict):
        return normalize_liability_value(raw.get("liability")) or "awaiting_responsibility"
    return "awaiting_responsibility"

MANAGEMENT_SEVERITY_LABELS = {
    "critical": "Crítica",
    "warning": "Atenção",
    "info": "Informativa",
}

MANAGEMENT_IMPORT_TYPE_LABELS = {
    AR_IMPORT_TYPE: "AR Rentway",
    CRAR_PER_VEHICLE_IMPORT_TYPE: "AR Rentway por viatura",
    REFSTRO_IMPORT_TYPE: "REFSTRO / Sinistros",
}

IMPORT_STATUS_DISPLAY_LABELS = {
    "pending": "Pendente",
    "running": "Em execução",
    "completed": "Concluída",
    "completed_with_errors": "Concluída com erros",
    "failed": "Falhada",
}


def management_process_query_filters(
    *,
    process_type_id: int,
    status: str | None,
    plate: str | None,
    document: str | None,
    customer: str | None,
    driver: str | None,
    pending: str | None,
):
    conditions = [ManagementProcess.process_type_id == process_type_id]
    if status:
        conditions.append(ManagementProcess.status == status)
    if plate:
        conditions.append(ManagementProcess.plate.ilike(f"%{plate.strip()}%"))
    if document:
        conditions.append(ManagementProcess.document_reference.ilike(f"%{document.strip()}%"))
    if customer:
        conditions.append(ManagementProcess.customer_name.ilike(f"%{customer.strip()}%"))
    if driver:
        conditions.append(ManagementProcess.driver_name.ilike(f"%{driver.strip()}%"))
    if pending:
        conditions.append(ManagementProcess.pending_reason == pending)
    return conditions


def process_association_counts(db, process_ids: list[int]) -> dict[int, dict[str, int]]:
    counts = {process_id: {"ar": 0, "refstro": 0, "actions": 0} for process_id in process_ids}
    if not process_ids:
        return counts
    association_rows = db.execute(
        select(
            ManagementProcessAssociation.process_id,
            ManagementProcessAssociation.entity_type,
            func.count(ManagementProcessAssociation.id),
        )
        .where(
            ManagementProcessAssociation.process_id.in_(process_ids),
            ManagementProcessAssociation.active.is_(True),
        )
        .group_by(ManagementProcessAssociation.process_id, ManagementProcessAssociation.entity_type)
    ).all()
    for process_id, entity_type, total in association_rows:
        if entity_type == "claim_rentway_ar":
            counts[process_id]["ar"] = total
        elif entity_type == "claim_refstro_line":
            counts[process_id]["refstro"] = total
    action_rows = db.execute(
        select(ManagementAction.process_id, func.count(ManagementAction.id))
        .where(ManagementAction.process_id.in_(process_ids), ManagementAction.status == "open")
        .group_by(ManagementAction.process_id)
    ).all()
    for process_id, total in action_rows:
        counts[process_id]["actions"] = total
    return counts


def management_business_metrics(db, process_type_id: int) -> dict[str, int | float]:
    official_ar_associations = db.execute(
        select(ClaimRentwayAR.id, ManagementProcessAssociation.process_id)
        .join(
            ManagementProcessAssociation,
            ManagementProcessAssociation.entity_id == ClaimRentwayAR.id,
        )
        .join(ManagementProcess, ManagementProcess.id == ManagementProcessAssociation.process_id)
        .where(
            ManagementProcess.process_type_id == process_type_id,
            ManagementProcessAssociation.entity_type == "claim_rentway_ar",
            ManagementProcessAssociation.active.is_(True),
            ClaimRentwayAR.source_file.is_not(None),
            ~ClaimRentwayAR.source_file.ilike("%crar_pervehicle%"),
            ~ClaimRentwayAR.source_file.ilike("%demo%"),
        )
    ).all()
    official_ar_ids = {ar_id for ar_id, _ in official_ar_associations}
    official_ar_process_ids = {process_id for _, process_id in official_ar_associations}

    refstro_rows = db.execute(
        select(ClaimRefstroLine.refstro_reference, ManagementProcessAssociation.process_id)
        .join(
            ManagementProcessAssociation,
            ManagementProcessAssociation.entity_id == ClaimRefstroLine.id,
        )
        .join(ManagementProcess, ManagementProcess.id == ManagementProcessAssociation.process_id)
        .where(
            ManagementProcess.process_type_id == process_type_id,
            ManagementProcessAssociation.entity_type == "claim_refstro_line",
            ManagementProcessAssociation.active.is_(True),
            ClaimRefstroLine.refstro_reference.is_not(None),
        )
    ).all()
    participation_refs = {ref for ref, _ in refstro_rows if ref}
    associated_participation_refs = {
        ref for ref, process_id in refstro_rows if ref and process_id in official_ar_process_ids
    }
    reconciliation_refs = participation_refs - associated_participation_refs
    open_actions = (
        db.scalar(
            select(func.count())
            .select_from(ManagementAction)
            .join(ManagementProcess, ManagementProcess.id == ManagementAction.process_id)
            .where(ManagementProcess.process_type_id == process_type_id, ManagementAction.status == "open")
        )
        or 0
    )
    mandatory_actions = (
        db.scalar(
            select(func.count())
            .select_from(ManagementAction)
            .join(ManagementProcess, ManagementProcess.id == ManagementAction.process_id)
            .where(
                ManagementProcess.process_type_id == process_type_id,
                ManagementAction.status == "open",
                ManagementAction.mandatory.is_(True),
            )
        )
        or 0
    )
    overdue = (
        db.scalar(
            select(func.count())
            .select_from(ManagementProcess)
            .where(
                ManagementProcess.process_type_id == process_type_id,
                ManagementProcess.closed_at.is_(None),
                ManagementProcess.sla_due_on.is_not(None),
                ManagementProcess.sla_due_on < date.today(),
            )
        )
        or 0
    )
    monitored = max(len(official_ar_ids) - len(associated_participation_refs) - mandatory_actions, 0)
    return {
        "official_ar": len(official_ar_ids),
        "participations": len(participation_refs),
        "participations_with_ar": len(associated_participation_refs),
        "participations_to_reconcile": len(reconciliation_refs),
        "mandatory_actions": mandatory_actions,
        "open_actions": open_actions,
        "overdue": overdue,
        "monitoring": monitored,
        "technical_processes": db.scalar(
            select(func.count()).select_from(ManagementProcess).where(ManagementProcess.process_type_id == process_type_id)
        )
        or 0,
        "value": db.scalar(
            select(func.coalesce(func.sum(ManagementProcess.total_claim_value), 0)).where(
                ManagementProcess.process_type_id == process_type_id
            )
        )
        or 0,
    }


def management_known_ar_records(db) -> dict[str, dict[str, object]]:
    rows = db.scalars(
        select(ClaimRentwayAR).where(
            ClaimRentwayAR.ar_reference.is_not(None),
            ClaimRentwayAR.source_file.is_not(None),
            ~ClaimRentwayAR.source_file.ilike("%crar_pervehicle%"),
            ~ClaimRentwayAR.source_file.ilike("%demo%"),
        )
    ).all()
    records = {}
    for ar in rows:
        if not ar.ar_reference:
            continue
        records[str(ar.ar_reference)] = {
            "id": ar.id,
            "ar_reference": ar.ar_reference,
            "plate": ar.plate,
            "vehicle_reference": ar.vehicle_reference,
            "request_date": ar.request_date,
            "ra_reference": ar.ra_reference,
            "impro_reference": ar.impro_reference,
            "driver_name": ar.driver_name,
            "customer_name": ar.customer_name,
        }
    return records


def parse_management_raw_date(value) -> date | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")[:19]).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def ar_reconciliation_date(ar: ClaimRentwayAR) -> date | None:
    raw = ar.raw_json if isinstance(ar.raw_json, dict) else {}
    accident_date = parse_management_raw_date(raw.get("accidentDate"))
    if accident_date:
        return accident_date
    sources = raw.get("_sources", [])
    for source in sources if isinstance(sources, list) else []:
        source_raw = source.get("raw") if isinstance(source, dict) else {}
        accident_date = parse_management_raw_date(source_raw.get("accident_date") or source_raw.get("Data do acidente"))
        if accident_date:
            return accident_date
    return ar.request_date


def money_value(value) -> float:
    return float(value or 0)


def reconciliation_association_maps(db):
    associations = db.scalars(
        select(ManagementProcessAssociation).where(ManagementProcessAssociation.active.is_(True))
    ).all()
    ar_process_by_id: dict[int, int] = {}
    ref_process_by_id: dict[int, int] = {}
    ar_ids_by_process: dict[int, set[int]] = defaultdict(set)
    ref_ids_by_process: dict[int, set[int]] = defaultdict(set)
    for association in associations:
        if association.entity_type == "claim_rentway_ar":
            ar_process_by_id[association.entity_id] = association.process_id
            ar_ids_by_process[association.process_id].add(association.entity_id)
        elif association.entity_type == "claim_refstro_line":
            ref_process_by_id[association.entity_id] = association.process_id
            ref_ids_by_process[association.process_id].add(association.entity_id)
    return ar_process_by_id, ref_process_by_id, ar_ids_by_process, ref_ids_by_process


def build_reconciliation_ref_groups(ref_lines: list[ClaimRefstroLine], ref_process_by_id: dict[int, int]) -> list[dict]:
    grouped: dict[tuple, dict] = {}
    for line in ref_lines:
        if line.plate and line.accident_date:
            key = ("incident", line.plate, line.accident_date)
        else:
            key = ("reference", line.refstro_reference or f"linha-{line.id}", line.plate or "-", line.accident_date)
        item = grouped.setdefault(
            key,
            {
                "refstro_reference": "-",
                "refstro_references": set(),
                "plate": line.plate,
                "accident_date": line.accident_date,
                "document_reference": "-",
                "document_references": set(),
                "components": set(),
                "component_totals": {},
                "value": 0.0,
                "line_ids": [],
                "process_ids": set(),
                "statuses": set(),
            },
        )
        if line.refstro_reference:
            item["refstro_references"].add(line.refstro_reference)
        if line.document_reference:
            item["document_references"].add(line.document_reference)
        if line.component:
            item["components"].add(line.component)
        component_key = line.component or "Sem componente"
        try:
            item["component_totals"][component_key] = item["component_totals"].get(component_key, 0.0) + money_value(line.claim_value)
        except AttributeError:
            pass
        if line.status:
            item["statuses"].add(line.status)
        item["value"] += money_value(line.claim_value)
        item["line_ids"].append(line.id)
        process_id = ref_process_by_id.get(line.id)
        if process_id:
            item["process_ids"].add(process_id)
    result = []
    for item in grouped.values():
        item["components"] = sorted(item["components"]) or ["Sem componente"]
        item["process_ids"] = sorted(item["process_ids"])
        refstro_references = sorted(item.pop("refstro_references"))
        document_references = sorted(item.pop("document_references"))
        statuses = sorted(item.pop("statuses"))
        item["refstro_reference"] = ", ".join(refstro_references) if refstro_references else "-"
        item["document_reference"] = ", ".join(document_references) if document_references else "-"
        item["status"] = ", ".join(statuses) if statuses else None
        item["line_count"] = len(item["line_ids"])
        item["refstro_count"] = len(refstro_references)
        component_totals = item.pop("component_totals", {})
        item["component_breakdown"] = [
            {"component": component, "value": value}
            for component, value in sorted(component_totals.items(), key=lambda current: (-current[1], current[0]))
        ]
        item["component_count"] = len(item["component_breakdown"])
        result.append(item)
    return result


def parse_ref_line_ids(raw_value: str | None) -> list[int]:
    if not raw_value:
        return []
    ids: list[int] = []
    for value in raw_value.split(','):
        value = value.strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except ValueError:
            continue
    return ids


def build_reconciliation_rows(
    db,
    *,
    plate_filter: str | None = None,
    selected_plate: str | None = None,
    selected_ref_line_ids: list[int] | None = None,
    mode: str = "pending",
    window_days: int = 30,
    limit: int = 180,
) -> dict:
    selected_ref_set = set(selected_ref_line_ids or [])
    ar_process_by_id, ref_process_by_id, ar_ids_by_process, ref_ids_by_process = reconciliation_association_maps(db)
    ar_query = select(ClaimRentwayAR).where(
        ClaimRentwayAR.plate.is_not(None),
        ClaimRentwayAR.source_file.is_not(None),
        ~ClaimRentwayAR.source_file.ilike("%crar_pervehicle%"),
        ~ClaimRentwayAR.source_file.ilike("%demo%"),
    )
    ref_query = select(ClaimRefstroLine).where(ClaimRefstroLine.plate.is_not(None))
    clean_plate = normalize_plate_for_web(plate_filter)
    if clean_plate:
        ar_query = ar_query.where(ClaimRentwayAR.plate.ilike(f"%{clean_plate}%"))
        ref_query = ref_query.where(ClaimRefstroLine.plate.ilike(f"%{clean_plate}%"))
    ars = db.scalars(ar_query.order_by(ClaimRentwayAR.plate, ClaimRentwayAR.request_date, ClaimRentwayAR.id)).all()
    ref_lines = db.scalars(ref_query.order_by(ClaimRefstroLine.plate, ClaimRefstroLine.accident_date, ClaimRefstroLine.id)).all()
    refs = build_reconciliation_ref_groups(ref_lines, ref_process_by_id)
    if selected_ref_set:
        refs = [ref for ref in refs if any(line_id in selected_ref_set for line_id in ref["line_ids"])]

    process_ids = {process_id for process_id in ar_process_by_id.values()} | {pid for ref in refs for pid in ref["process_ids"]}
    processes = {
        process.id: process
        for process in (
            db.scalars(select(ManagementProcess).where(ManagementProcess.id.in_(process_ids))).all()
            if process_ids
            else []
        )
    }

    ars_by_plate: dict[str, list[dict]] = defaultdict(list)
    for ar in ars:
        ar_date = ar_reconciliation_date(ar)
        process_id = ar_process_by_id.get(ar.id)
        ars_by_plate[ar.plate or "-"].append(
            {
                "id": ar.id,
                "ar_reference": ar.ar_reference or "-",
                "date": ar_date,
                "status": ar.status or "-",
                "driver_name": ar.driver_name or "-",
                "customer_name": ar.customer_name or "-",
                "document_reference": ar.ra_reference or ar.impro_reference or "-",
                "process_id": process_id,
                "process_reference": processes.get(process_id).internal_reference if process_id in processes else "-",
                "has_refstro": bool(process_id and ref_ids_by_process.get(process_id)),
            }
        )
    for values in ars_by_plate.values():
        values.sort(key=lambda item: (item["date"] or date.max, item["id"]))

    rows = []
    stats = {"strong": 0, "probable": 0, "doubt": 0, "missing_ar": 0, "monitoring": 0, "associated": 0}
    for ref in refs:
        candidate_ars = ars_by_plate.get(ref["plate"] or "-", [])
        already_associated = any(ar["process_id"] in ref["process_ids"] for ar in candidate_ars if ar["process_id"])
        best_ar = None
        best_delta = None
        for ar in candidate_ars:
            if not ar["date"] or not ref["accident_date"]:
                continue
            delta = abs((ar["date"] - ref["accident_date"]).days)
            if delta <= window_days and (best_delta is None or delta < best_delta):
                best_ar = ar
                best_delta = delta
        if already_associated:
            suggestion = "Associado"
            confidence = "associated"
            reason = "REFSTRO já está no mesmo processo que um AR desta matrícula."
        elif best_ar and best_delta is not None and best_delta <= 1:
            suggestion = "Match forte"
            confidence = "strong"
            reason = "Mesma matrícula e data igual ou muito próxima."
        elif best_ar and best_delta is not None and best_delta <= 7:
            suggestion = "Provável"
            confidence = "probable"
            reason = f"Mesma matrícula com diferença de {best_delta} dias."
        elif best_ar:
            suggestion = "Dúvida"
            confidence = "doubt"
            reason = f"Mesma matrícula, mas diferença de {best_delta} dias."
        else:
            suggestion = "Sem AR"
            confidence = "missing_ar"
            reason = "Participação REFSTRO sem AR candidato dentro da janela."
        stats[confidence] += 1
        if mode == "pending" and confidence == "associated":
            continue
        if mode == "strong" and confidence != "strong":
            continue
        if mode == "doubt" and confidence not in {"doubt", "missing_ar"}:
            continue
        rows.append(
            {
                "plate": ref["plate"] or "-",
                "ar": best_ar or (candidate_ars[0] if candidate_ars else None),
                "ref": ref,
                "ar_candidates": candidate_ars,
                "ref_line_ids": ",".join(str(line_id) for line_id in ref["line_ids"]),
                "suggestion": suggestion,
                "confidence": confidence,
                "reason": reason,
                "delta_days": best_delta,
                "candidate_count": len(candidate_ars),
                "accident_date": ref["accident_date"],
            }
        )

    ref_process_ids = {pid for ref in refs for pid in ref["process_ids"]}
    for ar_list in ars_by_plate.values():
        for ar in ar_list:
            if ar["process_id"] in ref_process_ids:
                continue
            if mode not in {"all", "monitoring"}:
                continue
            stats["monitoring"] += 1
            rows.append(
                {
                    "plate": next((plate for plate, items in ars_by_plate.items() if ar in items), "-"),
                    "ar": ar,
                    "ref": None,
                    "ar_candidates": [ar],
                    "ref_line_ids": "",
                    "suggestion": "Monitorização",
                    "confidence": "monitoring",
                    "reason": "AR sem REFSTRO associado.",
                    "delta_days": None,
                    "candidate_count": 0,
                    "accident_date": None,
                }
            )

    rows.sort(
        key=lambda row: (
            row["plate"] or "",
            row["ref"]["accident_date"] if row["ref"] and row["ref"].get("accident_date") else date.max,
            row["ar"]["date"] if row["ar"] and row["ar"].get("date") else date.max,
        )
    )
    grouped_counts = defaultdict(int)
    for row in rows:
        grouped_counts[row["plate"]] += 1
    grouped_items = sorted(grouped_counts.items(), key=lambda item: (-item[1], item[0]))
    visible_rows = rows[:limit]
    selected_clean_plate = normalize_plate_for_web(selected_plate) or clean_plate
    if not selected_clean_plate and grouped_items:
        selected_clean_plate = normalize_plate_for_web(grouped_items[0][0])
    selected_plate_value = ""
    if selected_clean_plate:
        selected_plate_value = next(
            (plate for plate, _ in grouped_items if normalize_plate_for_web(plate) == selected_clean_plate),
            "",
        )
        if not selected_plate_value and grouped_items:
            selected_plate_value = grouped_items[0][0]
            selected_clean_plate = normalize_plate_for_web(selected_plate_value)
    plate_rows = (
        [row for row in rows if normalize_plate_for_web(row["plate"]) == selected_clean_plate][:12]
        if selected_clean_plate
        else []
    )
    plate_ar_candidates = (
        ars_by_plate.get(selected_plate_value, []) if selected_plate_value else []
    )
    if selected_clean_plate and not plate_ar_candidates:
        plate_ar_candidates = next(
            (items for plate, items in ars_by_plate.items() if normalize_plate_for_web(plate) == selected_clean_plate),
            [],
        )
    plate_ref_rows = [row for row in plate_rows if row.get("ref")]
    visible_grouped_items = grouped_items[:20]
    if selected_plate_value and all(plate != selected_plate_value for plate, _ in visible_grouped_items):
        selected_group = next((item for item in grouped_items if item[0] == selected_plate_value), None)
        if selected_group:
            visible_grouped_items = [selected_group, *visible_grouped_items[:19]]
    return {
        "rows": visible_rows,
        "plate_rows": plate_rows,
        "plate_ar_candidates": plate_ar_candidates,
        "plate_ref_rows": plate_ref_rows,
        "selected_plate": selected_plate_value,
        "grouped_counts": visible_grouped_items,
        "grouped_count_by_plate": dict(grouped_counts),
        "stats": stats,
        "total_rows": len(rows),
        "mode": mode,
        "window_days": window_days,
        "plate_filter": plate_filter or "",
    }


def normalize_plate_for_web(value: str | None) -> str:
    return (value or "").strip().upper().replace("-", "").replace(" ", "")


def _technical_audit_dashboard_context(
    db: Session,
    *,
    plate: str | None = None,
    status: str | None = None,
    limit: int = 120,
) -> dict[str, Any]:
    audit_filters = []
    if plate:
        audit_filters.append(VehicleHistoryAudit.plate.ilike(f"%{plate.strip()}%"))
    if status:
        audit_filters.append(VehicleHistoryAudit.status == status)
    audit_query = (
        select(VehicleHistoryAudit)
        .where(*audit_filters)
        .order_by(VehicleHistoryAudit.updated_at.desc(), VehicleHistoryAudit.id.desc())
    )
    technical_audits = db.scalars(audit_query.limit(limit)).all()
    audit_ids = [audit.id for audit in technical_audits]
    audit_documents = (
        db.scalars(select(VehicleHistoryAuditDocument).where(VehicleHistoryAuditDocument.audit_id.in_(audit_ids))).all()
        if audit_ids
        else []
    )
    audit_issues = (
        db.scalars(select(VehicleHistoryAuditIssue).where(VehicleHistoryAuditIssue.audit_id.in_(audit_ids))).all()
        if audit_ids
        else []
    )
    audit_documents_by_id: dict[int, list[VehicleHistoryAuditDocument]] = defaultdict(list)
    for document_item in audit_documents:
        audit_documents_by_id[document_item.audit_id].append(document_item)
    audit_issues_by_id: dict[int, list[VehicleHistoryAuditIssue]] = defaultdict(list)
    for issue_item in audit_issues:
        audit_issues_by_id[issue_item.audit_id].append(issue_item)
    audit_process_ids = [audit.management_process_id for audit in technical_audits if audit.management_process_id]
    audit_processes_by_id = {
        item.id: item
        for item in (
            db.scalars(select(ManagementProcess).where(ManagementProcess.id.in_(audit_process_ids))).all()
            if audit_process_ids
            else []
        )
    }
    audit_vehicle_ids = [audit.vehicle_id for audit in technical_audits]
    audit_vehicles_by_id = {
        item.id: item
        for item in (
            db.scalars(select(Vehicle).where(Vehicle.id.in_(audit_vehicle_ids))).all()
            if audit_vehicle_ids
            else []
        )
    }
    audit_user_ids = [audit.responsible_user_id for audit in technical_audits if audit.responsible_user_id]
    audit_users_by_id = {
        item.id: item
        for item in (
            db.scalars(select(User).where(User.id.in_(audit_user_ids))).all()
            if audit_user_ids
            else []
        )
    }
    unresolved_issue_states = {"new", "in_analysis", "to_discuss", "waiting_evidence", "por_analisar", "em_discussao", "aguardar_resposta"}
    technical_audit_rows = []
    for audit in technical_audits:
        issues_for_audit = audit_issues_by_id.get(audit.id, [])
        open_issues = [item for item in issues_for_audit if item.status in unresolved_issue_states]
        high_issues = [item for item in open_issues if item.severity in {"high", "critical", "alta", "critica"}]
        process = audit_processes_by_id.get(audit.management_process_id or 0)
        vehicle = audit_vehicles_by_id.get(audit.vehicle_id)
        responsible = audit_users_by_id.get(audit.responsible_user_id or 0)
        technical_audit_rows.append(
            {
                "audit": audit,
                "process": process,
                "vehicle": vehicle,
                "responsible": responsible,
                "document_count": len(audit_documents_by_id.get(audit.id, [])),
                "issue_count": len(open_issues),
                "high_issue_count": len(high_issues),
                "last_action": audit.summary or audit.reason or "-",
            }
        )
    audit_plates = [audit.plate for audit in technical_audits if audit.plate]
    audit_open_tasks = (
        db.scalar(select(func.count()).select_from(Task).where(Task.plate.in_(audit_plates), Task.closed_at.is_(None)))
        if audit_plates
        else 0
    ) or 0
    metrics = {
        "open_audits": db.scalar(
            select(func.count()).select_from(VehicleHistoryAudit).where(VehicleHistoryAudit.status != "closed")
        ) or 0,
        "critical_vehicles": sum(1 for row in technical_audit_rows if row["high_issue_count"]),
        "open_problems": db.scalar(
            select(func.count())
            .select_from(VehicleHistoryAuditIssue)
            .where(VehicleHistoryAuditIssue.status.in_(unresolved_issue_states))
        ) or 0,
        "open_tasks": audit_open_tasks,
        "documents_to_validate": db.scalar(
            select(func.count())
            .select_from(VehicleHistoryAuditDocument)
            .where(VehicleHistoryAuditDocument.extraction_status.in_(("pending", "por_validar", "pending_validation", "extracted")))
        ) or 0,
    }
    highlighted_issues = db.scalars(
        select(VehicleHistoryAuditIssue)
        .where(VehicleHistoryAuditIssue.status.in_(unresolved_issue_states))
        .order_by(VehicleHistoryAuditIssue.id.desc())
        .limit(12)
    ).all()
    return {
        "technical_audit_rows": technical_audit_rows,
        "technical_audit_metrics": metrics,
        "highlighted_audit_issues": highlighted_issues,
        "unresolved_issue_states": unresolved_issue_states,
    }


@web_router.get("/management-center", response_class=HTMLResponse)
def management_center_page(request: Request):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request)
    if denied:
        return denied
    with SessionLocal() as db:
        process_type = ensure_management_defaults(db)
        ensure_history_audit_process_type(db)
        db.commit()
        claims_metrics = management_business_metrics(db, process_type.id)
        audit_context = _technical_audit_dashboard_context(db, limit=80)
        response = templates.TemplateResponse(
            request,
            "management_center.html",
            {
                "claims_metrics": claims_metrics,
                "audit_metrics": audit_context["technical_audit_metrics"],
            },
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


@web_router.get("/management-center/sinistros", response_class=HTMLResponse)
def management_center_claims_page(
    request: Request,
    view: str = "processes",
    origin: str = "all",
    process_page: int = 1,
    queue_page: int = 1,
    status: str | None = None,
    plate: str | None = None,
    document: str | None = None,
    customer: str | None = None,
    driver: str | None = None,
    pending: str | None = None,
    liability: str | None = None,
    imported: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request)
    if denied:
        return denied
    if view not in {"processes", "origins"}:
        view = "processes"
    if origin not in {"all", "ar", "refstro", "unclassified"}:
        origin = "all"
    liability_filter = normalize_liability_value(liability)
    process_page = max(process_page, 1)
    queue_page = max(queue_page, 1)
    process_page_size = 12
    queue_page_size = 10

    def page_url(**updates: object) -> str:
        params = {
            "view": view,
            "origin": origin,
            "process_page": process_page,
            "queue_page": queue_page,
            "status": status or "",
            "plate": plate or "",
            "document": document or "",
            "customer": customer or "",
            "driver": driver or "",
            "pending": pending or "",
            "liability": liability_filter or "",
        }
        params.update(updates)
        clean_params = {key: value for key, value in params.items() if value not in (None, "")}
        return f"/management-center/sinistros?{urlencode(clean_params)}"

    with SessionLocal() as db:
        process_type = ensure_management_defaults(db)
        audit_process_type = ensure_history_audit_process_type(db)
        db.commit()
        query_filters = management_process_query_filters(
            process_type_id=process_type.id,
            status=status,
            plate=plate,
            document=document,
            customer=customer,
            driver=driver,
            pending=pending,
        )
        all_processes = db.scalars(
            select(ManagementProcess)
            .where(*query_filters)
            .order_by(
                ManagementProcess.pending_reason.is_(None),
                ManagementProcess.sla_due_on.is_(None),
                ManagementProcess.sla_due_on,
                ManagementProcess.id.desc(),
            )
        ).all()
        if liability_filter:
            all_processes = [
                process for process in all_processes
                if management_process_liability(process) == liability_filter
            ]
        process_total = len(all_processes)
        process_total_pages = max(1, (process_total + process_page_size - 1) // process_page_size)
        process_page = min(process_page, process_total_pages)
        processes = all_processes[(process_page - 1) * process_page_size:process_page * process_page_size]
        process_liabilities = {
            process.id: management_process_liability(process)
            for process in processes
        }
        process_ids = [process.id for process in processes]
        counts = process_association_counts(db, process_ids)
        claim_dates = {
            item.process_id: item.accident_date
            for item in (
                db.scalars(select(ClaimIncident).where(ClaimIncident.process_id.in_(process_ids))).all()
                if process_ids
                else []
            )
        }
        metrics = management_business_metrics(db, process_type.id)
        queue_total = db.scalar(
            select(func.count())
            .select_from(ManagementAction)
            .join(ManagementProcess, ManagementAction.process_id == ManagementProcess.id)
            .where(
                ManagementProcess.process_type_id == process_type.id,
                ManagementAction.status == "open",
            )
        ) or 0
        queue_total_pages = max(1, (queue_total + queue_page_size - 1) // queue_page_size)
        queue_page = min(queue_page, queue_total_pages)
        priority_rows = db.execute(
            select(ManagementProcess, ManagementAction)
            .join(ManagementAction, ManagementAction.process_id == ManagementProcess.id)
            .where(
                ManagementProcess.process_type_id == process_type.id,
                ManagementAction.status == "open",
            )
            .order_by(ManagementAction.mandatory.desc(), ManagementAction.due_on.is_(None), ManagementAction.due_on)
            .offset((queue_page - 1) * queue_page_size)
            .limit(queue_page_size)
        ).all()
        priority_process_ids = [row[0].id for row in priority_rows]
        priority_counts = process_association_counts(db, priority_process_ids)
        priority_claim_dates = {
            item.process_id: item.accident_date
            for item in (
                db.scalars(select(ClaimIncident).where(ClaimIncident.process_id.in_(priority_process_ids))).all()
                if priority_process_ids
                else []
            )
        }
        priority_items = [
            {
                "process": process,
                "action": action,
                "counts": priority_counts[process.id],
                "accident_date": priority_claim_dates.get(process.id),
            }
            for process, action in priority_rows
        ]
        rules = db.scalars(
            select(ManagementRule).where(
                ManagementRule.process_type_id == process_type.id,
                ManagementRule.active.is_(True),
            ).order_by(ManagementRule.severity.desc(), ManagementRule.id)
        ).all()
        recent_imports = db.scalars(
            select(ImportBatch)
            .where(ImportBatch.import_type.in_((AR_IMPORT_TYPE, CRAR_PER_VEHICLE_IMPORT_TYPE, REFSTRO_IMPORT_TYPE)))
            .order_by(ImportBatch.id.desc())
            .limit(5)
        ).all()
        origin_ar_query = select(ClaimRentwayAR).where(
            ClaimRentwayAR.source_file.is_not(None),
            ~ClaimRentwayAR.source_file.ilike("%crar_pervehicle%"),
            ~ClaimRentwayAR.source_file.ilike("%demo%"),
        )
        origin_ref_query = select(ClaimRefstroLine)
        if plate:
            origin_ar_query = origin_ar_query.where(ClaimRentwayAR.plate.ilike(f"%{plate.strip()}%"))
            origin_ref_query = origin_ref_query.where(ClaimRefstroLine.plate.ilike(f"%{plate.strip()}%"))
        origin_ars = []
        if origin in {"all", "ar", "unclassified"}:
            origin_ars = db.scalars(origin_ar_query.order_by(ClaimRentwayAR.request_date.desc(), ClaimRentwayAR.id.desc()).limit(80)).all()
        origin_refs = []
        if origin in {"all", "refstro", "unclassified"}:
            origin_refs = db.scalars(
                origin_ref_query.order_by(ClaimRefstroLine.accident_date.desc(), ClaimRefstroLine.refstro_reference.desc()).limit(600)
            ).all()
        origin_entity_links = db.scalars(
            select(ManagementProcessAssociation).where(ManagementProcessAssociation.active.is_(True))
        ).all()
        ar_process_by_id = {
            item.entity_id: item.process_id
            for item in origin_entity_links
            if item.entity_type == "claim_rentway_ar"
        }
        ref_process_by_id = {
            item.entity_id: item.process_id
            for item in origin_entity_links
            if item.entity_type == "claim_refstro_line"
        }
        process_ref_by_id = {
            item.id: item.internal_reference
            for item in db.scalars(select(ManagementProcess).where(ManagementProcess.process_type_id == process_type.id)).all()
        }
        origin_ar_rows = []
        for ar in origin_ars:
            process_id = ar_process_by_id.get(ar.id)
            if origin == "unclassified" and process_id:
                continue
            raw = ar.raw_json if isinstance(ar.raw_json, dict) else {}
            sources = raw.get("_sources", []) if isinstance(raw, dict) else []
            crar_sources = [
                source for source in sources
                if isinstance(source, dict) and "crar_pervehicle" in str(source.get("source_file", "")).lower()
            ]
            origin_ar_rows.append(
                {
                    "kind": "AR Rentway",
                    "reference": ar.ar_reference or "-",
                    "plate": ar.plate or "-",
                    "date": ar_reconciliation_date(ar),
                    "status": ar.status or "-",
                    "detail": ar.customer_name or ar.driver_name or ar.vehicle_reference or "-",
                    "process_id": process_id,
                    "process_reference": process_ref_by_id.get(process_id, "Por classificar") if process_id else "Por classificar",
                    "crar_enriched": bool(crar_sources),
                }
            )
        origin_ref_rows = []
        origin_ref_groups: dict[tuple, dict] = {}
        for ref_line in origin_refs:
            if ref_line.plate and ref_line.accident_date:
                group_key = ("incident", ref_line.plate.strip(), ref_line.accident_date)
            else:
                group_key = ("reference", ref_line.refstro_reference or f"linha-{ref_line.id}", ref_line.plate or "-", ref_line.accident_date)
            group = origin_ref_groups.setdefault(
                group_key,
                {
                    "kind": "REFSTRO",
                    "references": set(),
                    "plate": ref_line.plate or "-",
                    "date": ref_line.accident_date,
                    "line_ids": [],
                    "process_ids": set(),
                    "component_totals": {},
                    "value": 0.0,
                },
            )
            if ref_line.refstro_reference:
                group["references"].add(ref_line.refstro_reference)
            group["line_ids"].append(ref_line.id)
            process_id = ref_process_by_id.get(ref_line.id)
            if process_id:
                group["process_ids"].add(process_id)
            component = ref_line.component or "Sem componente"
            value = money_value(ref_line.claim_value)
            group["component_totals"][component] = group["component_totals"].get(component, 0.0) + value
            group["value"] += value
        for group in origin_ref_groups.values():
            process_ids = sorted(group["process_ids"])
            process_id = process_ids[0] if process_ids else None
            if origin == "unclassified" and process_ids:
                continue
            references = sorted(group["references"])
            component_breakdown = [
                {"component": component, "value": value}
                for component, value in sorted(group["component_totals"].items(), key=lambda item: (-item[1], item[0]))
            ]
            origin_ref_rows.append(
                {
                    "kind": "REFSTRO",
                    "reference": ", ".join(references) if references else "-",
                    "plate": group["plate"],
                    "date": group["date"],
                    "status": f"{len(group['line_ids'])} linha(s) / {len(references) or 1} referência(s)",
                    "component_count": len(component_breakdown) or 0,
                    "component_breakdown": component_breakdown,
                    "detail": f"{float(group['value'] or 0):.2f} €",
                    "process_id": process_id,
                    "process_reference": process_ref_by_id.get(process_id, "Por classificar") if process_id else "Por classificar",
                    "crar_enriched": False,
                    "selection_value": f"ref:{','.join(str(line_id) for line_id in group['line_ids'])}",
                }
            )
        origin_rows = []
        if origin in {"all", "ar", "unclassified"}:
            origin_rows.extend(origin_ar_rows)
        if origin in {"all", "refstro", "unclassified"}:
            origin_rows.extend(origin_ref_rows)
        origin_rows = sorted(origin_rows, key=lambda item: (item["date"] or date.min, item["kind"], item["reference"]), reverse=True)[:120]
        origin_stats = {
            "all": metrics["official_ar"] + metrics["participations"],
            "ars": metrics["official_ar"],
            "refstro": metrics["participations"],
            "unclassified": sum(1 for item in origin_rows if not item["process_id"]),
            "shown": len(origin_rows),
        }
        audit_filters = []
        if plate:
            audit_filters.append(VehicleHistoryAudit.plate.ilike(f"%{plate.strip()}%"))
        if view == "technical_audits" and status:
            audit_filters.append(VehicleHistoryAudit.status == status)
        audit_query = select(VehicleHistoryAudit).where(*audit_filters).order_by(VehicleHistoryAudit.updated_at.desc(), VehicleHistoryAudit.id.desc())
        technical_audits = db.scalars(audit_query.limit(120)).all()
        audit_ids = [audit.id for audit in technical_audits]
        audit_process_ids = [audit.management_process_id for audit in technical_audits if audit.management_process_id]
        audit_documents = (
            db.scalars(select(VehicleHistoryAuditDocument).where(VehicleHistoryAuditDocument.audit_id.in_(audit_ids))).all()
            if audit_ids
            else []
        )
        audit_issues = (
            db.scalars(select(VehicleHistoryAuditIssue).where(VehicleHistoryAuditIssue.audit_id.in_(audit_ids))).all()
            if audit_ids
            else []
        )
        audit_documents_by_id: dict[int, list[VehicleHistoryAuditDocument]] = defaultdict(list)
        for document_item in audit_documents:
            audit_documents_by_id[document_item.audit_id].append(document_item)
        audit_issues_by_id: dict[int, list[VehicleHistoryAuditIssue]] = defaultdict(list)
        for issue_item in audit_issues:
            audit_issues_by_id[issue_item.audit_id].append(issue_item)
        audit_processes_by_id = {
            item.id: item
            for item in (
                db.scalars(select(ManagementProcess).where(ManagementProcess.id.in_(audit_process_ids))).all()
                if audit_process_ids
                else []
            )
        }
        audit_vehicle_ids = [audit.vehicle_id for audit in technical_audits]
        audit_vehicles_by_id = {
            item.id: item
            for item in (
                db.scalars(select(Vehicle).where(Vehicle.id.in_(audit_vehicle_ids))).all()
                if audit_vehicle_ids
                else []
            )
        }
        audit_user_ids = [audit.responsible_user_id for audit in technical_audits if audit.responsible_user_id]
        audit_users_by_id = {
            item.id: item
            for item in (
                db.scalars(select(User).where(User.id.in_(audit_user_ids))).all()
                if audit_user_ids
                else []
            )
        }
        unresolved_issue_states = {"new", "in_analysis", "to_discuss", "waiting_evidence", "por_analisar", "em_discussao", "aguardar_resposta"}
        technical_audit_rows = []
        for audit in technical_audits:
            issues_for_audit = audit_issues_by_id.get(audit.id, [])
            open_issues = [item for item in issues_for_audit if item.status in unresolved_issue_states]
            high_issues = [item for item in open_issues if item.severity in {"high", "critical", "alta", "critica"}]
            process = audit_processes_by_id.get(audit.management_process_id or 0)
            vehicle = audit_vehicles_by_id.get(audit.vehicle_id)
            responsible = audit_users_by_id.get(audit.responsible_user_id or 0)
            technical_audit_rows.append(
                {
                    "audit": audit,
                    "process": process,
                    "vehicle": vehicle,
                    "responsible": responsible,
                    "document_count": len(audit_documents_by_id.get(audit.id, [])),
                    "issue_count": len(open_issues),
                    "high_issue_count": len(high_issues),
                    "last_action": audit.summary or audit.reason or "-",
                }
            )
        audit_plates = [audit.plate for audit in technical_audits if audit.plate]
        audit_open_tasks = (
            db.scalar(select(func.count()).select_from(Task).where(Task.plate.in_(audit_plates), Task.closed_at.is_(None)))
            if audit_plates
            else 0
        ) or 0
        technical_audit_metrics = {
            "open_audits": db.scalar(
                select(func.count()).select_from(VehicleHistoryAudit).where(VehicleHistoryAudit.status != "closed")
            ) or 0,
            "critical_vehicles": sum(1 for row in technical_audit_rows if row["high_issue_count"]),
            "open_problems": db.scalar(
                select(func.count())
                .select_from(VehicleHistoryAuditIssue)
                .where(VehicleHistoryAuditIssue.status.in_(unresolved_issue_states))
            ) or 0,
            "open_tasks": audit_open_tasks,
        }
        highlighted_audit_issues = db.scalars(
            select(VehicleHistoryAuditIssue)
            .where(VehicleHistoryAuditIssue.status.in_(unresolved_issue_states))
            .order_by(VehicleHistoryAuditIssue.id.desc())
            .limit(12)
        ).all()
        response = templates.TemplateResponse(
            request,
            "management_claims_center.html",
            {
                "process_type": process_type,
                "process_types": [process_type, audit_process_type],
                "processes": processes,
                "process_liabilities": process_liabilities,
                "counts": counts,
                "claim_dates": claim_dates,
                "process_pagination": {
                    "page": process_page,
                    "pages": process_total_pages,
                    "total": process_total,
                    "page_size": process_page_size,
                    "prev_url": page_url(view="processes", process_page=process_page - 1) if process_page > 1 else None,
                    "next_url": page_url(view="processes", process_page=process_page + 1) if process_page < process_total_pages else None,
                },
                "metrics": metrics,
                "priority_items": priority_items,
                "queue_pagination": {
                    "page": queue_page,
                    "pages": queue_total_pages,
                    "total": queue_total,
                    "page_size": queue_page_size,
                    "prev_url": page_url(view="processes", queue_page=queue_page - 1) if queue_page > 1 else None,
                    "next_url": page_url(view="processes", queue_page=queue_page + 1) if queue_page < queue_total_pages else None,
                },
                "rules": rules,
                "recent_imports": recent_imports,
                "active_view": view,
                "origin_filter": origin,
                "origin_rows": origin_rows,
                "origin_stats": origin_stats,
                "technical_audit_rows": technical_audit_rows,
                "technical_audit_metrics": technical_audit_metrics,
                "highlighted_audit_issues": highlighted_audit_issues,
                "history_audit_status_labels": HISTORY_AUDIT_STATUS_LABELS,
                "history_audit_phase_labels": HISTORY_AUDIT_PHASE_LABELS,
                "history_audit_issue_status_labels": HISTORY_AUDIT_ISSUE_STATUS_LABELS,
                "history_audit_issue_types": dict(HISTORY_AUDIT_ISSUE_TYPES),
                "status_labels": PROCESS_STATUS_LABELS,
                "phase_labels": PROCESS_PHASE_LABELS,
                "pending_labels": MANAGEMENT_PENDING_LABELS,
                "severity_labels": MANAGEMENT_SEVERITY_LABELS,
                "liability_labels": LIABILITY_LABELS,
                "management_import_type_labels": MANAGEMENT_IMPORT_TYPE_LABELS,
                "import_status_labels": IMPORT_STATUS_DISPLAY_LABELS,
                "AR_IMPORT_TYPE": AR_IMPORT_TYPE,
                "REFSTRO_IMPORT_TYPE": REFSTRO_IMPORT_TYPE,
                "filters": {
                    "status": status or "",
                    "plate": plate or "",
                    "document": document or "",
                    "customer": customer or "",
                    "driver": driver or "",
                    "pending": pending or "",
                    "liability": liability_filter or "",
                },
                "imported": imported,
                "page_loaded_at": datetime.now().strftime("%H:%M:%S"),
            },
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


@web_router.get("/management-center/auditorias", response_class=HTMLResponse)
def management_center_technical_audits_page(
    request: Request,
    status: str | None = None,
    plate: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request)
    if denied:
        return denied
    with SessionLocal() as db:
        ensure_history_audit_process_type(db)
        db.commit()
        audit_context = _technical_audit_dashboard_context(db, plate=plate, status=status)
        response = templates.TemplateResponse(
            request,
            "management_technical_audits.html",
            {
                **audit_context,
                "history_audit_status_labels": HISTORY_AUDIT_STATUS_LABELS,
                "history_audit_phase_labels": HISTORY_AUDIT_PHASE_LABELS,
                "history_audit_issue_status_labels": HISTORY_AUDIT_ISSUE_STATUS_LABELS,
                "history_audit_issue_types": dict(HISTORY_AUDIT_ISSUE_TYPES),
                "filters": {
                    "status": status or "",
                    "plate": plate or "",
                },
            },
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


@web_router.post("/management-center/import", response_class=HTMLResponse)
def management_center_import(
    request: Request,
    file: UploadFile,
    import_kind: str = Form("refstro"),
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request, write=True)
    if denied:
        return denied
    if import_kind not in {"ar", "ar_rentway_per_vehicle", "refstro"}:
        return RedirectResponse("/management-center/sinistros?imported=invalid_kind", status_code=303)
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".csv")):
        return RedirectResponse("/management-center/sinistros?imported=invalid_file", status_code=303)
    return RedirectResponse("/management-center/sinistros?imported=preview_required", status_code=303)


@web_router.post("/management-center/import-preview", response_class=HTMLResponse)
def management_center_import_preview(
    request: Request,
    file: UploadFile,
    import_kind: str = Form("refstro"),
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request, write=True)
    if denied:
        return denied
    if import_kind not in {"ar", "ar_rentway_per_vehicle", "refstro"}:
        return RedirectResponse("/management-center/sinistros?imported=invalid_kind", status_code=303)
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".csv")):
        return RedirectResponse("/management-center/sinistros?imported=invalid_file", status_code=303)
    suffix = Path(file.filename).suffix
    with NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file.file.read())
        tmp_path = Path(tmp.name)
    with SessionLocal() as db:
        known_ar_records = management_known_ar_records(db) if import_kind == "ar_rentway_per_vehicle" else {}
    try:
        preview = preview_claims_file(
            tmp_path,
            file.filename,
            import_kind=import_kind,
            known_ar_records=known_ar_records,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    with SessionLocal() as db:
        process_type = ensure_management_defaults(db)
        process_type_context = {"name": process_type.name}
        db.commit()
    return templates.TemplateResponse(
        request,
        "management_import_preview.html",
        {
            "preview": preview,
            "process_type": process_type_context,
        },
    )


@web_router.post("/management-center/load-originals", response_class=HTMLResponse)
def management_center_load_originals(
    request: Request,
    accident_report: UploadFile,
    crar: UploadFile,
    refstro_old: UploadFile,
    refstro_recent: UploadFile,
    from_date: str = Form("2024-01-01"),
    reset_confirm: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request, write=True)
    if denied:
        return denied
    if reset_confirm.strip().upper() != "CARREGAR":
        return RedirectResponse("/management-center/sinistros?imported=load_confirm_missing", status_code=303)
    uploads = {
        "accident_report": accident_report,
        "crar": crar,
        "refstro_old": refstro_old,
        "refstro_recent": refstro_recent,
    }
    if any(not item.filename or not item.filename.lower().endswith(".xlsx") for item in uploads.values()):
        return RedirectResponse("/management-center/sinistros?imported=invalid_file", status_code=303)
    try:
        cutoff_date = date.fromisoformat(from_date)
    except ValueError:
        return RedirectResponse("/management-center/sinistros?imported=invalid_date", status_code=303)

    with TemporaryDirectory(prefix="management_center_load_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        paths = {}
        for key, upload in uploads.items():
            target = tmp_root / (upload.filename or f"{key}.xlsx")
            target.write_bytes(upload.file.read())
            paths[key] = target
        with SessionLocal() as db:
            from scripts.import_management_center_originals import (
                final_counts,
                import_accident_report,
                import_crar,
                import_refstro_sources,
                reset_management_center,
            )

            reset_management_center(db)
            import_accident_report(db, paths["accident_report"], user_id, cutoff_date=cutoff_date)
            import_crar(db, paths["crar"], user_id, cutoff_date=cutoff_date)
            import_refstro_sources(db, paths, user_id, cutoff_date=cutoff_date)
            counts = final_counts(db)
            record_audit(
                db,
                action="management_center.load_originals.completed",
                entity_type="management_center",
                detail="Carga final dos originais Sinistros/AR aplicada pelo Centro de Gestão.",
                user_id=user_id,
                after_json={"from_date": cutoff_date.isoformat(), "counts": counts},
            )
            db.commit()
    return RedirectResponse("/management-center/sinistros?imported=loaded", status_code=303)


@web_router.get("/management-center/reconciliation", response_class=HTMLResponse)
def management_center_reconciliation(
    request: Request,
    plate: str | None = None,
    selected_plate: str | None = None,
    selected_ref_lines: str | None = None,
    mode: str = "pending",
    window_days: int = 30,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login?next=%2Fmanagement-center%2Freconciliation", status_code=303)
    denied = management_center_denied(request)
    if denied:
        return denied
    if mode not in {"pending", "all", "strong", "doubt", "monitoring"}:
        mode = "pending"
    window_days = max(1, min(window_days, 90))
    with SessionLocal() as db:
        process_type = ensure_management_defaults(db)
        metrics = management_business_metrics(db, process_type.id)
        reconciliation = build_reconciliation_rows(
            db,
            plate_filter=plate,
            selected_ref_line_ids=parse_ref_line_ids(selected_ref_lines),
            selected_plate=selected_plate,
            mode=mode,
            window_days=window_days,
        )
        response = templates.TemplateResponse(
            request,
            "management_reconciliation.html",
            {
                "process_type": process_type,
                "metrics": metrics,
                "reconciliation": reconciliation,
                "mode_labels": {
                    "pending": "Pendentes",
                    "all": "Todos",
                    "strong": "Match forte",
                    "doubt": "Dúvidas",
                    "monitoring": "Monitorização",
                },
                "page_loaded_at": datetime.now().strftime("%H:%M:%S"),
            },
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response



@web_router.post("/management-center/reconciliation/associate", response_class=HTMLResponse)
def management_center_reconciliation_associate(
    request: Request,
    mode: str = Form("attach_to_ar"),
    ref_line_ids: str = Form(""),
    ar_id: int | None = Form(None),
    selected_plate: str = Form(""),
    selected_mode: str = Form("pending"),
    window_days: int = Form(30),
    plate_filter: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request, write=True)
    if denied:
        return denied

    ref_ids = parse_ref_line_ids(ref_line_ids)
    if not ref_ids:
        return RedirectResponse(
            f"/management-center/reconciliation?{urlencode({'selected_plate': selected_plate, 'mode': selected_mode, 'window_days': window_days, 'plate': plate_filter})}",
            status_code=303,
        )

    with SessionLocal() as db:
        process_type = ensure_management_defaults(db)
        target_process_id: int | None = None
        refs = db.scalars(
            select(ClaimRefstroLine).where(ClaimRefstroLine.id.in_(ref_ids)).order_by(ClaimRefstroLine.accident_date, ClaimRefstroLine.id)
        ).all()
        if not refs or len(refs) != len(ref_ids):
            return RedirectResponse(
                f"/management-center/reconciliation?selected_plate={selected_plate}&mode={selected_mode}&window_days={window_days}&plate={plate_filter}",
                status_code=303,
            )

        process_ids_to_refresh: set[int] = set()
        if mode == "attach_to_ar":
            if not ar_id:
                return RedirectResponse(
                    f"/management-center/reconciliation?selected_plate={selected_plate}&mode={selected_mode}&window_days={window_days}&plate={plate_filter}&error=missing_ar",
                    status_code=303,
                )
            ar = db.get(ClaimRentwayAR, ar_id)
            if not ar:
                return RedirectResponse(
                    f"/management-center/reconciliation?selected_plate={selected_plate}&mode={selected_mode}&window_days={window_days}&plate={plate_filter}&error=invalid_ar",
                    status_code=303,
                )
            ar_assoc = db.scalar(
                select(ManagementProcessAssociation).where(
                    ManagementProcessAssociation.entity_type == "claim_rentway_ar",
                    ManagementProcessAssociation.entity_id == ar.id,
                    ManagementProcessAssociation.active.is_(True),
                ).order_by(ManagementProcessAssociation.id.desc())
            )
            if ar_assoc:
                target_process_id = ar_assoc.process_id
            else:
                claim = create_claim_process(
                    db,
                    process_type,
                    plate=ar.plate,
                    accident_date=ar_reconciliation_date(ar),
                    customer_name=ar.customer_name,
                    driver_name=ar.driver_name,
                    document_reference=ar.ar_reference,
                    user_id=user_id,
                )
                target_process_id = claim.process_id
                db.flush()
                associate_to_process(
                    db,
                    target_process_id,
                    entity_type="claim_rentway_ar",
                    entity_id=ar.id,
                    reason="AR associado no fluxo de reconciliação.",
                    user_id=user_id,
                )
            for ref in refs:
                previous = db.scalar(
                    select(ManagementProcessAssociation).where(
                        ManagementProcessAssociation.entity_type == "claim_refstro_line",
                        ManagementProcessAssociation.entity_id == ref.id,
                        ManagementProcessAssociation.active.is_(True),
                    )
                )
                if previous and previous.process_id != target_process_id:
                    end_association(db, previous, reason="Reconciliação: reatribuição para processo AR selecionado.", user_id=user_id)
                    process_ids_to_refresh.add(previous.process_id)
                    add_history(
                        db,
                        previous.process_id,
                        action="association.moved",
                        entity_type="claim_refstro_line",
                        entity_id=ref.id,
                        detail=f"REFSTRO {ref.refstro_reference or ref.id} movido para {target_process_id}",
                        user_id=user_id,
                    )
                elif previous and previous.process_id == target_process_id:
                    process_ids_to_refresh.add(target_process_id)
                    continue

                associate_to_process(
                    db,
                    target_process_id,
                    entity_type="claim_refstro_line",
                    entity_id=ref.id,
                    reason="REFSTRO associado após validação manual.",
                    user_id=user_id,
                )
                process_ids_to_refresh.add(target_process_id)

        elif mode == "create_new":
            ref = refs[0]
            selected_ar = db.get(ClaimRentwayAR, ar_id) if ar_id else None
            reference_plate = ref.plate or (selected_ar.plate if selected_ar else None)
            candidate_date = ref.accident_date
            claim = create_claim_process(
                db,
                process_type,
                plate=reference_plate,
                accident_date=candidate_date,
                customer_name=selected_ar.customer_name if selected_ar else ref.customer_name,
                driver_name=selected_ar.driver_name if selected_ar else ref.driver_name,
                document_reference=(selected_ar.ar_reference if selected_ar else None) or ref.document_reference,
                user_id=user_id,
            )
            target_process_id = claim.process_id
            if selected_ar:
                associate_to_process(
                    db,
                    target_process_id,
                    entity_type="claim_rentway_ar",
                    entity_id=selected_ar.id,
                    reason="AR associado ao processo criado em reconciliação.",
                    user_id=user_id,
                )
                process_ids_to_refresh.add(target_process_id)
            for ref in refs:
                associate_to_process(
                    db,
                    target_process_id,
                    entity_type="claim_refstro_line",
                    entity_id=ref.id,
                    reason="REFSTRO associado após criação de SIN.",
                    user_id=user_id,
                )
            process_ids_to_refresh.add(target_process_id)
        else:
            return RedirectResponse(
                f"/management-center/reconciliation?selected_plate={selected_plate}&mode={selected_mode}&window_days={window_days}&plate={plate_filter}",
                status_code=303,
            )

        for process_id in process_ids_to_refresh:
            claim = db.scalar(select(ClaimIncident).where(ClaimIncident.process_id == process_id))
            if claim:
                refresh_claim_state(db, claim)
        db.commit()

    if target_process_id:
        return RedirectResponse(
            f"/management-center/{target_process_id}?updated=association&ref_focus={selected_plate}",
            status_code=303,
        )
    return RedirectResponse(
        f"/management-center/reconciliation?selected_plate={selected_plate}&mode={selected_mode}&window_days={window_days}&plate={plate_filter}",
        status_code=303,
    )
@web_router.get("/management-center/{process_id}", response_class=HTMLResponse)
def management_center_detail(request: Request, process_id: int, updated: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request)
    if denied:
        return denied
    with SessionLocal() as db:
        process = db.get(ManagementProcess, process_id)
        if not process:
            return RedirectResponse("/management-center", status_code=303)
        process_type = db.get(ManagementProcessType, process.process_type_id)
        if process_type and process_type.code == "vehicle_history_audit":
            audit = db.scalar(
                select(VehicleHistoryAudit).where(VehicleHistoryAudit.management_process_id == process.id)
            )
            if audit:
                return RedirectResponse(f"/fleet/{audit.vehicle_id}/history-audits/{audit.id}", status_code=303)
        claim = db.scalar(select(ClaimIncident).where(ClaimIncident.process_id == process.id))
        associations = db.scalars(
            select(ManagementProcessAssociation)
            .where(ManagementProcessAssociation.process_id == process.id)
            .order_by(ManagementProcessAssociation.active.desc(), ManagementProcessAssociation.id.desc())
        ).all()
        ar_ids = [item.entity_id for item in associations if item.entity_type == "claim_rentway_ar"]
        refstro_ids = [item.entity_id for item in associations if item.entity_type == "claim_refstro_line"]
        ars = {
            item.id: item
            for item in (db.scalars(select(ClaimRentwayAR).where(ClaimRentwayAR.id.in_(ar_ids))).all() if ar_ids else [])
        }
        refstros = {
            item.id: item
            for item in (
                db.scalars(select(ClaimRefstroLine).where(ClaimRefstroLine.id.in_(refstro_ids))).all()
                if refstro_ids
                else []
            )
        }
        ar_crar_status = {}
        for ar in ars.values():
            raw_json = ar.raw_json if isinstance(ar.raw_json, dict) else {}
            sources = raw_json.get("_sources", []) if isinstance(raw_json, dict) else []
            crar_sources = [
                source for source in sources
                if isinstance(source, dict) and "crar_pervehicle" in str(source.get("source_file", "")).lower()
            ]
            if len(crar_sources) > 1:
                ar_crar_status[ar.id] = "Conflito"
            elif len(crar_sources) == 1:
                ar_crar_status[ar.id] = "CRAR complementar"
            else:
                ar_crar_status[ar.id] = "Não recebido"
        actions = db.scalars(
            select(ManagementAction)
            .where(ManagementAction.process_id == process.id)
            .order_by(ManagementAction.status, ManagementAction.mandatory.desc(), ManagementAction.due_on)
        ).all()
        active_associations = [item for item in associations if item.active]
        inactive_associations = [item for item in associations if not item.active]
        ar_associations = [item for item in active_associations if item.entity_type == "claim_rentway_ar"]
        refstro_associations = [
            item for item in active_associations if item.entity_type == "claim_refstro_line"
        ]
        ar_references = sorted(
            {
                ars[item.entity_id].ar_reference
                for item in ar_associations
                if item.entity_id in ars and ars[item.entity_id].ar_reference
            }
        )
        refstro_references = sorted(
            {
                refstros[item.entity_id].refstro_reference
                for item in refstro_associations
                if item.entity_id in refstros and refstros[item.entity_id].refstro_reference
            }
        )
        refstro_component_totals: dict[str, float] = {}
        for association in refstro_associations:
            refstro = refstros.get(association.entity_id)
            if not refstro:
                continue
            component = refstro.component or "Sem componente"
            refstro_component_totals[component] = refstro_component_totals.get(component, 0.0) + money_value(refstro.claim_value)
        tracking_references = {
            "ar_references": ar_references,
            "refstro_references": refstro_references,
            "refstro_line_count": len(refstro_associations),
            "refstro_component_breakdown": [
                {"component": component, "value": value}
                for component, value in sorted(refstro_component_totals.items(), key=lambda item: (-item[1], item[0]))
            ],
        }
        rules = db.scalars(
            select(ManagementRule).where(
                ManagementRule.process_type_id == process.process_type_id,
                ManagementRule.active.is_(True),
            ).order_by(ManagementRule.severity.desc(), ManagementRule.id)
        ).all()
        history = db.scalars(
            select(ManagementHistory)
            .where(ManagementHistory.process_id == process.id)
            .order_by(ManagementHistory.changed_at.desc(), ManagementHistory.id.desc())
            .limit(80)
        ).all()
        other_processes = db.scalars(
            select(ManagementProcess)
            .where(
                ManagementProcess.process_type_id == process.process_type_id,
                ManagementProcess.id != process.id,
            )
            .order_by(ManagementProcess.internal_reference.desc())
            .limit(120)
        ).all()
        return templates.TemplateResponse(
            request,
            "management_process_detail.html",
            {
                "process": process,
                "liability_value": management_process_liability(process),
                "process_type": process_type,
                "claim": claim,
                "associations": associations,
                "active_associations": active_associations,
                "inactive_associations": inactive_associations,
                "ar_associations": ar_associations,
                "refstro_associations": refstro_associations,
                "ars": ars,
                "refstros": refstros,
                "tracking_references": tracking_references,
                "actions": actions,
                "rules": rules,
                "history": history,
                "other_processes": other_processes,
                "ar_crar_status": ar_crar_status,
                "status_labels": PROCESS_STATUS_LABELS,
                "phase_labels": PROCESS_PHASE_LABELS,
                "pending_labels": MANAGEMENT_PENDING_LABELS,
                "liability_labels": LIABILITY_LABELS,
                "liability_options": LIABILITY_LABELS.items(),
                "severity_labels": MANAGEMENT_SEVERITY_LABELS,
                "action_status_labels": ACTION_STATUS_LABELS,
                "updated": updated,
            },
        )


@web_router.post("/management-center/{process_id}/liability", response_class=HTMLResponse)
def management_center_set_liability(request: Request, process_id: int, liability: str = Form(...)):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request, write=True)
    if denied:
        return denied
    selected_liability = normalize_liability_value(liability)
    if not selected_liability:
        return RedirectResponse(f"/management-center/{process_id}?updated=liability_invalid", status_code=303)

    with SessionLocal() as db:
        process = db.get(ManagementProcess, process_id)
        if not process:
            return RedirectResponse("/management-center", status_code=303)

        raw_summary = process.raw_summary_json
        if not isinstance(raw_summary, dict):
            raw_summary = {}
        old_value = management_process_liability(process)
        raw_summary["liability"] = selected_liability
        process.raw_summary_json = raw_summary
        db.add(
            ManagementHistory(
                process_id=process_id,
                user_id=user_id,
                action="claim.liability",
                entity_type="management_process",
                entity_id=str(process.id),
                old_value=LIABILITY_LABELS.get(old_value or "", old_value or ""),
                new_value=LIABILITY_LABELS.get(selected_liability, selected_liability),
                detail="Classificação de responsabilidade atualizada.",
            )
        )
        db.commit()
    return RedirectResponse(f"/management-center/{process_id}?updated=liability", status_code=303)


@web_router.post("/management-center/{process_id}/actions/{action_id}/complete", response_class=HTMLResponse)
def management_center_complete_action(request: Request, process_id: int, action_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request, write=True)
    if denied:
        return denied
    with SessionLocal() as db:
        action = db.get(ManagementAction, action_id)
        if not action or action.process_id != process_id:
            return RedirectResponse(f"/management-center/{process_id}", status_code=303)
        action.status = "done"
        action.completed_at = datetime.now(UTC)
        action.completed_by_id = user_id
        db.add(
            ManagementHistory(
                process_id=process_id,
                user_id=user_id,
                action="action.completed",
                entity_type="management_action",
                entity_id=str(action.id),
                old_value="open",
                new_value="done",
                detail=action.title,
            )
        )
        db.commit()
    return RedirectResponse(f"/management-center/{process_id}?updated=action", status_code=303)


@web_router.post("/management-center/{process_id}/associations/{association_id}/move", response_class=HTMLResponse)
def management_center_move_association(
    request: Request,
    process_id: int,
    association_id: int,
    target_process_id: int = Form(...),
    reason: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    denied = management_center_denied(request, write=True)
    if denied:
        return denied
    with SessionLocal() as db:
        association = db.get(ManagementProcessAssociation, association_id)
        target = db.get(ManagementProcess, target_process_id)
        if not association or association.process_id != process_id or not target:
            return RedirectResponse(f"/management-center/{process_id}", status_code=303)
        move_reason = reason.strip() or f"Correção para {target.internal_reference}."
        end_association(db, association, reason=move_reason, user_id=user_id)
        db.add(
            ManagementProcessAssociation(
                process_id=target.id,
                entity_type=association.entity_type,
                entity_id=association.entity_id,
                association_role=association.association_role,
                active=True,
                reason=move_reason,
                created_by_id=user_id,
            )
        )
        db.add(
            ManagementHistory(
                process_id=target.id,
                user_id=user_id,
                action="association.created",
                entity_type=association.entity_type,
                entity_id=str(association.entity_id),
                new_value="active",
                detail=f"Associação movida de {process_id}. {move_reason}",
            )
        )
        source_claim = db.scalar(select(ClaimIncident).where(ClaimIncident.process_id == process_id))
        target_claim = db.scalar(select(ClaimIncident).where(ClaimIncident.process_id == target.id))
        if source_claim:
            refresh_claim_state(db, source_claim)
        if target_claim:
            refresh_claim_state(db, target_claim)
        db.commit()
    return RedirectResponse(f"/management-center/{process_id}?updated=association", status_code=303)


@web_router.get("/imports/{batch_id}/errors.csv")
def import_errors_csv(request: Request, batch_id: int):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        batch = db.get(ImportBatch, batch_id)
        if not batch:
            return RedirectResponse("/imports", status_code=303)
        output = io.StringIO()
        writer = csv.writer(output, lineterminator="\n")
        writer.writerow(["lote", "linha", "entidade", "erro"])
        for error in db.scalars(select(ImportError).where(ImportError.batch_id == batch.id).order_by(ImportError.id)):
            writer.writerow([batch.id, error.row_number or "", error.entity_type or "", error.error_message])
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="import_errors_{batch_id}.csv"'},
    )


@web_router.get("/imports", response_class=HTMLResponse)
def imports_page(request: Request, type: str | None = None):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        import_types = [
            {
                "code": "rentway_fleet",
                "source_system": "rentway",
                "title": "Frota Rentway",
                "description": "Atualização da frota importada do Rentway.",
                "import_url": "/imports/fleet",
                "history_url": "/imports?type=rentway_fleet",
            },
            {
                "code": "technical_history",
                "source_system": "workshop_history",
                "title": "Histórico técnico / Oficina",
                "description": "Histórico técnico importado para a ficha da viatura.",
                "import_url": "/imports/technical-history",
                "history_url": "/imports?type=technical_history",
            },
            {
                "code": TASK_BULK_IMPORT_TYPE,
                "source_system": "carfast",
                "title": "Tarefas em massa",
                "description": "Criar tarefa mãe e subtarefas a partir de Excel/CSV.",
                "import_url": "/imports/tasks",
                "history_url": "/imports?type=task_bulk",
                "created_label": "Subtarefas",
                "updated_label": "Linhas",
            },
            {
                "code": TRADE_DEBT_IMPORT_TYPE,
                "source_system": "carfast",
                "title": "Dívida para comércio",
                "description": "Preencher Valor em dívida e Entidade financeira na Gestão CarFast da viatura.",
                "import_url": "/imports/trade-debt",
                "history_url": f"/imports?type={TRADE_DEBT_IMPORT_TYPE}",
                "created_label": "Criadas",
                "updated_label": "Viaturas",
            },
            {
                "code": AR_IMPORT_TYPE,
                "source_system": "rentway",
                "title": "AR Rentway",
                "description": "ARs associados ao SIN; o AR não é a referência única.",
                "import_url": "/management-center/sinistros",
                "history_url": f"/imports?type={AR_IMPORT_TYPE}",
                "created_label": "ARs",
                "updated_label": "SIN atualizados",
            },
            {
                "code": REFSTRO_IMPORT_TYPE,
                "source_system": "carfast",
                "title": "REFSTRO / componentes",
                "description": "Linhas REFSTRO associadas ao SIN por matrícula e data.",
                "import_url": "/management-center/sinistros",
                "history_url": f"/imports?type={REFSTRO_IMPORT_TYPE}",
                "created_label": "Linhas",
                "updated_label": "SIN atualizados",
            },
        ]
        type_codes = {item["code"] for item in import_types}
        selected_type = type if type in type_codes else None
        batch_query = select(ImportBatch).order_by(ImportBatch.id.desc()).limit(100)
        if selected_type:
            batch_query = (
                select(ImportBatch)
                .where(ImportBatch.import_type == selected_type)
                .order_by(ImportBatch.id.desc())
                .limit(100)
            )
        batches = db.scalars(batch_query).all()
        import_cards = []
        for item in import_types:
            latest_batch = db.scalars(
                select(ImportBatch)
                .where(ImportBatch.import_type == item["code"])
                .order_by(ImportBatch.id.desc())
                .limit(1)
            ).first()
            totals = db.execute(
                select(
                    func.count(ImportBatch.id),
                    func.coalesce(func.sum(ImportBatch.total_rows), 0),
                    func.coalesce(func.sum(ImportBatch.created_rows), 0),
                    func.coalesce(func.sum(ImportBatch.updated_rows), 0),
                    func.coalesce(func.sum(ImportBatch.error_rows), 0),
                ).where(ImportBatch.import_type == item["code"])
            ).one()
            import_cards.append(
                {
                    **item,
                    "count": totals[0] or 0,
                    "total_rows": totals[1] or 0,
                    "created_rows": totals[2] or 0,
                    "updated_rows": totals[3] or 0,
                    "error_rows": totals[4] or 0,
                    "latest_batch": latest_batch,
                    "active": selected_type == item["code"],
                }
            )
        return templates.TemplateResponse(
            request,
            "imports.html",
            {
                "batches": batches,
                "import_cards": import_cards,
                "selected_type": selected_type,
                "selected_card": next((item for item in import_cards if item["active"]), None),
            },
        )


@web_router.get("/imports/{batch_id}", response_class=HTMLResponse)
def import_detail(request: Request, batch_id: int):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        batch = db.get(ImportBatch, batch_id)
        if not batch:
            return RedirectResponse("/imports", status_code=303)
        files = db.scalars(
            select(ImportFile).where(ImportFile.batch_id == batch.id).order_by(ImportFile.id)
        ).all()
        errors = db.scalars(
            select(ImportError).where(ImportError.batch_id == batch.id).order_by(ImportError.id).limit(100)
        ).all()
        raw_rows = db.scalar(
            select(func.count()).select_from(ImportRawRow).where(ImportRawRow.batch_id == batch.id)
        ) or 0
        created_tasks = db.scalars(
            select(Task)
            .where(Task.entity_type == "import_batch", Task.entity_id == str(batch.id))
            .order_by(Task.parent_task_id.is_(None), Task.id)
        ).all()
        return templates.TemplateResponse(
            request,
            "import_detail.html",
            {
                "batch": batch,
                "files": files,
                "errors": errors,
                "raw_rows": raw_rows,
                "created_tasks": created_tasks,
            },
        )


@web_router.get("/documents", response_class=HTMLResponse)
def documents_center_page(
    request: Request,
    created: str | None = None,
    updated: str | None = None,
    feedback_saved: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        metrics = {
            "total": db.scalar(select(func.count()).select_from(Document)) or 0,
            "unclassified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status.in_(("received", "unclassified")))
            )
            or 0,
            "classified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "classified")
            )
            or 0,
            "archived": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "archived")
            )
            or 0,
        }
        return templates.TemplateResponse(
            request,
            "documents_center.html",
            {
                "metrics": metrics,
                "created": created,
                "updated": updated,
                "feedback_saved": feedback_saved,
            },
        )


@web_router.get("/documents/new", response_class=HTMLResponse)
def documents_new_page(
    request: Request,
    error: str | None = None,
    vehicle_id: int | None = None,
    plate: str = "",
    classification: str = "",
    document_type: str = "",
    status: str = "",
    source: str = "",
    title: str = "",
    supplier_name: str = "",
    customer_name: str = "",
    document_date: str = "",
    url_original: str = "",
    url_archive: str = "",
    entry_channel: str = "",
    source_sender: str = "",
    source_subject: str = "",
    task_id: str = "",
    workshop_process_id: str = "",
    import_batch_id: str = "",
    notes: str = "",
    return_url: str = "",
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    clean_plate = plate.strip().upper()
    selected_vehicle_id = vehicle_id
    vehicle_ctx = None
    with SessionLocal() as db:
        if selected_vehicle_id:
            vehicle = db.get(Vehicle, selected_vehicle_id)
            if vehicle:
                clean_plate = clean_plate or (vehicle.plate or "")
                vehicle_ctx = clean_vehicle_display_context(db, vehicle)
    clean_classification = classification if classification in DOCUMENT_AREA_LABELS else "workshop"
    clean_document_type = normalize_document_type_for_area(document_type, clean_classification)
    clean_status = status if status in DOCUMENT_STATUS_LABELS else "received"
    clean_source = source if source in dict(DOCUMENT_SOURCES) else "manual"
    clean_return_url = return_url.strip()
    if clean_return_url and (not clean_return_url.startswith("/v2-clean/") or clean_return_url.startswith("//")):
        clean_return_url = ""
    if not clean_return_url and selected_vehicle_id:
        clean_return_url = f"/v2-clean/fleet/{selected_vehicle_id}/documents"
    is_clean_mode = bool(clean_return_url.startswith("/v2-clean/") or selected_vehicle_id)
    return templates.TemplateResponse(
        request,
        "clean_document_new.html" if is_clean_mode else "documents_new.html",
        {
            "areas": DOCUMENT_AREAS,
            "document_types": DOCUMENT_TYPES,
            "document_type_areas": DOCUMENT_TYPE_AREAS,
            "statuses": DOCUMENT_STATUSES,
            "sources": DOCUMENT_SOURCES,
            "error": error,
            "is_clean_mode": is_clean_mode,
            "vehicle_ctx": vehicle_ctx,
            "prefill": {
                "vehicle_id": selected_vehicle_id or "",
                "plate": clean_plate,
                "classification": clean_classification,
                "document_type": clean_document_type,
                "status": clean_status,
                "source": clean_source,
                "title": title.strip(),
                "notes": notes.strip(),
                "url_original": url_original.strip(),
                "url_archive": url_archive.strip(),
                "supplier_name": supplier_name.strip(),
                "customer_name": customer_name.strip(),
                "document_date": document_date.strip(),
                "entry_channel": entry_channel.strip(),
                "source_sender": source_sender.strip(),
                "source_subject": source_subject.strip(),
                "task_id": task_id.strip(),
                "workshop_process_id": workshop_process_id.strip(),
                "import_batch_id": import_batch_id.strip(),
                "return_url": clean_return_url,
            },
        },
    )


@web_router.get("/documents/manage", response_class=HTMLResponse)
def documents_manage_page(
    request: Request,
    q: str = "",
    status: str = "",
    area: str = "",
    document_type: str = "",
    created: str | None = None,
    updated: str | None = None,
    error: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_q = q.strip()
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)

        statement = select(Document)
        if clean_q:
            pattern = f"%{clean_q}%"
            statement = statement.where(
                or_(
                    Document.title.ilike(pattern),
                    Document.plate.ilike(pattern),
                    Document.supplier_name.ilike(pattern),
                    Document.customer_name.ilike(pattern),
                    Document.entry_channel.ilike(pattern),
                    Document.source_sender.ilike(pattern),
                    Document.source_subject.ilike(pattern),
                )
            )
        if status in DOCUMENT_STATUS_LABELS:
            statement = statement.where(Document.status == status)
        if area in DOCUMENT_AREA_LABELS:
            statement = statement.where(Document.classification == area)
        if document_type in DOCUMENT_TYPE_LABELS:
            statement = statement.where(Document.document_type == document_type)

        documents = db.scalars(statement.order_by(Document.id.desc()).limit(100)).all()
        metrics = {
            "total": db.scalar(select(func.count()).select_from(Document)) or 0,
            "unclassified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status.in_(("received", "unclassified")))
            )
            or 0,
            "classified": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "classified")
            )
            or 0,
            "archived": db.scalar(
                select(func.count()).select_from(Document).where(Document.status == "archived")
            )
            or 0,
        }
        return templates.TemplateResponse(
            request,
            "documents.html",
            {
                "user": user,
                "documents": documents,
                "metrics": metrics,
                "filters": {
                    "q": q,
                    "status": status,
                    "area": area,
                    "document_type": document_type,
                },
                "areas": DOCUMENT_AREAS,
                "area_labels": DOCUMENT_AREA_LABELS,
                "document_types": DOCUMENT_TYPES,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "document_type_areas": DOCUMENT_TYPE_AREAS,
                "statuses": DOCUMENT_STATUSES,
                "status_labels": DOCUMENT_STATUS_LABELS,
                "sources": DOCUMENT_SOURCES,
                "created": created,
                "updated": updated,
                "error": error,
            },
        )


@web_router.post("/documents", response_class=HTMLResponse)
@web_router.post("/documents/new", response_class=HTMLResponse)
def document_create(
    request: Request,
    title: str = Form(""),
    classification: str = Form("workshop"),
    document_type: str = Form("workshop_other"),
    status: str = Form("received"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    plate: str = Form(""),
    supplier_name: str = Form(""),
    customer_name: str = Form(""),
    vehicle_id: str = Form(""),
    task_id: str = Form(""),
    workshop_process_id: str = Form(""),
    import_batch_id: str = Form(""),
    notes: str = Form(""),
    return_url: str = Form(""),
    document_file: UploadFile | None = File(None),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_return_url = return_url.strip()
    if clean_return_url and (not clean_return_url.startswith("/v2-clean/") or clean_return_url.startswith("//")):
        clean_return_url = ""
    is_clean_target = bool(
        clean_return_url.startswith("/v2-clean/")
        or request.url.path.startswith("/v2-clean/")
        or vehicle_id.strip()
    )
    new_document_form_path = "/v2-clean/documents/new" if is_clean_target else "/documents/new"

    def document_error_redirect(message: str) -> RedirectResponse:
        params = {
            "error": message,
            "vehicle_id": vehicle_id.strip(),
            "plate": plate.strip().upper(),
            "classification": classification,
            "document_type": document_type,
            "status": status,
            "source": source,
            "title": title.strip(),
            "supplier_name": supplier_name.strip(),
            "customer_name": customer_name.strip(),
            "document_date": document_date.strip(),
            "url_original": url_original.strip(),
            "url_archive": url_archive.strip(),
            "entry_channel": entry_channel.strip(),
            "source_sender": source_sender.strip(),
            "source_subject": source_subject.strip(),
            "task_id": task_id.strip(),
            "workshop_process_id": workshop_process_id.strip(),
            "import_batch_id": import_batch_id.strip(),
            "notes": notes.strip(),
            "return_url": clean_return_url,
        }
        return RedirectResponse(f"{new_document_form_path}?{urlencode({k: v for k, v in params.items() if v})}", status_code=303)

    uploaded_original_name = Path(document_file.filename).name if document_file and document_file.filename else ""
    clean_title = title.strip() or sanitize_archive_component(Path(uploaded_original_name).stem, "Documento")
    clean_original_url = url_original.strip()
    clean_archive_url = url_archive.strip()
    if not clean_title:
        return document_error_redirect("Indica um título.")
    if not clean_original_url and not clean_archive_url and not uploaded_original_name:
        return document_error_redirect("Indica pelo menos um link/caminho ou anexa um ficheiro.")
    if classification not in DOCUMENT_AREA_LABELS:
        classification = "workshop"
    document_type = normalize_document_type_for_area(document_type, classification)
    if status not in DOCUMENT_STATUS_LABELS:
        status = "received"

    parsed_document_date = parse_optional_date(document_date)
    clean_plate = plate.strip().upper()
    archived = status == "archived"

    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)

        linked_vehicle_id = None
        parsed_vehicle_id = parse_optional_int(vehicle_id)
        vehicle = db.get(Vehicle, parsed_vehicle_id) if parsed_vehicle_id else None
        if not vehicle and clean_plate:
            vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == clean_plate))
        if vehicle:
            linked_vehicle_id = vehicle.id
            clean_plate = clean_plate or (vehicle.plate or "")
        parsed_task_id = parse_optional_int(task_id)
        if parsed_task_id and not db.get(Task, parsed_task_id):
            parsed_task_id = None
        parsed_workshop_process_id = parse_optional_int(workshop_process_id)
        linked_process = db.get(WorkshopProcess, parsed_workshop_process_id) if parsed_workshop_process_id else None
        if parsed_workshop_process_id and not linked_process:
            parsed_workshop_process_id = None
        process_folder_ref = linked_process.document_folder_path.split("/")[-1] if linked_process and linked_process.document_folder_path else None
        folder_path = suggest_document_folder_path(
            classification,
            parsed_document_date,
            clean_plate,
            document_type,
            supplier_name,
            customer_name,
            vin=vehicle.vin if vehicle else None,
            workshop_process_ref=process_folder_ref,
        )
        storage_provider = "sharepoint"
        storage_path = clean_original_url or clean_archive_url
        storage_key = clean_original_url or None
        external_url = clean_archive_url or clean_original_url
        original_name = clean_title[:255]
        file_name = clean_title[:255]
        file_type = None
        file_size = None
        file_hash = None

        if uploaded_original_name:
            content = document_file.file.read()
            if not content and not clean_original_url and not clean_archive_url:
                return document_error_redirect("O ficheiro anexado está vazio.")
            if content:
                suffix = Path(uploaded_original_name).suffix or ".bin"
                digest = hashlib.sha256(content).hexdigest()
                stem = sanitize_archive_component(Path(uploaded_original_name).stem or clean_title, "documento")
                storage_dir = local_document_storage_folder(
                    folder_path,
                    plate=clean_plate or (vehicle.plate if vehicle else None),
                    vin=vehicle.vin if vehicle else None,
                )
                storage_dir.mkdir(parents=True, exist_ok=True)
                file_name = f"{stem}_{digest[:12]}{suffix.lower()}"
                stored_path = storage_dir / file_name
                if not stored_path.exists():
                    stored_path.write_bytes(content)
                storage_provider = "local"
                storage_path = str(stored_path)
                storage_key = digest
                external_url = clean_archive_url or None
                original_name = uploaded_original_name[:255]
                file_type = suffix.lstrip(".").lower() or None
                file_size = len(content)
                file_hash = digest

        document = Document(
            title=clean_title,
            document_type=document_type,
            classification=classification,
            status=status,
            source=source.strip() or None,
            entry_channel=entry_channel.strip() or None,
            source_sender=source_sender.strip() or None,
            source_subject=source_subject.strip() or None,
            original_name=original_name,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            storage_provider=storage_provider,
            storage_path=storage_path,
            storage_key=storage_key,
            external_url=external_url,
            file_hash=file_hash,
            folder_path=folder_path,
            vehicle_id=linked_vehicle_id,
            task_id=parsed_task_id,
            workshop_process_id=parsed_workshop_process_id,
            plate=clean_plate or None,
            customer_name=customer_name.strip() or None,
            supplier_name=supplier_name.strip() or None,
            document_date=parsed_document_date,
            uploaded_by_id=user_id,
            archived_by_id=user_id if archived else None,
            archived_at=datetime.now(UTC) if archived else None,
            archived=archived,
        )
        db.add(document)
        db.flush()
        if import_batch_id.strip():
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="linked.import_batch",
                    old_value=None,
                    new_value=import_batch_id.strip(),
                    user_id=user_id,
                )
            )
        if notes.strip():
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="note",
                    old_value=None,
                    new_value=notes.strip(),
                    user_id=user_id,
                )
            )
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="created",
                old_value=None,
                new_value=f"Documento criado em {DOCUMENT_AREA_LABELS[classification]}",
                user_id=user_id,
            )
        )
        record_audit(
            db,
            action="document.created",
            entity_type="document",
            entity_id=document.id,
            detail=f"Documento registado: {document.title}",
            after_json={
                "classification": classification,
                "document_type": document_type,
                "status": status,
                "folder_path": folder_path,
                "storage_provider": storage_provider,
            },
            user_id=user_id,
        )
        db.commit()

    if clean_return_url:
        separator = "&" if "?" in clean_return_url else "?"
        return RedirectResponse(f"{clean_return_url}{separator}document_created=1", status_code=303)
    return RedirectResponse("/documents/manage?created=1", status_code=303)


@web_router.get("/documents/{document_id}", response_class=HTMLResponse)
def document_detail(request: Request, document_id: int, updated: str | None = None):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        document = db.get(Document, document_id)
        if not user or not document:
            return RedirectResponse("/documents", status_code=303)
        events = db.scalars(
            select(DocumentEvent)
            .where(DocumentEvent.document_id == document.id)
            .order_by(DocumentEvent.id.desc())
        ).all()
        linked_email_intake = db.scalar(
            select(EmailIntake)
            .where(
                EmailIntake.target_entity_type == "document",
                EmailIntake.target_entity_id == str(document.id),
            )
            .order_by(EmailIntake.id.desc())
        )
        attachments_statement = select(EmailIntakeAttachment).where(EmailIntakeAttachment.document_id == document.id)
        if linked_email_intake:
            attachments_statement = select(EmailIntakeAttachment).where(
                or_(
                    EmailIntakeAttachment.document_id == document.id,
                    EmailIntakeAttachment.email_intake_id == linked_email_intake.id,
                )
            )
        attachments = db.scalars(attachments_statement.order_by(EmailIntakeAttachment.id.asc())).all()
        return templates.TemplateResponse(
            request,
            "document_detail.html",
            {
                "user": user,
                "can_manage_document_links": can_manage_admin(db, user),
                "document": document,
                "events": events,
                "linked_email_intake": linked_email_intake,
                "attachments": attachments,
                "attachment_statuses": DOCUMENT_ATTACHMENT_STATUSES,
                "attachment_status_labels": DOCUMENT_ATTACHMENT_STATUS_LABELS,
                "areas": DOCUMENT_AREAS,
                "area_labels": DOCUMENT_AREA_LABELS,
                "document_types": DOCUMENT_TYPES,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "document_type_areas": DOCUMENT_TYPE_AREAS,
                "statuses": DOCUMENT_STATUSES,
                "status_labels": DOCUMENT_STATUS_LABELS,
                "sources": DOCUMENT_SOURCES,
                "updated": updated,
            },
        )


@web_router.get("/documents/{document_id}/email-original", response_class=HTMLResponse)
def document_email_original(request: Request, document_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        document = db.get(Document, document_id)
        intake = db.scalar(
            select(EmailIntake)
            .where(
                EmailIntake.target_entity_type == "document",
                EmailIntake.target_entity_id == str(document_id),
            )
            .order_by(EmailIntake.id.desc())
        )
        if not user or not document or not intake:
            return RedirectResponse(f"/documents/{document_id}", status_code=303)
        payload = intake.payload_json or {}
        original_body = payload.get("body_preview") or intake.body_preview or ""
        return templates.TemplateResponse(
            request,
            "email_original.html",
            {
                "user": user,
                "can_manage_document_links": can_manage_admin(db, user),
                "record": None,
                "document": document,
                "intake": intake,
                "original_body": original_body,
                "return_url": f"/documents/{document.id}",
                "breadcrumb_label": f"Documento #{document.id}",
                "active_menu": "documents",
            },
        )


@web_router.post("/documents/{document_id}/attachments/{attachment_id}/update", response_class=HTMLResponse)
def document_attachment_update(
    request: Request,
    document_id: int,
    attachment_id: int,
    status: str = Form("pending"),
    archive_url: str = Form(""),
    archive_folder_path: str = Form(""),
    decision_note: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        document = db.get(Document, document_id)
        attachment = db.get(EmailIntakeAttachment, attachment_id)
        if not document or not attachment or attachment.document_id != document.id:
            return RedirectResponse(f"/documents/{document_id}", status_code=303)

        clean_status = status if status in DOCUMENT_ATTACHMENT_STATUS_LABELS else "pending"
        changes = []
        if clean_status != attachment.status:
            changes.append(f"Estado: {DOCUMENT_ATTACHMENT_STATUS_LABELS.get(attachment.status, attachment.status)} -> {DOCUMENT_ATTACHMENT_STATUS_LABELS.get(clean_status, clean_status)}")
            attachment.status = clean_status
        clean_archive_url = archive_url.strip()
        if clean_archive_url != (attachment.archive_url or ""):
            changes.append("Link arquivado atualizado.")
            attachment.archive_url = clean_archive_url or None
        clean_folder = archive_folder_path.strip()
        if clean_folder != (attachment.archive_folder_path or ""):
            changes.append("Destino de arquivo atualizado.")
            attachment.archive_folder_path = clean_folder or None
        clean_note = decision_note.strip()
        if clean_note:
            changes.append(f"Nota: {clean_note}")
            attachment.decision_note = clean_note

        if changes:
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="attachment.updated",
                    old_value=attachment.name,
                    new_value="; ".join(changes),
                    user_id=user_id,
                )
            )
            record_audit(
                db,
                action="document.attachment.updated",
                entity_type="document",
                entity_id=document.id,
                detail=f"Anexo tratado: {attachment.name}",
                after_json={"attachment_id": attachment.id, "status": attachment.status},
                user_id=user_id,
            )
        db.commit()
    return RedirectResponse(f"/documents/{document_id}?updated=1", status_code=303)


@web_router.post("/documents/{document_id}/update", response_class=HTMLResponse)
def document_update(
    request: Request,
    document_id: int,
    classification: str = Form(""),
    document_type: str = Form(""),
    status: str = Form(""),
    url_archive: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        document = db.get(Document, document_id)
        if not document:
            return RedirectResponse("/documents", status_code=303)
        vehicle = db.get(Vehicle, document.vehicle_id) if document.vehicle_id else None
        linked_process = db.get(WorkshopProcess, document.workshop_process_id) if document.workshop_process_id else None

        changes = []
        if classification in DOCUMENT_AREA_LABELS and classification != document.classification:
            changes.append(("classification", document.classification, classification))
            document.classification = classification
        clean_document_type = normalize_document_type_for_area(document_type, document.classification or "workshop")
        if clean_document_type != document.document_type:
            changes.append(("document_type", document.document_type, clean_document_type))
            document.document_type = clean_document_type
        if status in DOCUMENT_STATUS_LABELS and status != document.status:
            changes.append(("status", document.status, status))
            document.status = status
        clean_archive_url = url_archive.strip()
        if clean_archive_url and clean_archive_url != document.external_url:
            changes.append(("url_archive", document.external_url, clean_archive_url))
            document.external_url = clean_archive_url
        document.folder_path = suggest_document_folder_path(
            document.classification or "general_archive",
            document.document_date,
            document.plate,
            document.document_type,
            document.supplier_name,
            document.customer_name,
            vin=vehicle.vin if vehicle else None,
            workshop_process_ref=linked_process.document_folder_path.split("/")[-1] if linked_process and linked_process.document_folder_path else None,
        )
        if document.status == "archived":
            document.archived = True
            document.archived_by_id = user_id
            document.archived_at = document.archived_at or datetime.now(UTC)
        else:
            document.archived = False

        for field, old_value, new_value in changes:
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action=f"updated.{field}",
                    old_value=str(old_value or ""),
                    new_value=str(new_value or ""),
                    user_id=user_id,
                )
            )
        if notes.strip():
            db.add(
                DocumentEvent(
                    document_id=document.id,
                    action="note",
                    old_value=None,
                    new_value=notes.strip(),
                    user_id=user_id,
                )
            )
        if changes or notes.strip():
            record_audit(
                db,
                action="document.updated",
                entity_type="document",
                entity_id=document.id,
                detail=f"Documento atualizado: {document.title}",
                after_json={"changes": [field for field, _, _ in changes]},
                user_id=user_id,
            )
        db.commit()
    return RedirectResponse(f"/documents/{document_id}?updated=1", status_code=303)


@web_router.get("/task-board", response_class=HTMLResponse)
def task_center(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        today = date.today()
        workspace_metrics = {}
        authorized_workspaces = [
            workspace_code
            for workspace_code in TASK_WORKSPACE_CONFIG
            if user_can_access_task_workspace(db, current_user, workspace_code)
        ]
        if not authorized_workspaces:
            return RedirectResponse("/", status_code=303)
        for workspace_code, workspace_config in TASK_WORKSPACE_CONFIG.items():
            if workspace_code not in authorized_workspaces:
                continue
            workspace_task_filter = Task.task_type.in_(tuple(TASK_WORKSPACE_TASK_TYPES[workspace_code]))
            Subtask = aliased(Task)
            subtask_parent_ids = select(Subtask.parent_task_id).where(Subtask.parent_task_id.is_not(None)).distinct()
            open_count = db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.parent_task_id.is_(None),
                )
            ) or 0
            open_simple_count = db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.parent_task_id.is_(None),
                    ~Task.id.in_(subtask_parent_ids),
                )
            ) or 0
            open_parent_count = db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.parent_task_id.is_(None),
                    Task.id.in_(subtask_parent_ids),
                )
            ) or 0
            open_subtask_count = db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.parent_task_id.is_not(None),
                )
            ) or 0
            due_today = db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.parent_task_id.is_(None),
                    Task.due_on == today,
                )
            ) or 0
            quick_open_count = db.scalar(
                select(func.count()).select_from(QuickRecord).where(
                    QuickRecord.workspace == workspace_code,
                    QuickRecord.closed_at.is_(None),
                    ~QuickRecord.status.in_(QUICK_RECORD_ARCHIVE_STATUSES),
                )
            ) or 0
            workspace_metrics[workspace_code] = {
                "open": open_count,
                "open_simple": open_simple_count,
                "open_parent": open_parent_count,
                "open_subtasks": open_subtask_count,
                "due_today": due_today,
                "quick_open": quick_open_count,
                "config": workspace_config,
                "manage_url": task_workspace_manage_url(workspace_code),
            }
        return templates.TemplateResponse(
            request,
            "task_center.html",
            {
                "workspace_metrics": workspace_metrics,
                "authorized_workspaces": authorized_workspaces,
                "current_user": current_user,
            },
        )


@web_router.get("/task-board/manage", response_class=HTMLResponse)
@web_router.get("/task-board/{workspace}/manage", response_class=HTMLResponse)
def task_board_manage(
    request: Request,
    workspace: str = "operational",
    created: str | None = None,
    closed: str | None = None,
    quick_created: str | None = None,
    feedback_saved: str | None = None,
    q: str = "",
    status: str = "",
    task_type: str = "",
    category: str = "",
    source: str = "",
    assigned_to_id: str = "",
    team_id: str = "",
    station: str = "",
    view: str = "",
    content: str = "tasks",
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    current_workspace = normalize_task_workspace(workspace)
    workspace_config = TASK_WORKSPACE_CONFIG[current_workspace]
    content_mode = content if content in {"tasks", "quick", "all"} else "tasks"
    workspace_task_codes = set(TASK_WORKSPACE_TASK_TYPES[current_workspace])
    workspace_primary_task_codes = set(workspace_config["primary_task_types"])
    workspace_secondary_task_codes = set(workspace_config["secondary_task_types"])
    manage_url = task_workspace_manage_url(current_workspace)

    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, current_workspace):
            return RedirectResponse("/task-board", status_code=303)
        can_write_workspace = user_can_access_task_workspace(db, current_user, current_workspace, write=True)
        today = date.today()
        today_start = datetime(today.year, today.month, today.day, tzinfo=UTC)
        tomorrow_start = datetime.fromtimestamp(today_start.timestamp() + 86400, UTC)
        archived_condition = (Task.closed_at.is_not(None)) | (Task.status.in_(TASK_ARCHIVE_STATUSES))
        workspace_task_filter = Task.task_type.in_(tuple(workspace_task_codes))
        parent_task_filter = Task.parent_task_id.is_(None)
        subtask_filter = Task.parent_task_id.is_not(None)
        active_task_filter = (
            Task.closed_at.is_(None),
            ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
        )
        Subtask = aliased(Task)
        open_subtask_parent_ids = (
            select(Subtask.parent_task_id)
            .where(
                Subtask.parent_task_id.is_not(None),
                Subtask.closed_at.is_(None),
                    ~Subtask.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
            )
            .distinct()
        )
        subtask_parent_ids = select(Subtask.parent_task_id).where(Subtask.parent_task_id.is_not(None)).distinct()
        open_stmt = select(Task).where(
            workspace_task_filter,
            *active_task_filter,
        )
        metrics = {
            "open": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    *active_task_filter,
                )
            )
            or 0,
            "open_subtasks": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    subtask_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                )
            )
            or 0,
            "open_simple": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    parent_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    ~Task.id.in_(subtask_parent_ids),
                )
            )
            or 0,
            "open_parent": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    parent_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.id.in_(subtask_parent_ids),
                )
            )
            or 0,
            "with_subtasks": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    parent_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    Task.id.in_(open_subtask_parent_ids),
                )
            )
            or 0,
            "mine": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    or_(
                        Task.assigned_to_id == user_id,
                        Task.delegated_to_user_id == user_id,
                        Task.waiting_for_user_id == user_id,
                    ),
                )
            )
            or 0,
            "urgent": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    *active_task_filter,
                    Task.priority == "urgent",
                )
            )
            or 0,
            "in_treatment": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    *active_task_filter,
                    Task.status.in_(("in_execution", "delegated")),
                )
            )
            or 0,
            "unassigned": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    *active_task_filter,
                    Task.assigned_to_id.is_(None),
                )
            )
            or 0,
            "overdue": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    *active_task_filter,
                    Task.due_on.is_not(None),
                    Task.due_on < today,
                )
            )
            or 0,
            "due_today": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    *active_task_filter,
                    Task.due_on == today,
                )
            )
            or 0,
            "closed_today": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    parent_task_filter,
                    Task.closed_at.is_not(None),
                    Task.closed_at >= today_start,
                    Task.closed_at < tomorrow_start,
                )
            )
            or 0,
            "archived": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    parent_task_filter,
                    archived_condition,
                )
            )
            or 0,
            "planned": db.scalar(
                select(func.count()).select_from(Task).where(
                    workspace_task_filter,
                    parent_task_filter,
                    Task.status.in_(TASK_PLANNED_STATUSES),
                    Task.closed_at.is_(None),
                )
            )
            or 0,
            "all": db.scalar(
                select(func.count()).select_from(Task).where(workspace_task_filter, parent_task_filter)
            )
            or 0,
            "quick_open": db.scalar(
                select(func.count()).select_from(QuickRecord).where(
                    QuickRecord.workspace == current_workspace,
                    QuickRecord.closed_at.is_(None),
                    ~QuickRecord.status.in_(QUICK_RECORD_ARCHIVE_STATUSES),
                )
            )
            or 0,
        }

        stmt = open_stmt
        if view == "archived" or status in TASK_ARCHIVE_STATUSES:
            stmt = select(Task).where(workspace_task_filter, parent_task_filter, archived_condition)
        elif view == "planned":
            stmt = select(Task).where(
                workspace_task_filter,
                parent_task_filter,
                Task.status.in_(TASK_PLANNED_STATUSES),
                Task.closed_at.is_(None),
            )
        elif view == "all":
            stmt = select(Task).where(workspace_task_filter, parent_task_filter)
        elif view == "mine":
            stmt = select(Task).where(
                workspace_task_filter,
                Task.closed_at.is_(None),
                ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                or_(
                    Task.assigned_to_id == user_id,
                    Task.delegated_to_user_id == user_id,
                    Task.waiting_for_user_id == user_id,
                )
            )
        elif view == "team":
            stmt = stmt.where(Task.team_id.is_not(None))
        elif view == "urgent":
            stmt = stmt.where(Task.priority == "urgent")
        elif view == "unassigned":
            stmt = stmt.where(Task.assigned_to_id.is_(None))
        elif view == "overdue":
            stmt = stmt.where(Task.due_on.is_not(None), Task.due_on < today)
        elif view == "due_today":
            stmt = stmt.where(Task.due_on == today)
        elif view == "simple":
            stmt = stmt.where(~Task.id.in_(subtask_parent_ids))
        elif view == "parents":
            stmt = stmt.where(Task.id.in_(subtask_parent_ids))
        elif view == "with_subtasks":
            stmt = stmt.where(Task.id.in_(open_subtask_parent_ids))
        elif view == "subtasks":
            stmt = select(Task).where(
                workspace_task_filter,
                subtask_filter,
                Task.closed_at.is_(None),
                ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
            )

        clean_q = q.strip()
        if clean_q:
            like_q = f"%{clean_q}%"
            normalized_plate = clean_q.upper().replace(" ", "")
            matching_subtask_parent_ids = select(Subtask.parent_task_id).where(
                Subtask.parent_task_id.is_not(None),
                (
                    (Subtask.title.ilike(like_q))
                    | (Subtask.description.ilike(like_q))
                    | (Subtask.customer_name.ilike(like_q))
                    | (Subtask.customer_email.ilike(like_q))
                    | (Subtask.customer_phone.ilike(like_q))
                    | (Subtask.plate == normalized_plate)
                    | (Subtask.reservation_number.ilike(like_q))
                    | (Subtask.contract_number.ilike(like_q))
                    | (Subtask.external_source_id.ilike(like_q))
                ),
            )
            stmt = stmt.where(
                (Task.title.ilike(like_q))
                | (Task.description.ilike(like_q))
                | (Task.customer_name.ilike(like_q))
                | (Task.customer_email.ilike(like_q))
                | (Task.customer_phone.ilike(like_q))
                | (Task.plate == normalized_plate)
                | (Task.reservation_number.ilike(like_q))
                | (Task.contract_number.ilike(like_q))
                | (Task.external_source_id.ilike(like_q))
                | (Task.id.in_(matching_subtask_parent_ids))
            )
        if status:
            stmt = stmt.where(Task.status == status)
        if task_type:
            matching_task_types = [task_type, *TASK_TYPE_LEGACY_BY_CANONICAL.get(task_type, [])]
            stmt = stmt.where(Task.task_type.in_(matching_task_types))
        if category:
            stmt = stmt.where(Task.category == category)
        if source:
            stmt = stmt.where(Task.source == source)
        parsed_assigned_to_id = parse_optional_int(assigned_to_id)
        if parsed_assigned_to_id:
            stmt = stmt.where(Task.assigned_to_id == parsed_assigned_to_id)
        parsed_team_id = parse_optional_int(team_id)
        if parsed_team_id:
            stmt = stmt.where(Task.team_id == parsed_team_id)
        if station.strip():
            stmt = stmt.where(Task.station.ilike(f"%{station.strip()}%"))

        if view == "archived":
            category_count_conditions = [workspace_task_filter, parent_task_filter, archived_condition]
        elif view == "planned":
            category_count_conditions = [
                workspace_task_filter,
                parent_task_filter,
                Task.status.in_(TASK_PLANNED_STATUSES),
                Task.closed_at.is_(None),
            ]
        elif view == "all":
            category_count_conditions = [workspace_task_filter, parent_task_filter]
        else:
            category_count_conditions = [
                workspace_task_filter,
                *active_task_filter,
            ]

        if view == "mine":
            category_count_conditions.append(
                or_(
                    Task.assigned_to_id == user_id,
                    Task.delegated_to_user_id == user_id,
                    Task.waiting_for_user_id == user_id,
                )
            )
        elif view == "with_subtasks":
            category_count_conditions.extend([parent_task_filter, Task.id.in_(open_subtask_parent_ids)])
        elif view == "subtasks":
            category_count_conditions.append(subtask_filter)
        elif view not in {"all", "archived", "planned"}:
            if view == "urgent":
                category_count_conditions.append(Task.priority == "urgent")
            elif view == "unassigned":
                category_count_conditions.append(Task.assigned_to_id.is_(None))
            elif view == "overdue":
                category_count_conditions.extend([Task.due_on.is_not(None), Task.due_on < today])
            elif view == "due_today":
                category_count_conditions.append(Task.due_on == today)

        category_counts = {
            "all": db.scalar(select(func.count()).select_from(Task).where(*category_count_conditions)) or 0
        }
        for category_code, _ in TASK_CATEGORIES:
            category_counts[category_code] = (
                db.scalar(
                    select(func.count())
                    .select_from(Task)
                    .where(*category_count_conditions, Task.category == category_code)
                )
                or 0
            )

        quick_archived_condition = (
            (QuickRecord.closed_at.is_not(None))
            | (QuickRecord.status.in_(QUICK_RECORD_ARCHIVE_STATUSES))
        )
        quick_stmt = select(QuickRecord).where(QuickRecord.workspace == current_workspace)
        if view == "archived":
            quick_stmt = quick_stmt.where(quick_archived_condition)
        elif view == "all":
            quick_stmt = quick_stmt
        else:
            quick_stmt = quick_stmt.where(~quick_archived_condition)
        if clean_q:
            like_q = f"%{clean_q}%"
            normalized_plate = clean_q.upper().replace(" ", "")
            quick_stmt = quick_stmt.where(
                (QuickRecord.title.ilike(like_q))
                | (QuickRecord.description.ilike(like_q))
                | (QuickRecord.customer_name.ilike(like_q))
                | (QuickRecord.customer_email.ilike(like_q))
                | (QuickRecord.customer_phone.ilike(like_q))
                | (QuickRecord.plate == normalized_plate)
            )
        if status and status in QUICK_RECORD_STATUS_LABELS:
            quick_stmt = quick_stmt.where(QuickRecord.status == status)
        if source:
            quick_stmt = quick_stmt.where(QuickRecord.source == source)
        if station.strip():
            quick_stmt = quick_stmt.where(QuickRecord.station.ilike(f"%{station.strip()}%"))

        raw_tasks = db.scalars(
            stmt.order_by(
                Task.id.desc(),
                Task.created_at.desc(),
            ).limit(100)
        ).all()
        task_result_count = len(raw_tasks)
        task_ids = [task.id for task in raw_tasks]
        subtask_counts_by_parent = {}
        parent_tasks_by_id = {}
        parent_task_ids = sorted({task.parent_task_id for task in raw_tasks if task.parent_task_id})
        if parent_task_ids:
            parent_tasks_by_id = {
                task.id: task
                for task in db.scalars(select(Task).where(Task.id.in_(parent_task_ids))).all()
            }
        task_ids_for_subtask_counts = sorted(set(task_ids) | set(parent_task_ids))
        if task_ids_for_subtask_counts:
            subtask_counts_by_parent = {
                parent_id: count
                for parent_id, count in db.execute(
                    select(Task.parent_task_id, func.count())
                    .where(
                        Task.parent_task_id.in_(task_ids_for_subtask_counts),
                        Task.closed_at.is_(None),
                        ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                    )
                    .group_by(Task.parent_task_id)
                ).all()
                if parent_id is not None
            }
        tasks_by_id = {task.id: task for task in raw_tasks}
        child_tasks_by_parent = {}
        for task in raw_tasks:
            if task.parent_task_id:
                child_tasks_by_parent.setdefault(task.parent_task_id, []).append(task)
        tasks = []
        used_task_ids_for_order = set()

        def append_task_with_children(task: Task | None) -> None:
            if task is None or task.id in used_task_ids_for_order:
                return
            tasks.append(task)
            used_task_ids_for_order.add(task.id)
            if not task.parent_task_id:
                for child_task in child_tasks_by_parent.get(task.id, []):
                    append_task_with_children(child_task)

        for task in raw_tasks:
            if task.id in used_task_ids_for_order:
                continue
            if task.parent_task_id:
                parent_task = tasks_by_id.get(task.parent_task_id) or parent_tasks_by_id.get(task.parent_task_id)
                if parent_task:
                    append_task_with_children(parent_task)
                append_task_with_children(task)
            else:
                append_task_with_children(task)
        task_ids = [task.id for task in tasks]
        quick_records = db.scalars(
            quick_stmt.order_by(QuickRecord.created_at.desc(), QuickRecord.id.desc()).limit(100)
        ).all()
        grouped_tasks = []
        used_task_ids = set()
        canonical_task_type_filter = TASK_TYPE_CANONICAL_GROUP.get(task_type, task_type)
        workspace_task_options = workspace_task_type_options(current_workspace)
        for type_code, type_label in workspace_task_options:
            group_items = [
                task
                for task in tasks
                if TASK_TYPE_CANONICAL_GROUP.get(task.task_type or "task", task.task_type or "task")
                == type_code
            ]
            should_show_group = (
                bool(group_items)
                or canonical_task_type_filter == type_code
                or (current_workspace != "operational" and type_code in workspace_primary_task_codes)
                or (current_workspace == "workshop" and type_code in workspace_secondary_task_codes)
            )
            if should_show_group:
                grouped_tasks.append(
                    {
                        "code": type_code,
                        "label": TASK_BOARD_TYPE_LABELS.get(type_code, type_label),
                        "tasks": group_items,
                        "count": len(group_items),
                        "section": "secondary" if type_code in workspace_secondary_task_codes else "primary",
                    }
                )
                used_task_ids.update(task.id for task in group_items)
        other_tasks = [task for task in tasks if task.id not in used_task_ids]
        if other_tasks:
            grouped_tasks.append(
                {
                    "code": "other",
                    "label": "Outras",
                    "tasks": other_tasks,
                    "count": len(other_tasks),
                    "section": "primary",
                }
            )
        primary_task_groups = [group for group in grouped_tasks if group["section"] == "primary"]
        secondary_task_groups = [group for group in grouped_tasks if group["section"] == "secondary"]
        quick_record_groups = []
        workspace_record_types = QUICK_RECORD_TYPES_BY_WORKSPACE[current_workspace]
        workspace_record_type_codes = {code for code, _ in workspace_record_types}
        for type_code, type_label in workspace_record_types:
            group_items = [record for record in quick_records if (record.record_type or "other") == type_code]
            if group_items:
                quick_record_groups.append(
                    {
                        "code": type_code,
                        "label": type_label,
                        "records": group_items,
                        "count": len(group_items),
                    }
                )
        other_quick_records = [
            record
            for record in quick_records
            if (record.record_type or "other") not in workspace_record_type_codes
        ]
        if other_quick_records:
            quick_record_groups.append(
                {
                    "code": "other",
                    "label": "Outro",
                    "records": other_quick_records,
                    "count": len(other_quick_records),
                }
            )
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
        user_by_id = {item.id: item for item in users}
        assignable_users = assignable_users_for_workspace(users, current_workspace)
        teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        team_by_id = {item.id: item for item in teams}
        stations = [
            item
            for item in db.scalars(
                select(Task.station)
                .where(Task.station.is_not(None), Task.station != "")
                .distinct()
                .order_by(Task.station)
                .limit(100)
            ).all()
            if item
        ]
        return templates.TemplateResponse(
            request,
            "tasks.html",
            {
                "tasks": tasks,
                "task_result_count": task_result_count,
                "subtask_counts_by_parent": subtask_counts_by_parent,
                "parent_tasks_by_id": parent_tasks_by_id,
                "quick_records": quick_records,
                "task_groups": primary_task_groups,
                "secondary_task_groups": secondary_task_groups,
                "workspace": current_workspace,
                "workspace_config": workspace_config,
                "workspace_label": workspace_config["label"],
                "manage_url": manage_url,
                "new_task_url": task_workspace_new_url(current_workspace, "task"),
                "new_quick_url": task_workspace_new_url(current_workspace, "quick"),
                "users": users,
                "assignable_users": assignable_users,
                "current_user": user_by_id.get(user_id),
                "can_write_workspace": can_write_workspace,
                "user_by_id": user_by_id,
                "teams": teams,
                "team_by_id": team_by_id,
                "created": created,
                "closed": closed,
                "quick_created": quick_created,
                "feedback_saved": feedback_saved,
                "error": None,
                "metrics": metrics,
                "category_counts": category_counts,
                "filters": {
                    "q": q,
                    "status": status,
                    "task_type": task_type,
                    "category": category,
                    "source": source,
                    "assigned_to_id": assigned_to_id,
                    "team_id": team_id,
                    "station": station,
                    "view": view,
                    "content": content_mode,
                },
                "archive_statuses": TASK_ARCHIVE_STATUSES,
                "quick_record_groups": quick_record_groups,
                "quick_record_statuses": QUICK_RECORD_STATUSES,
                "quick_record_status_labels": QUICK_RECORD_STATUS_LABELS,
                "quick_record_type_labels": QUICK_RECORD_TYPE_LABELS,
                "stations": stations,
                "task_statuses": TASK_STATUSES,
                "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                "priorities": PRIORITIES,
                "priority_labels": PRIORITY_DISPLAY_LABELS,
                "task_types": workspace_task_options,
                "task_type_labels": TASK_TYPE_LABELS,
                "task_sources": TASK_SOURCES,
                "task_source_labels": TASK_SOURCE_DISPLAY_LABELS,
                "task_categories": TASK_CATEGORIES,
                "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
                "task_subcategories_by_category": TASK_SUBCATEGORIES_BY_CATEGORY,
                "task_subcategory_labels": TASK_SUBCATEGORY_DISPLAY_LABELS,
            },
        )


@web_router.get("/task-board/new", response_class=HTMLResponse)
def task_new_form(
    request: Request,
    error: str | None = None,
    mode: str = "task",
    workspace: str = "operational",
    parent_task_id: str = "",
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    current_workspace = normalize_task_workspace(workspace)
    workspace_config = TASK_WORKSPACE_CONFIG[current_workspace]
    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        parent_task = db.get(Task, parse_optional_int(parent_task_id)) if parse_optional_int(parent_task_id) else None
        if parent_task:
            current_workspace = workspace_for_task_type(parent_task.task_type)
            workspace_config = TASK_WORKSPACE_CONFIG[current_workspace]
        if not user_can_access_task_workspace(db, current_user, current_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
        assignable_users = assignable_users_for_workspace(users, current_workspace)
        teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "users": users,
                "assignable_users": assignable_users,
                "current_user": current_user,
                "teams": teams,
                "error": "Este utilizador só pode ser responsável ou delegado em tarefas de Administração." if error == "assignment_not_allowed" else None,
                "form_mode": "quick" if mode == "quick" else "task",
                "workspace": current_workspace,
                "workspace_config": workspace_config,
                "workspace_label": workspace_config["label"],
                "manage_url": task_workspace_manage_url(current_workspace),
                "form_values": {
                    "task_type": workspace_config["default_task_type"],
                    "record_type": QUICK_RECORD_TYPES_BY_WORKSPACE[current_workspace][0][0],
                    "category": parent_task.category if parent_task else workspace_config["default_category"],
                    "subcategory": parent_task.subcategory
                    if parent_task
                    else default_task_subcategory(workspace_config["default_category"]),
                    "parent_task_id": parent_task.id if parent_task else "",
                    "priority": parent_task.priority if parent_task else "normal",
                    "plate": parent_task.plate if parent_task else "",
                    "station": parent_task.station if parent_task else "",
                    "customer_name": parent_task.customer_name if parent_task else "",
                    "customer_contact": parent_task.customer_contact if parent_task else "",
                    "customer_email": parent_task.customer_email if parent_task else "",
                    "customer_phone": parent_task.customer_phone if parent_task else "",
                    "reservation_number": parent_task.reservation_number if parent_task else "",
                    "contract_number": parent_task.contract_number if parent_task else "",
                },
                "parent_task": parent_task,
                "duplicate_tasks": [],
                "task_types": workspace_task_type_options(current_workspace),
                "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE[current_workspace],
                "workspaces": TASK_WORKSPACES,
                "task_sources": TASK_SOURCES,
                "task_categories": TASK_CATEGORIES,
                "task_subcategories_by_category": TASK_SUBCATEGORIES_BY_CATEGORY,
                "task_subcategory_labels": TASK_SUBCATEGORY_DISPLAY_LABELS,
                "priorities": PRIORITIES,
                "delegation_value": "",
                "guided_flow_options": guided_flow_options_for_workspace(current_workspace),
                "can_create_recurring": user_can_create_recurring_tasks(db, current_user),
                "recurrence_rules": RECURRENCE_RULES,
            },
        )


@web_router.get("/task-board/vehicle-search")
def task_vehicle_search(request: Request):
    if not get_web_user_id(request):
        return JSONResponse({"items": []}, status_code=401)

    raw_query = (request.query_params.get("q") or "").strip()
    query = raw_query.upper().replace(" ", "")
    context = (request.query_params.get("context") or "").strip().lower()
    with SessionLocal() as db:
        statement = select(Vehicle).where(Vehicle.plate.is_not(None), Vehicle.plate != "")
        if context == "workshop":
            statement = statement.where(
                or_(
                    Vehicle.lifecycle_status.is_(None),
                    ~func.lower(Vehicle.lifecycle_status).in_(WORKSHOP_BLOCKED_VEHICLE_STATUSES),
                ),
                or_(
                    Vehicle.operational_status.is_(None),
                    ~func.lower(Vehicle.operational_status).in_(WORKSHOP_BLOCKED_VEHICLE_STATUSES),
                ),
            )
        if query:
            statement = statement.where(
                or_(
                    Vehicle.plate.ilike(f"{query}%"),
                    Vehicle.vin.ilike(f"{query}%"),
                    Vehicle.rentway_unit_nr.ilike(f"{query}%"),
                    Vehicle.brand.ilike(f"%{raw_query}%"),
                    Vehicle.model.ilike(f"%{raw_query}%"),
                )
            )
        vehicles = db.scalars(statement.order_by(Vehicle.plate).limit(12)).all()
        workshop_contexts: dict[int, dict[str, object]] = {}
        if context == "workshop":
            workshop_contexts = {
                vehicle.id: clean_workshop_vehicle_context(db, vehicle_id=vehicle.id)
                for vehicle in vehicles
            }
        return {
            "items": [
                {
                    "id": vehicle.id,
                    "plate": vehicle.plate,
                    "brand": vehicle.brand,
                    "model": vehicle.model,
                    "version": vehicle.version,
                    "vin": vehicle.vin,
                    "rentway_unit_nr": vehicle.rentway_unit_nr,
                    "lifecycle_status": vehicle.lifecycle_status,
                    "operational_status": vehicle.operational_status,
                    "workshop_context": workshop_contexts.get(vehicle.id, {}),
                    "label": " · ".join(
                        item
                        for item in [
                            vehicle.plate or "",
                            f"Unit {vehicle.rentway_unit_nr}" if vehicle.rentway_unit_nr else "",
                            " ".join(
                                part for part in [vehicle.brand, vehicle.model] if part
                            ).strip(),
                        ]
                        if item
                    ),
                }
                for vehicle in vehicles
                if vehicle.plate
            ]
        }


@web_router.post("/task-board/quick/new", response_class=HTMLResponse)
def quick_record_create(
    request: Request,
    title: str = Form(...),
    record_type: str = Form("request"),
    workspace: str = Form("operational"),
    source: str = Form("manual"),
    priority: str = Form("normal"),
    customer_name: str = Form(""),
    customer_contact: str = Form(""),
    customer_email: str = Form(""),
    customer_phone: str = Form(""),
    plate: str = Form(""),
    station: str = Form(""),
    description: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_workspace = normalize_task_workspace(workspace)
    with SessionLocal() as db:
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, clean_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
    allowed_record_types = {code for code, _ in QUICK_RECORD_TYPES_BY_WORKSPACE.get(clean_workspace, [])}
    if record_type not in allowed_record_types:
        record_type = "other"
    if source not in TASK_SOURCE_DISPLAY_LABELS:
        source = "manual"
    if priority not in PRIORITY_DISPLAY_LABELS:
        priority = "normal"
    clean_title = title.strip()
    clean_plate = plate.strip().upper().replace(" ", "")
    form_values = {
        "title": clean_title,
        "description": description,
        "record_type": record_type,
        "priority": priority,
        "source": source,
        "plate": clean_plate,
        "station": station,
        "customer_name": customer_name,
        "customer_contact": customer_contact,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
    }
    if not clean_title:
        with SessionLocal() as db:
            current_user = db.get(User, user_id)
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            assignable_users = assignable_users_for_workspace(users, clean_workspace)
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "users": users,
                "assignable_users": assignable_users,
                "current_user": current_user,
                "teams": teams,
                "error": "Indica um assunto para o registo rápido.",
                "form_mode": "quick",
                "workspace": clean_workspace,
                "workspace_config": TASK_WORKSPACE_CONFIG[clean_workspace],
                "workspace_label": TASK_WORKSPACE_LABELS[clean_workspace],
                "manage_url": task_workspace_manage_url(clean_workspace),
                "form_values": form_values,
                "parent_task": None,
                "duplicate_tasks": [],
                "task_sources": TASK_SOURCES,
                "task_types": TASK_TYPES,
                "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE.get(clean_workspace, []),
                "workspaces": TASK_WORKSPACES,
                "task_categories": TASK_CATEGORIES,
                "task_subcategories_by_category": TASK_SUBCATEGORIES_BY_CATEGORY,
                "task_subcategory_labels": TASK_SUBCATEGORY_DISPLAY_LABELS,
                "priorities": PRIORITIES,
            },
            status_code=400,
        )

    with SessionLocal() as db:
        record = QuickRecord(
            workspace=clean_workspace,
            record_type=record_type,
            title=clean_title,
            description=description.strip() or None,
            status="new",
            priority=priority,
            source=source,
            customer_name=customer_name.strip() or None,
            customer_contact=customer_contact.strip() or None,
            customer_email=customer_email.strip().lower() or None,
            customer_phone=customer_phone.strip() or None,
            plate=clean_plate or None,
            station=station.strip() or None,
            created_by_id=user_id,
        )
        db.add(record)
        db.flush()
        record_audit(
            db,
            action="quick_record.create",
            entity_type="quick_record",
            entity_id=record.id,
            detail=f"Registo rápido criado: {record.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"{task_workspace_manage_url(clean_workspace)}?quick_created=1", status_code=303)


@web_router.get("/task-board/quick/{record_id}", response_class=HTMLResponse)
def quick_record_detail(
    request: Request,
    record_id: int,
    updated: str | None = None,
    closed: str | None = None,
    converted: str | None = None,
    error: str | None = None,
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        record = db.get(QuickRecord, record_id)
        if not record:
            return RedirectResponse("/task-board/manage", status_code=303)
        workspace = normalize_task_workspace(record.workspace)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, workspace):
            return RedirectResponse("/task-board", status_code=303)
        linked_task = db.get(Task, record.converted_task_id) if record.converted_task_id else None
        linked_email_intake = None
        if record.entity_type == "email_intake" and record.entity_id:
            try:
                linked_email_intake = db.get(EmailIntake, int(record.entity_id))
            except ValueError:
                linked_email_intake = None
        linked_vehicle = None
        if record.plate:
            linked_vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == record.plate))
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
        user_by_id = {item.id: item for item in users}
        assignable_users = assignable_users_for_workspace(users, workspace)
        teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "quick_record_detail.html",
            {
                "record": record,
                "workspace": workspace,
                "workspace_config": TASK_WORKSPACE_CONFIG[workspace],
                "workspace_label": TASK_WORKSPACE_LABELS[workspace],
                "manage_url": task_workspace_manage_url(workspace),
                "linked_task": linked_task,
                "linked_email_intake": linked_email_intake,
                "linked_vehicle": linked_vehicle,
                "can_write_workspace": user_can_access_task_workspace(db, current_user, workspace, write=True),
                "users": users,
                "assignable_users": assignable_users,
                "user_by_id": user_by_id,
                "teams": teams,
                "current_user": current_user,
                "updated": updated,
                "closed": closed,
                "converted": converted,
                "error": task_detail_error_message(error),
                "quick_record_statuses": QUICK_RECORD_STATUSES,
                "quick_record_status_labels": QUICK_RECORD_STATUS_LABELS,
                "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE[workspace],
                "quick_record_type_labels": QUICK_RECORD_TYPE_LABELS,
                "task_types": workspace_task_type_options(workspace),
                "task_sources": TASK_SOURCES,
                "task_source_labels": TASK_SOURCE_DISPLAY_LABELS,
                "priorities": PRIORITIES,
                "priority_labels": PRIORITY_DISPLAY_LABELS,
            },
        )


@web_router.get("/task-board/quick/{record_id}/email-original", response_class=HTMLResponse)
def quick_record_email_original(request: Request, record_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        record = db.get(QuickRecord, record_id)
        if not record or record.entity_type != "email_intake" or not record.entity_id:
            return RedirectResponse(f"/task-board/quick/{record_id}", status_code=303)
        workspace = normalize_task_workspace(record.workspace)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, workspace):
            return RedirectResponse("/task-board", status_code=303)
        try:
            intake_id = int(record.entity_id)
        except ValueError:
            return RedirectResponse(f"/task-board/quick/{record_id}", status_code=303)
        intake = db.get(EmailIntake, intake_id)
        if not intake:
            return RedirectResponse(f"/task-board/quick/{record_id}", status_code=303)
        payload = intake.payload_json or {}
        original_body = payload.get("body_preview") or intake.body_preview or ""
        return templates.TemplateResponse(
            request,
            "email_original.html",
            {
                "record": record,
                "intake": intake,
                "original_body": original_body,
                "current_user": current_user,
            },
        )


@web_router.post("/task-board/quick/{record_id}/update", response_class=HTMLResponse)
def quick_record_update(
    request: Request,
    record_id: int,
    title: str = Form(""),
    record_type: str = Form(""),
    status: str = Form(""),
    priority: str = Form(""),
    source: str = Form(""),
    customer_name: str = Form(""),
    customer_contact: str = Form(""),
    customer_email: str = Form(""),
    customer_phone: str = Form(""),
    plate: str = Form(""),
    station: str = Form(""),
    description: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        record = db.get(QuickRecord, record_id)
        if not record:
            return RedirectResponse("/task-board/manage", status_code=303)
        workspace = normalize_task_workspace(record.workspace)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        allowed_record_types = {code for code, _ in QUICK_RECORD_TYPES_BY_WORKSPACE[workspace]}
        if record_type not in allowed_record_types:
            record_type = record.record_type or "other"
        if status not in QUICK_RECORD_STATUS_LABELS:
            status = record.status or "new"
        if priority not in PRIORITY_DISPLAY_LABELS:
            priority = record.priority or "normal"
        if source not in TASK_SOURCE_DISPLAY_LABELS:
            source = record.source or "manual"

        record.title = title.strip() or record.title
        record.record_type = record_type
        record.status = status
        record.priority = priority
        record.source = source
        record.customer_name = customer_name.strip() or None
        record.customer_contact = customer_contact.strip() or None
        record.customer_email = customer_email.strip().lower() or None
        record.customer_phone = customer_phone.strip() or None
        record.plate = plate.strip().upper().replace(" ", "") or None
        record.station = station.strip() or None
        record.description = description.strip() or None
        if status in QUICK_RECORD_ARCHIVE_STATUSES:
            record.closed_at = record.closed_at or datetime.now(UTC)
        else:
            record.closed_at = None

        record_audit(
            db,
            action="quick_record.update",
            entity_type="quick_record",
            entity_id=record.id,
            detail=f"Registo rápido atualizado: {record.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/task-board/quick/{record_id}?updated=1", status_code=303)


@web_router.post("/task-board/quick/{record_id}/close", response_class=HTMLResponse)
def quick_record_close(request: Request, record_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        record = db.get(QuickRecord, record_id)
        if not record:
            return RedirectResponse("/task-board/manage", status_code=303)
        workspace = normalize_task_workspace(record.workspace)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        record.status = "closed"
        record.closed_at = record.closed_at or datetime.now(UTC)
        record_audit(
            db,
            action="quick_record.close",
            entity_type="quick_record",
            entity_id=record.id,
            detail=f"Registo rápido fechado: {record.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"{task_workspace_manage_url(workspace)}?closed=1", status_code=303)


@web_router.post("/task-board/quick/{record_id}/convert", response_class=HTMLResponse)
def quick_record_convert(
    request: Request,
    record_id: int,
    title: str = Form(""),
    description: str = Form(""),
    task_type: str = Form(""),
    priority: str = Form("normal"),
    assigned_to_id: str = Form(""),
    team_id: str = Form(""),
    delegated_to: str = Form(""),
    due_on: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        record = db.get(QuickRecord, record_id)
        if not record:
            return RedirectResponse("/task-board/manage", status_code=303)
        workspace = normalize_task_workspace(record.workspace)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        workspace_config = TASK_WORKSPACE_CONFIG[workspace]
        allowed_task_types = set(TASK_WORKSPACE_TASK_TYPES[workspace])
        if task_type not in allowed_task_types:
            task_type = workspace_config["default_task_type"]
        if priority not in PRIORITY_DISPLAY_LABELS:
            priority = record.priority or "normal"
        assigned_user_id = parse_optional_int(assigned_to_id)
        if assigned_user_id and not db.get(User, assigned_user_id):
            assigned_user_id = None
        if not is_assignment_allowed_for_workspace(db, assigned_user_id, workspace):
            return RedirectResponse(
                f"{task_workspace_new_url(workspace, 'task')}&error=assignment_not_allowed",
                status_code=303,
            )
        assigned_team_id = parse_optional_int(team_id)
        if assigned_team_id and not db.get(Team, assigned_team_id):
            assigned_team_id = None
        delegated_user_id, delegated_team_id = parse_delegation_target(delegated_to)
        if delegated_user_id and not db.get(User, delegated_user_id):
            delegated_user_id = None
        if not is_assignment_allowed_for_workspace(db, delegated_user_id, workspace):
            return RedirectResponse(
                f"{task_workspace_new_url(workspace, 'task')}&error=assignment_not_allowed",
                status_code=303,
            )
        if delegated_team_id and not db.get(Team, delegated_team_id):
            delegated_team_id = None

        task = Task(
            title=title.strip() or record.title,
            description=description.strip() or record.description,
            task_type=task_type,
            source=record.source or "manual",
            category=workspace_config["default_category"],
            subcategory=default_task_subcategory(workspace_config["default_category"]),
            status="new",
            priority=priority,
            customer_name=record.customer_name,
            customer_contact=record.customer_contact,
            customer_email=record.customer_email,
            customer_phone=record.customer_phone,
            plate=record.plate,
            station=record.station,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            assigned_to_id=assigned_user_id,
            team_id=assigned_team_id,
            delegated_to_user_id=delegated_user_id,
            delegated_to_team_id=delegated_team_id,
            created_by_id=user_id,
            due_on=parse_optional_date(due_on),
        )
        db.add(task)
        db.flush()
        task_id = task.id
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        record.status = "converted"
        record.converted_task_id = task.id
        record.closed_at = record.closed_at or datetime.now(UTC)
        record_audit(
            db,
            action="quick_record.convert",
            entity_type="quick_record",
            entity_id=record.id,
            detail=f"Registo rápido convertido em tarefa: {task.title}",
            after_json={"task_id": task.id},
            user_id=user_id,
        )
        record_audit(
            db,
            action="task.create",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa criada por conversão: {task.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/task-board/{task_id}?commented=1", status_code=303)


@web_router.post("/task-board", response_class=HTMLResponse)
@web_router.post("/task-board/new", response_class=HTMLResponse)
def task_create(
    request: Request,
    title: str = Form(...),
    workspace: str = Form("operational"),
    task_type: str = Form("operational_task"),
    category: str = Form(""),
    subcategory: str = Form(""),
    manual_subcategory: str = Form(""),
    source: str = Form("manual"),
    priority: str = Form("normal"),
    assigned_to_id: str = Form(""),
    team_id: str = Form(""),
    delegated_to: str = Form(""),
    due_on: str = Form(""),
    customer_name: str = Form(""),
    customer_contact: str = Form(""),
    customer_email: str = Form(""),
    customer_phone: str = Form(""),
    plate: str = Form(""),
    reservation_number: str = Form(""),
    contract_number: str = Form(""),
    station: str = Form(""),
    department: str = Form(""),
    external_source_id: str = Form(""),
    parent_task_id: str = Form(""),
    guided_flow_code: str = Form(""),
    recurrence_rule: str = Form(""),
    recurrence_interval: str = Form(""),
    description: str = Form(""),
    confirm_duplicate: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    current_workspace = normalize_task_workspace(workspace)
    workspace_config = TASK_WORKSPACE_CONFIG[current_workspace]
    clean_title = title.strip()
    parsed_parent_task_id = parse_optional_int(parent_task_id)
    if not clean_title:
        with SessionLocal() as db:
            current_user = db.get(User, user_id)
            parent_task = db.get(Task, parsed_parent_task_id) if parsed_parent_task_id else None
            if parent_task:
                current_workspace = workspace_for_task_type(parent_task.task_type)
                workspace_config = TASK_WORKSPACE_CONFIG[current_workspace]
            if not user_can_access_task_workspace(db, current_user, current_workspace, write=True):
                return RedirectResponse("/task-board", status_code=303)
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            assignable_users = assignable_users_for_workspace(users, current_workspace)
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        return templates.TemplateResponse(
            request,
            "task_new.html",
            {
                "users": users,
                "assignable_users": assignable_users,
                "current_user": current_user,
                "teams": teams,
                "error": "Indica um título para a tarefa.",
                "form_mode": "task",
                "workspace": current_workspace,
                "workspace_config": workspace_config,
                "workspace_label": workspace_config["label"],
                "manage_url": task_workspace_manage_url(current_workspace),
                "form_values": {
                    "parent_task_id": parent_task.id if parent_task else "",
                    "category": workspace_config["default_category"],
                    "subcategory": default_task_subcategory(workspace_config["default_category"]),
                },
                "parent_task": parent_task,
                "duplicate_tasks": [],
                "task_sources": TASK_SOURCES,
                "task_types": workspace_task_type_options(current_workspace),
                "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE[current_workspace],
                "workspaces": TASK_WORKSPACES,
                "task_categories": TASK_CATEGORIES,
                "task_subcategories_by_category": TASK_SUBCATEGORIES_BY_CATEGORY,
                "task_subcategory_labels": TASK_SUBCATEGORY_DISPLAY_LABELS,
                "priorities": PRIORITIES,
                "delegation_value": delegated_to,
                "guided_flow_options": guided_flow_options_for_workspace(current_workspace),
                "can_create_recurring": user_can_create_recurring_tasks(db, current_user),
                "recurrence_rules": RECURRENCE_RULES,
            },
            status_code=400,
        )

    with SessionLocal() as db:
        clean_plate = plate.strip().upper().replace(" ", "")
        parent_task = db.get(Task, parsed_parent_task_id) if parsed_parent_task_id else None
        if parent_task:
            current_workspace = workspace_for_task_type(parent_task.task_type)
            workspace_config = TASK_WORKSPACE_CONFIG[current_workspace]
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, current_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        if source not in TASK_SOURCE_DISPLAY_LABELS:
            source = "manual"
        allowed_workspace_task_types = set(TASK_WORKSPACE_TASK_TYPES[current_workspace])
        if task_type not in allowed_workspace_task_types:
            task_type = workspace_config["default_task_type"]
        if category not in TASK_CATEGORY_LABELS:
            category = workspace_config["default_category"]
        requested_subcategory = subcategory
        subcategory = normalize_task_subcategory(category, subcategory)
        clean_manual_subcategory = manual_subcategory.strip()[:120]
        if clean_manual_subcategory and task_subcategory_allows_manual_text(requested_subcategory):
            subcategory = clean_manual_subcategory
        clean_guided_flow_code = guided_flow_code if guided_flow_template(guided_flow_code) else None
        if clean_guided_flow_code and current_workspace not in guided_flow_template(clean_guided_flow_code)["workspaces"]:
            clean_guided_flow_code = None
        can_create_recurring = user_can_create_recurring_tasks(db, current_user)
        clean_recurrence_rule = recurrence_rule if recurrence_rule in RECURRENCE_RULE_LABELS and can_create_recurring else None
        parsed_recurrence_interval = parse_optional_int(recurrence_interval) or 1
        parsed_recurrence_interval = min(max(parsed_recurrence_interval, 1), 36)
        assigned_user_id = parse_optional_int(assigned_to_id)
        if assigned_user_id and not db.get(User, assigned_user_id):
            assigned_user_id = None
        if not is_assignment_allowed_for_workspace(db, assigned_user_id, workspace):
            return RedirectResponse(f"{task_workspace_new_url(current_workspace, 'task')}&error=assignment_not_allowed", status_code=303)
        assigned_team_id = parse_optional_int(team_id)
        if assigned_team_id and not db.get(Team, assigned_team_id):
            assigned_team_id = None
        delegated_user_id, delegated_team_id = parse_delegation_target(delegated_to)
        if delegated_user_id and not db.get(User, delegated_user_id):
            delegated_user_id = None
        if not is_assignment_allowed_for_workspace(db, delegated_user_id, workspace):
            return RedirectResponse(f"{task_workspace_new_url(current_workspace, 'task')}&error=assignment_not_allowed", status_code=303)
        if delegated_team_id and not db.get(Team, delegated_team_id):
            delegated_team_id = None
        parent_task_redirect_id = parent_task.id if parent_task else None
        duplicate_tasks = []
        if clean_plate and confirm_duplicate != "1" and not parent_task:
            duplicate_tasks = db.scalars(
                select(Task)
                .where(
                    Task.plate == clean_plate,
                    Task.closed_at.is_(None),
                    ~Task.status.in_(TASK_ARCHIVE_STATUSES | TASK_PLANNED_STATUSES),
                )
                .order_by(Task.due_on.is_(None), Task.due_on, Task.id.desc())
                .limit(8)
            ).all()
        if duplicate_tasks:
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            assignable_users = assignable_users_for_workspace(users, current_workspace)
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
            return templates.TemplateResponse(
                request,
                "task_new.html",
                {
                    "users": users,
                    "assignable_users": assignable_users,
                    "current_user": db.get(User, user_id),
                    "teams": teams,
                    "error": None,
                    "duplicate_tasks": duplicate_tasks,
                    "form_mode": "task",
                    "workspace": current_workspace,
                    "workspace_config": workspace_config,
                    "workspace_label": workspace_config["label"],
                    "manage_url": task_workspace_manage_url(current_workspace),
                    "form_values": {
                        "title": clean_title,
                        "description": description,
                        "task_type": task_type,
                        "priority": priority,
                        "source": source,
                        "category": category,
                        "subcategory": requested_subcategory if clean_manual_subcategory and task_subcategory_allows_manual_text(requested_subcategory) else subcategory,
                        "manual_subcategory": clean_manual_subcategory,
                        "plate": clean_plate,
                        "station": station,
                        "due_on": due_on,
                        "customer_name": customer_name,
                        "customer_contact": customer_contact,
                        "customer_email": customer_email,
                        "customer_phone": customer_phone,
                        "reservation_number": reservation_number,
                        "contract_number": contract_number,
                        "assigned_to_id": assigned_to_id,
                        "delegated_to": delegated_to,
                        "department": department,
                        "external_source_id": external_source_id,
                        "parent_task_id": parent_task.id if parent_task else "",
                        "guided_flow_code": clean_guided_flow_code or "",
                        "recurrence_rule": clean_recurrence_rule or "",
                        "recurrence_interval": parsed_recurrence_interval,
                    },
                    "parent_task": parent_task,
                    "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                    "task_sources": TASK_SOURCES,
                    "task_types": workspace_task_type_options(current_workspace),
                    "quick_record_types": QUICK_RECORD_TYPES_BY_WORKSPACE[current_workspace],
                    "workspaces": TASK_WORKSPACES,
                    "task_categories": TASK_CATEGORIES,
                    "task_subcategories_by_category": TASK_SUBCATEGORIES_BY_CATEGORY,
                    "task_subcategory_labels": TASK_SUBCATEGORY_DISPLAY_LABELS,
                    "priorities": PRIORITIES,
                    "guided_flow_options": guided_flow_options_for_workspace(current_workspace),
                    "can_create_recurring": can_create_recurring,
                    "recurrence_rules": RECURRENCE_RULES,
                },
                status_code=409,
            )
        task = Task(
            title=clean_title,
            description=description.strip() or None,
            task_type=task_type,
            source=source,
            category=category,
            subcategory=subcategory,
            status="new",
            priority=priority,
            customer_name=customer_name.strip() or None,
            customer_contact=customer_contact.strip() or None,
            customer_email=customer_email.strip().lower() or None,
            customer_phone=customer_phone.strip() or None,
            plate=clean_plate or None,
            reservation_number=reservation_number.strip() or None,
            contract_number=contract_number.strip() or None,
            station=station.strip() or None,
            department=department.strip() or None,
            external_source_id=external_source_id.strip() or None,
            parent_task_id=parent_task.id if parent_task else None,
            assigned_to_id=assigned_user_id,
            team_id=assigned_team_id,
            delegated_to_user_id=delegated_user_id,
            delegated_to_team_id=delegated_team_id,
            created_by_id=user_id,
            due_on=parse_optional_date(due_on),
            planned_for=None,
            guided_flow_code=clean_guided_flow_code,
            recurrence_enabled=bool(clean_recurrence_rule),
            recurrence_rule=clean_recurrence_rule,
            recurrence_interval=parsed_recurrence_interval if clean_recurrence_rule else None,
            recurrence_next_on=next_recurrence_date(parse_optional_date(due_on) or date.today(), clean_recurrence_rule, parsed_recurrence_interval)
            if clean_recurrence_rule
            else None,
        )
        db.add(task)
        db.flush()
        create_guided_flow_run_for_task(db, task, clean_guided_flow_code, user_id)
        db.add(
            TaskHistory(
                task_id=task.id,
                user_id=user_id,
                field_name="status",
                old_value=None,
                new_value="new",
            )
        )
        record_audit(
            db,
            action="task.create",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa criada: {task.title}",
            after_json={"parent_task_id": task.parent_task_id} if task.parent_task_id else None,
            user_id=user_id,
        )
        db.commit()

    if parent_task_redirect_id:
        return RedirectResponse(f"/task-board/{parent_task_redirect_id}?commented=1", status_code=303)
    return RedirectResponse(f"{task_workspace_manage_url(current_workspace)}?created=1", status_code=303)


@web_router.get("/task-board/{task_id}", response_class=HTMLResponse)
def task_detail(
    request: Request,
    task_id: int,
    commented: str | None = None,
    feedback_saved: str | None = None,
    error: str | None = None,
):
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        current_user = db.get(User, get_web_user_id(request))
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)
        task_workspace = workspace_for_task_type(task.task_type)
        if not user_can_access_task_workspace(db, current_user, task_workspace):
            return RedirectResponse("/task-board", status_code=303)
        task_manage_url = task_workspace_manage_url(task_workspace)
        comments = db.scalars(
            select(TaskComment).where(TaskComment.task_id == task.id).order_by(TaskComment.created_at.desc())
        ).all()
        history = db.scalars(
            select(TaskHistory).where(TaskHistory.task_id == task.id).order_by(TaskHistory.changed_at.desc())
        ).all()
        linked_vehicle = None
        if task.entity_type == "vehicle" and task.entity_id and task.entity_id.isdigit():
            linked_vehicle = db.get(Vehicle, int(task.entity_id))
        elif task.plate:
            linked_vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == task.plate))
        parent_task = db.get(Task, task.parent_task_id) if task.parent_task_id else None
        subtasks = db.scalars(
            select(Task)
            .where(Task.parent_task_id == task.id)
            .order_by(Task.id.desc(), Task.created_at.desc())
            .limit(50)
        ).all()
        documents = db.scalars(
            select(Document)
            .where(Document.task_id == task.id)
            .order_by(Document.id.desc())
            .limit(20)
        ).all()
        guided_flow = task_guided_flow_context(db, task)
        users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
        user_by_id = {item.id: item for item in users}
        assignable_users = assignable_users_for_workspace(users, task_workspace)
        teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
        team_by_id = {item.id: item for item in teams}
        assigned_user = db.get(User, task.assigned_to_id) if task.assigned_to_id else None
        assigned_team = db.get(Team, task.team_id) if task.team_id else None
        delegated_user = db.get(User, task.delegated_to_user_id) if task.delegated_to_user_id else None
        delegated_team = db.get(Team, task.delegated_to_team_id) if task.delegated_to_team_id else None
        waiting_for_user = db.get(User, task.waiting_for_user_id) if task.waiting_for_user_id else None
        waiting_for_team = db.get(Team, task.waiting_for_team_id) if task.waiting_for_team_id else None
        for current_option in (assigned_user, delegated_user, waiting_for_user):
            if current_option and current_option.id not in {item.id for item in users}:
                users.append(current_option)
                user_by_id[current_option.id] = current_option
            if current_option and current_option.id not in {item.id for item in assignable_users}:
                assignable_users.append(current_option)
        for current_option in (assigned_team, delegated_team, waiting_for_team):
            if current_option and current_option.id not in {item.id for item in teams}:
                teams.append(current_option)
                team_by_id[current_option.id] = current_option
        current_status_options = list(TASK_STATUSES)
        if task.status and task.status not in {code for code, _ in current_status_options}:
            current_status_options.insert(0, (task.status, TASK_STATUS_DISPLAY_LABELS.get(task.status, task.status)))
        current_priority_options = list(PRIORITIES)
        if task.priority and task.priority not in {code for code, _ in current_priority_options}:
            current_priority_options.insert(0, (task.priority, PRIORITY_DISPLAY_LABELS.get(task.priority, task.priority)))
        current_category_options = list(TASK_CATEGORIES)
        if task.category and task.category not in {code for code, _ in current_category_options}:
            current_category_options.insert(0, (task.category, TASK_CATEGORY_DISPLAY_LABELS.get(task.category, task.category)))
        return templates.TemplateResponse(
            request,
            "task_detail.html",
            {
                "task": task,
                "task_workspace": task_workspace,
                "task_workspace_label": TASK_WORKSPACE_LABELS[task_workspace],
                "task_manage_url": task_manage_url,
                "can_write_workspace": user_can_access_task_workspace(db, current_user, task_workspace, write=True),
                "comments": comments,
                "history": history,
                "linked_vehicle": linked_vehicle,
                "parent_task": parent_task,
                "subtasks": subtasks,
                "documents": documents,
                "guided_flow": guided_flow,
                "guided_flow_step_statuses": GUIDED_FLOW_STEP_STATUSES,
                "guided_flow_step_status_labels": GUIDED_FLOW_STEP_STATUS_LABELS,
                "guided_flow_step_status_class": GUIDED_FLOW_STEP_STATUS_CLASS,
                "recurrence_rule_labels": RECURRENCE_RULE_LABELS,
                "users": users,
                "assignable_users": assignable_users,
                "current_user": current_user,
                "user_by_id": user_by_id,
                "teams": teams,
                "team_by_id": team_by_id,
                "assigned_user": assigned_user,
                "assigned_team": assigned_team,
                "delegated_user": delegated_user,
                "delegated_team": delegated_team,
                "responsible_value": format_delegation_target(task.assigned_to_id, task.team_id),
                "delegation_value": format_delegation_target(task.delegated_to_user_id, task.delegated_to_team_id),
                "waiting_for_user": waiting_for_user,
                "waiting_for_team": waiting_for_team,
                "waiting_for_value": format_delegation_target(task.waiting_for_user_id, task.waiting_for_team_id),
                "commented": commented,
                "feedback_saved": feedback_saved,
                "error": task_detail_error_message(error),
                "task_statuses": current_status_options,
                "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                "waiting_reasons": TASK_WAITING_REASONS,
                "waiting_reason_labels": TASK_WAITING_REASON_LABELS,
                "priorities": current_priority_options,
                "priority_labels": PRIORITY_DISPLAY_LABELS,
                "task_types": TASK_TYPES,
                "task_type_labels": TASK_TYPE_LABELS,
                "task_source_labels": TASK_SOURCE_DISPLAY_LABELS,
                "task_categories": current_category_options,
                "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
                "task_subcategories_by_category": TASK_SUBCATEGORIES_BY_CATEGORY,
                "task_subcategory_labels": TASK_SUBCATEGORY_DISPLAY_LABELS,
                "task_history_field_labels": TASK_HISTORY_FIELD_LABELS,
                "document_statuses": DOCUMENT_STATUSES,
                "document_status_labels": DOCUMENT_STATUS_LABELS,
                "document_area_labels": DOCUMENT_AREA_LABELS,
                "document_type_labels": DOCUMENT_TYPE_LABELS,
                "document_sources": DOCUMENT_SOURCES,
            },
        )


@web_router.post("/task-board/{task_id}/update", response_class=HTMLResponse)
def task_update(
    request: Request,
    task_id: int,
    status: str = Form(""),
    priority: str = Form(""),
    task_type: str = Form(""),
    category: str | None = Form(None),
    subcategory: str | None = Form(None),
    responsible_to: str = Form(""),
    assigned_to_id: str | None = Form(None),
    team_id: str | None = Form(None),
    delegated_to: str = Form(""),
    waiting_for: str = Form(""),
    waiting_reason: str = Form(""),
    waiting_reason_detail: str = Form(""),
    due_on: str = Form(""),
    department: str | None = Form(None),
    station: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)
        allowed_statuses = {code for code, _ in TASK_STATUSES} | TASK_ARCHIVE_STATUSES | {task.status}
        if status not in allowed_statuses:
            status = task.status
        if priority not in PRIORITY_DISPLAY_LABELS:
            priority = task.priority or "normal"
        if task_type not in TASK_TYPE_LABELS:
            task_type = task.task_type or "operational_task"
        current_user = db.get(User, user_id)
        can_supervise = can_supervise_task(db, current_user, task)
        current_workspace = workspace_for_task_type(task.task_type)
        target_workspace = workspace_for_task_type(task_type)
        if not user_can_access_task_workspace(db, current_user, current_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        if target_workspace != current_workspace and not user_can_access_task_workspace(
            db, current_user, target_workspace, write=True
        ):
            return RedirectResponse("/task-board", status_code=303)
        clean_category = (category.strip() if category else None) or task.category or "operations"
        if clean_category not in TASK_CATEGORY_LABELS:
            clean_category = task.category or "operations"
        if clean_category not in TASK_CATEGORY_LABELS:
            clean_category = "other"
        clean_subcategory = normalize_task_subcategory(clean_category, subcategory)
        clean_department = department.strip() if department is not None else (task.department or "")

        responsible_user_id, responsible_team_id = parse_delegation_target(responsible_to)
        assigned_user_id = responsible_user_id if responsible_to else parse_optional_int(assigned_to_id)
        if assigned_user_id and not db.get(User, assigned_user_id):
            assigned_user_id = None
        assigned_team_id = responsible_team_id if responsible_to else parse_optional_int(team_id)
        if assigned_team_id and not db.get(Team, assigned_team_id):
            assigned_team_id = None
        assignment_changed = (
            str(task.assigned_to_id or "") != str(assigned_user_id or "")
            or str(task.team_id or "") != str(assigned_team_id or "")
        )
        if assignment_changed and not is_assignment_allowed_for_workspace(db, assigned_user_id, target_workspace):
            return task_update_error_url(task_id, "assignment_not_allowed")
        delegated_user_id, delegated_team_id = parse_delegation_target(delegated_to)
        if delegated_user_id and not db.get(User, delegated_user_id):
            delegated_user_id = None
        delegate_changed = (
            str(task.delegated_to_user_id or "") != str(delegated_user_id or "")
            or str(task.delegated_to_team_id or "") != str(delegated_team_id or "")
        )
        if delegate_changed and not is_assignment_allowed_for_workspace(db, delegated_user_id, target_workspace):
            return task_update_error_url(task_id, "assignment_not_allowed")
        if delegated_team_id and not db.get(Team, delegated_team_id):
            delegated_team_id = None
        waiting_for_user_id, waiting_for_team_id = parse_delegation_target(waiting_for)
        if waiting_for_user_id and not db.get(User, waiting_for_user_id):
            waiting_for_user_id = None
        if waiting_for_team_id and not db.get(Team, waiting_for_team_id):
            waiting_for_team_id = None
        parsed_due_on = parse_optional_date(due_on)
        clean_waiting_reason = waiting_reason.strip()
        clean_waiting_reason_detail = waiting_reason_detail.strip()
        if status in TASK_RESPONSIBLE_ONLY_STATUSES and not can_supervise:
            return task_update_error_url(task_id, "responsible_required")
        if (status == "delegated" or delegate_changed) and not can_supervise:
            return task_update_error_url(task_id, "delegation_not_allowed")
        if status == "delegated" and not delegated_user_id and not delegated_team_id:
            return task_update_error_url(task_id, "delegation_required")
        if status == "waiting":
            if clean_waiting_reason not in TASK_WAITING_REASON_LABELS:
                return task_update_error_url(task_id, "waiting_reason_required")
            if clean_waiting_reason == "other" and not clean_waiting_reason_detail:
                return task_update_error_url(task_id, "waiting_reason_detail_required")
        else:
            clean_waiting_reason = ""
            clean_waiting_reason_detail = ""
            waiting_for_user_id = None
            waiting_for_team_id = None

        changes: list[tuple[str, str, str]] = []
        add_visible_task_change(
            changes,
            "Estado",
            TASK_STATUS_DISPLAY_LABELS.get(task.status, task.status),
            TASK_STATUS_DISPLAY_LABELS.get(status, status),
        )
        add_visible_task_change(
            changes,
            "Prioridade",
            PRIORITY_DISPLAY_LABELS.get(task.priority, task.priority),
            PRIORITY_DISPLAY_LABELS.get(priority, priority),
        )
        add_visible_task_change(
            changes,
            "Tipo de tarefa",
            TASK_TYPE_LABELS.get(task.task_type, task.task_type),
            TASK_TYPE_LABELS.get(task_type, task_type),
        )
        add_visible_task_change(
            changes,
            "Classificação",
            TASK_CATEGORY_DISPLAY_LABELS.get(task.category, task.category),
            TASK_CATEGORY_DISPLAY_LABELS.get(clean_category, clean_category),
        )
        add_visible_task_change(
            changes,
            "Subcategoria",
            TASK_SUBCATEGORY_DISPLAY_LABELS.get(task.subcategory or "", task.subcategory),
            TASK_SUBCATEGORY_DISPLAY_LABELS.get(clean_subcategory, clean_subcategory),
        )
        add_visible_task_change(
            changes,
            "Responsável",
            task_target_label(db, task.assigned_to_id, task.team_id),
            task_target_label(db, assigned_user_id, assigned_team_id),
        )
        add_visible_task_change(
            changes,
            "Execução delegada a",
            task_target_label(db, task.delegated_to_user_id, task.delegated_to_team_id),
            task_target_label(db, delegated_user_id, delegated_team_id),
        )
        add_visible_task_change(
            changes,
            "A aguardar por",
            task_target_label(db, task.waiting_for_user_id, task.waiting_for_team_id),
            task_target_label(db, waiting_for_user_id, waiting_for_team_id),
        )
        add_visible_task_change(
            changes,
            "Motivo de espera",
            TASK_WAITING_REASON_LABELS.get(task.waiting_reason or "", task.waiting_reason),
            TASK_WAITING_REASON_LABELS.get(clean_waiting_reason, clean_waiting_reason),
        )
        add_visible_task_change(changes, "Detalhe do motivo", task.waiting_reason_detail, clean_waiting_reason_detail)
        add_visible_task_change(
            changes,
            "Data limite",
            task.due_on.isoformat() if task.due_on else "",
            parsed_due_on.isoformat() if parsed_due_on else "",
        )
        add_visible_task_change(changes, "Área", task.department, clean_department)
        add_visible_task_change(changes, "Estação", task.station, station.strip())

        task.status = status
        task.priority = priority
        task.task_type = task_type
        task.category = clean_category
        task.subcategory = clean_subcategory or None
        task.assigned_to_id = assigned_user_id
        task.team_id = assigned_team_id
        task.delegated_to_user_id = delegated_user_id
        task.delegated_to_team_id = delegated_team_id
        task.waiting_for_user_id = waiting_for_user_id
        task.waiting_for_team_id = waiting_for_team_id
        task.waiting_reason = clean_waiting_reason or None
        task.waiting_reason_detail = clean_waiting_reason_detail or None
        task.due_on = parsed_due_on
        task.department = clean_department or None
        task.station = station.strip() or None
        if status in {"resolved", "closed", "no_action_needed"}:
            task.resolved_at = task.resolved_at or datetime.now(UTC)
        else:
            task.resolved_at = None
        if status in {"closed", "cancelled", "no_action_needed"}:
            task.closed_at = task.closed_at or datetime.now(UTC)
        else:
            task.closed_at = None
        next_recurring_task = None
        if status in {"closed", "cancelled", "no_action_needed"}:
            next_recurring_task = create_next_recurring_task(db, task, user_id)
            if next_recurring_task:
                task.recurrence_next_on = next_recurring_task.planned_for

        for field_name, old_value, new_value in changes:
            db.add(
                TaskHistory(
                    task_id=task.id,
                    user_id=user_id,
                    field_name=field_name,
                    old_value=old_value or None,
                    new_value=new_value or None,
                )
            )
        if next_recurring_task:
            db.add(
                TaskHistory(
                    task_id=task.id,
                    user_id=user_id,
                    field_name="Recorrência",
                    old_value=None,
                    new_value=f"Próxima ocorrência CF-TASK-{next_recurring_task.id:05d} planeada para {next_recurring_task.planned_for}",
                )
            )

        record_audit(
            db,
            action="task.update",
            entity_type="task",
            entity_id=task.id,
            detail=f"Tarefa atualizada: {task.title}",
            user_id=user_id,
        )
        db.commit()

    if status in {"closed", "cancelled", "no_action_needed"}:
        return RedirectResponse(f"{task_workspace_manage_url(workspace_for_task_type(task_type))}?closed=1", status_code=303)
    return RedirectResponse(f"/task-board/{task_id}?commented=1", status_code=303)


@web_router.post("/task-board/{task_id}/flow/{step_run_id}", response_class=HTMLResponse)
def task_guided_flow_step_update(
    request: Request,
    task_id: int,
    step_run_id: int,
    step_status: str = Form("pending"),
    step_note: str = Form(""),
    action: str = Form("save"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        step = db.get(TaskGuidedFlowStepRun, step_run_id)
        if not task or not step or step.task_id != task.id:
            return RedirectResponse("/task-board/manage", status_code=303)
        task_workspace = workspace_for_task_type(task.task_type)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, task_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)

        allowed_step_statuses = {code for code, _ in GUIDED_FLOW_STEP_STATUSES}
        if step_status not in allowed_step_statuses:
            step_status = step.status or "pending"
        clean_note = step_note.strip()
        old_status = step.status
        step_data = dict(step.data_json or {})
        if clean_note:
            step_data["note"] = clean_note
        step.data_json = step_data

        if action == "generate_task":
            subtask = Task(
                title=f"{step.title} - {task.title}",
                description=clean_note or f"Passo pendente gerado a partir da tarefa CF-TASK-{task.id:05d}.",
                task_type=task.task_type,
                source="system",
                category=task.category,
                subcategory=task.subcategory,
                status="new",
                priority=task.priority or "normal",
                customer_name=task.customer_name,
                customer_contact=task.customer_contact,
                customer_email=task.customer_email,
                customer_phone=task.customer_phone,
                plate=task.plate,
                reservation_number=task.reservation_number,
                contract_number=task.contract_number,
                station=task.station,
                department=task.department,
                entity_type=task.entity_type,
                entity_id=task.entity_id,
                parent_task_id=task.id,
                team_id=task.team_id,
                assigned_to_id=task.assigned_to_id,
                created_by_id=user_id,
                due_on=task.due_on,
            )
            db.add(subtask)
            db.flush()
            step.generated_task_id = subtask.id
            step.status = "task_created"
            db.add(
                TaskHistory(
                    task_id=subtask.id,
                    user_id=user_id,
                    field_name="status",
                    old_value=None,
                    new_value=TASK_STATUS_DISPLAY_LABELS.get("new", "Nova"),
                )
            )
            db.add(
                TaskHistory(
                    task_id=task.id,
                    user_id=user_id,
                    field_name="Fluxo guiado",
                    old_value=GUIDED_FLOW_STEP_STATUS_LABELS.get(old_status, old_status),
                    new_value=f"{step.title}: tarefa CF-TASK-{subtask.id:05d} criada",
                )
            )
        else:
            step.status = step_status
            if step_status in {"done", "not_applicable", "task_created"}:
                step.completed_by_id = user_id
                step.completed_at = step.completed_at or datetime.now(UTC)
            else:
                step.completed_by_id = None
                step.completed_at = None
            db.add(
                TaskHistory(
                    task_id=task.id,
                    user_id=user_id,
                    field_name="Fluxo guiado",
                    old_value=f"{step.title}: {GUIDED_FLOW_STEP_STATUS_LABELS.get(old_status, old_status)}",
                    new_value=f"{step.title}: {GUIDED_FLOW_STEP_STATUS_LABELS.get(step.status, step.status)}",
                )
            )

        flow_run = db.get(TaskGuidedFlowRun, step.flow_run_id)
        if flow_run:
            remaining = db.scalar(
                select(func.count())
                .select_from(TaskGuidedFlowStepRun)
                .where(
                    TaskGuidedFlowStepRun.flow_run_id == flow_run.id,
                    TaskGuidedFlowStepRun.status == "pending",
                )
            )
            if remaining == 0:
                flow_run.status = "completed"
                flow_run.completed_at = flow_run.completed_at or datetime.now(UTC)
            else:
                flow_run.status = "active"
                flow_run.completed_at = None

        record_audit(
            db,
            action="task.guided_flow.step.updated",
            entity_type="task_guided_flow_step_run",
            entity_id=step.id,
            detail=f"Passo do fluxo atualizado: {step.title}",
            before_json={"status": old_status},
            after_json={"status": step.status, "generated_task_id": step.generated_task_id},
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/task-board/{task_id}?commented=1#flow-step-{step_run_id}", status_code=303)


@web_router.post("/task-board/{task_id}/comments", response_class=HTMLResponse)
def task_add_comment(
    request: Request,
    task_id: int,
    comment: str = Form(...),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    clean_comment = comment.strip()
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)
        task_workspace = workspace_for_task_type(task.task_type)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, task_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)

        if not clean_comment:
            comments = db.scalars(
                select(TaskComment)
                .where(TaskComment.task_id == task.id)
                .order_by(TaskComment.created_at.desc())
            ).all()
            history = db.scalars(
                select(TaskHistory)
                .where(TaskHistory.task_id == task.id)
                .order_by(TaskHistory.changed_at.desc())
            ).all()
            linked_vehicle = None
            if task.entity_type == "vehicle" and task.entity_id and task.entity_id.isdigit():
                linked_vehicle = db.get(Vehicle, int(task.entity_id))
            elif task.plate:
                linked_vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == task.plate))
            documents = db.scalars(
                select(Document)
                .where(Document.task_id == task.id)
                .order_by(Document.id.desc())
                .limit(20)
            ).all()
            users = db.scalars(select(User).where(User.active.is_(True)).order_by(User.name, User.email)).all()
            user_by_id = {item.id: item for item in users}
            assignable_users = assignable_users_for_workspace(users, task_workspace)
            teams = db.scalars(select(Team).where(Team.active.is_(True)).order_by(Team.name)).all()
            assigned_user = db.get(User, task.assigned_to_id) if task.assigned_to_id else None
            assigned_team = db.get(Team, task.team_id) if task.team_id else None
            delegated_user = db.get(User, task.delegated_to_user_id) if task.delegated_to_user_id else None
            delegated_team = db.get(Team, task.delegated_to_team_id) if task.delegated_to_team_id else None
            waiting_for_user = db.get(User, task.waiting_for_user_id) if task.waiting_for_user_id else None
            waiting_for_team = db.get(Team, task.waiting_for_team_id) if task.waiting_for_team_id else None
            parent_task = db.get(Task, task.parent_task_id) if task.parent_task_id else None
            subtasks = db.scalars(
                select(Task)
                .where(Task.parent_task_id == task.id)
                .order_by(Task.created_at.desc(), Task.id.desc())
            ).all()
            guided_flow = task_guided_flow_context(db, task)
            return templates.TemplateResponse(
                request,
                "task_detail.html",
                {
                    "task": task,
                    "task_workspace": task_workspace,
                    "task_workspace_label": TASK_WORKSPACE_LABELS[task_workspace],
                    "task_manage_url": task_workspace_manage_url(task_workspace),
                    "comments": comments,
                    "history": history,
                    "linked_vehicle": linked_vehicle,
                    "documents": documents,
                    "users": users,
                    "assignable_users": assignable_users,
                    "current_user": current_user,
                    "can_write_workspace": True,
                    "user_by_id": user_by_id,
                    "teams": teams,
                    "assigned_user": assigned_user,
                    "assigned_team": assigned_team,
                    "delegated_user": delegated_user,
                    "delegated_team": delegated_team,
                    "delegation_value": format_delegation_target(task.delegated_to_user_id, task.delegated_to_team_id),
                    "waiting_for_user": waiting_for_user,
                    "waiting_for_team": waiting_for_team,
                    "waiting_for_value": format_delegation_target(task.waiting_for_user_id, task.waiting_for_team_id),
                    "parent_task": parent_task,
                    "subtasks": subtasks,
                    "guided_flow": guided_flow,
                    "guided_flow_step_statuses": GUIDED_FLOW_STEP_STATUSES,
                    "guided_flow_step_status_labels": GUIDED_FLOW_STEP_STATUS_LABELS,
                    "guided_flow_step_status_class": GUIDED_FLOW_STEP_STATUS_CLASS,
                    "recurrence_rule_labels": RECURRENCE_RULE_LABELS,
                    "commented": None,
                    "error": "Escreve um comentário antes de gravar.",
                    "task_statuses": TASK_STATUSES,
                    "task_status_labels": TASK_STATUS_DISPLAY_LABELS,
                    "waiting_reasons": TASK_WAITING_REASONS,
                    "waiting_reason_labels": TASK_WAITING_REASON_LABELS,
                    "priorities": PRIORITIES,
                    "priority_labels": PRIORITY_DISPLAY_LABELS,
                    "task_types": TASK_TYPES,
                    "task_type_labels": TASK_TYPE_LABELS,
                    "task_source_labels": TASK_SOURCE_DISPLAY_LABELS,
                    "task_categories": TASK_CATEGORIES,
                    "task_category_labels": TASK_CATEGORY_DISPLAY_LABELS,
                    "task_subcategories_by_category": TASK_SUBCATEGORIES_BY_CATEGORY,
                    "task_subcategory_labels": TASK_SUBCATEGORY_DISPLAY_LABELS,
                    "task_history_field_labels": TASK_HISTORY_FIELD_LABELS,
                    "document_statuses": DOCUMENT_STATUSES,
                    "document_status_labels": DOCUMENT_STATUS_LABELS,
                    "document_area_labels": DOCUMENT_AREA_LABELS,
                    "document_type_labels": DOCUMENT_TYPE_LABELS,
                    "document_sources": DOCUMENT_SOURCES,
                },
                status_code=400,
            )

        db.add(TaskComment(task_id=task.id, user_id=user_id, comment=clean_comment))
        record_audit(
            db,
            action="task.comment.created",
            entity_type="task",
            entity_id=task.id,
            detail=f"Comentário adicionado à tarefa: {task.title}",
            user_id=user_id,
        )
        db.commit()

    return RedirectResponse(f"/task-board/{task_id}?commented=1", status_code=303)


@web_router.post("/task-board/{task_id}/documents", response_class=HTMLResponse)
def task_create_document(
    request: Request,
    task_id: int,
    title: str = Form(""),
    classification: str = Form("general_archive"),
    document_type: str = Form("general_archive"),
    status: str = Form("unclassified"),
    document_date: str = Form(""),
    source: str = Form("email"),
    entry_channel: str = Form(""),
    source_sender: str = Form(""),
    source_subject: str = Form(""),
    url_original: str = Form(""),
    url_archive: str = Form(""),
    supplier_name: str = Form(""),
    notes: str = Form(""),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if not task:
            return RedirectResponse("/task-board/manage", status_code=303)
        task_workspace = workspace_for_task_type(task.task_type)
        current_user = db.get(User, user_id)
        if not user_can_access_task_workspace(db, current_user, task_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == task.plate)) if task.plate else None
        if classification not in DOCUMENT_AREA_LABELS:
            classification = "general_archive"
        if document_type not in DOCUMENT_TYPE_LABELS:
            document_type = default_document_type_for_area(classification)
        try:
            add_document_record(
                db,
                title=title,
                classification=classification,
                document_type=document_type,
                status=status,
                document_date=parse_optional_date(document_date),
                source=source,
                entry_channel=entry_channel,
                source_sender=source_sender,
                source_subject=source_subject,
                url_original=url_original,
                url_archive=url_archive,
                plate=task.plate or "",
                vehicle_id=vehicle.id if vehicle else None,
                supplier_name=supplier_name,
                customer_name=task.customer_name or "",
                task_id=task.id,
                workshop_process_id=None,
                notes=notes,
                user_id=user_id,
            )
        except ValueError:
            return RedirectResponse(f"/task-board/{task_id}?error=missing_document_fields", status_code=303)
        db.commit()

    return RedirectResponse(f"/task-board/{task_id}?commented=1", status_code=303)


@web_router.post("/task-board/{task_id}/close")
def task_close(request: Request, task_id: int):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        task_workspace = workspace_for_task_type(task.task_type) if task else "operational"
        current_user = db.get(User, user_id)
        if task and not user_can_access_task_workspace(db, current_user, task_workspace, write=True):
            return RedirectResponse("/task-board", status_code=303)
        if task and not task.closed_at:
            if not can_supervise_task(db, current_user, task):
                return task_update_error_url(task_id, "responsible_required")
            old_status = task.status
            task.status = "closed"
            task.resolved_at = task.resolved_at or datetime.now(UTC)
            task.closed_at = datetime.now(UTC)
            db.add(
                TaskHistory(
                    task_id=task.id,
                    user_id=user_id,
                    field_name="status",
                    old_value=old_status,
                    new_value="closed",
                )
            )
            record_audit(
                db,
                action="task.close",
                entity_type="task",
                entity_id=task.id,
                detail=f"Tarefa fechada: {task.title}",
                user_id=user_id,
            )
            next_recurring_task = create_next_recurring_task(db, task, user_id)
            if next_recurring_task:
                task.recurrence_next_on = next_recurring_task.planned_for
                db.add(
                    TaskHistory(
                        task_id=task.id,
                        user_id=user_id,
                        field_name="Recorrência",
                        old_value=None,
                        new_value=f"Próxima ocorrência CF-TASK-{next_recurring_task.id:05d} planeada para {next_recurring_task.planned_for}",
                    )
                )
            db.commit()

    return RedirectResponse(f"{task_workspace_manage_url(task_workspace)}?closed=1", status_code=303)


@web_router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "next_url": safe_internal_next(request.query_params.get("next")),
        },
    )


@web_router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next_url: str = Form("/"),
):
    clean_next_url = safe_internal_next(next_url)
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == email.strip().lower()))
        if not user or not user.active or not verify_password(password, user.password_hash):
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "error": "Email ou password invalidos.",
                    "next_url": clean_next_url,
                },
                status_code=401,
            )
        request.session["user_id"] = user.id
        record_audit(
            db,
            action="web.login",
            entity_type="user",
            entity_id=user.id,
            detail=f"Login web de {user.email}",
            user_id=user.id,
        )
        db.commit()
    if clean_next_url == "/":
        return RedirectResponse("/choose-experience", status_code=303)
    return RedirectResponse(clean_next_url, status_code=303)


@web_router.get("/choose-experience", response_class=HTMLResponse)
def choose_experience(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if not user:
            return RedirectResponse("/login", status_code=303)
        return templates.TemplateResponse(
            request,
            "choose_experience.html",
            {
                "user": user,
                "can_use_clean": True,
            },
        )


@web_router.get("/switch-experience/{experience}", response_class=HTMLResponse)
def switch_experience(request: Request, experience: str):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    if experience == "clean":
        request.session["carfast_experience"] = "clean"
        return RedirectResponse("/v2-clean", status_code=303)
    request.session["carfast_experience"] = "current"
    return RedirectResponse("/", status_code=303)


def safe_internal_next(value: str | None) -> str:
    clean_value = (value or "/").strip()
    if not clean_value.startswith("/") or clean_value.startswith("//"):
        return "/"
    if clean_value.startswith("/login") or clean_value.startswith("/change-notice"):
        return "/"
    return clean_value


@web_router.get("/change-notice", response_class=HTMLResponse)
def change_notice(request: Request):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "change_notice.html",
        {
            "title": CHANGE_NOTICE_TITLE,
            "notice_title": CHANGE_NOTICE_TITLE,
            "notice_version": CHANGE_NOTICE_VERSION,
            "notice_sections": CHANGE_NOTICE_SECTIONS,
            "next_url": safe_internal_next(request.query_params.get("next")),
        },
    )


@web_router.post("/change-notice", response_class=HTMLResponse)
def confirm_change_notice(
    request: Request,
    next_url: str = Form("/"),
):
    user_id = get_web_user_id(request)
    if not user_id:
        return RedirectResponse("/login", status_code=303)
    request.session[CHANGE_NOTICE_SESSION_KEY] = CHANGE_NOTICE_VERSION
    clean_next_url = safe_internal_next(next_url)
    with SessionLocal() as db:
        record_audit(
            db,
            action="web.change_notice.confirmed",
            entity_type="user",
            entity_id=user_id,
            detail=f"Confirmou leitura do aviso {CHANGE_NOTICE_VERSION}",
            user_id=user_id,
            after_json={
                "notice_version": CHANGE_NOTICE_VERSION,
                "next_url": clean_next_url,
            },
        )
        db.commit()
    return RedirectResponse(clean_next_url, status_code=303)


@web_router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


def get_web_user_id(request: Request) -> int | None:
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if not user_id:
        return None
    return int(user_id)


def web_user_permissions(request: Request) -> set[str]:
    user_id = get_web_user_id(request)
    if not user_id:
        return set()
    cached_permissions = getattr(request.state, "permission_codes", None)
    if cached_permissions is not None:
        return set(cached_permissions)
    with SessionLocal() as db:
        user = db.get(User, user_id)
        permissions = get_user_permission_codes(db, user) if user else set()
    request.state.permission_codes = permissions
    return permissions


def has_any_web_permission(request: Request, *permission_codes: str) -> bool:
    permissions = web_user_permissions(request)
    return bool(permissions.intersection(permission_codes))


def permission_denied_redirect(request: Request) -> RedirectResponse:
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/", status_code=303)


def require_any_web_permission(request: Request, *permission_codes: str) -> RedirectResponse | None:
    if not get_web_user_id(request):
        return RedirectResponse("/login", status_code=303)
    if not has_any_web_permission(request, *permission_codes):
        return RedirectResponse("/", status_code=303)
    return None


templates.env.globals["nav_permissions"] = web_user_permissions
templates.env.globals["nav_has_permission"] = has_any_web_permission


def count_rows(db, model) -> int:
    from sqlalchemy import func

    return db.scalar(select(func.count()).select_from(model)) or 0


def count_open_tasks(db) -> int:
    return db.scalar(select(func.count()).select_from(Task).where(Task.closed_at.is_(None))) or 0


def default_team_id(db, code: str) -> int | None:
    team = db.scalar(select(Team).where(Team.code == code, Team.active.is_(True)))
    return team.id if team else None


def parse_delegation_target(value: str | None) -> tuple[int | None, int | None]:
    clean_value = (value or "").strip()
    if not clean_value:
        return None, None
    target_kind, separator, target_id = clean_value.partition(":")
    if not separator:
        return None, None
    try:
        parsed_id = int(target_id)
    except ValueError:
        return None, None
    if target_kind == "user":
        return parsed_id, None
    if target_kind == "team":
        return None, parsed_id
    return None, None


def format_delegation_target(user_id: int | None, team_id: int | None) -> str:
    if user_id:
        return f"user:{user_id}"
    if team_id:
        return f"team:{team_id}"
    return ""


def task_target_label(db, user_id: int | None, team_id: int | None) -> str:
    if user_id:
        user = db.get(User, user_id)
        return user.name if user else f"Utilizador #{user_id}"
    if team_id:
        team = db.get(Team, team_id)
        return team.name if team else f"Equipa #{team_id}"
    return ""


def add_visible_task_change(changes: list[tuple[str, str, str]], field_name: str, old_value, new_value) -> None:
    old_text = str(old_value or "").strip()
    new_text = str(new_value or "").strip()
    if old_text != new_text:
        changes.append((field_name, old_text, new_text))


TASK_HISTORY_FIELD_LABELS = {
    "status": "Estado",
    "priority": "Prioridade",
    "task_type": "Tipo de tarefa",
    "category": "Classificação",
    "subcategory": "Subcategoria",
    "assigned_to_id": "Responsável",
    "team_id": "Fila / equipa responsável",
    "delegated_to_user_id": "Execução delegada a",
    "delegated_to_team_id": "Equipa delegada",
    "waiting_for_user_id": "A aguardar por",
    "waiting_for_team_id": "A aguardar por equipa",
    "waiting_reason": "Motivo de espera",
    "waiting_reason_detail": "Detalhe do motivo",
    "due_on": "Data limite",
    "department": "Área",
    "station": "Estação",
    "responsible": "Responsável",
    "delegation": "Execução delegada a",
    "waiting_for": "A aguardar por",
}


def assignable_users_for_workspace(users: list[User], workspace: str) -> list[User]:
    clean_workspace = normalize_task_workspace(workspace)
    assignable_users = [
        user
        for user in users
        if user.name.strip().lower() not in TASK_NEVER_ASSIGNMENT_NAMES
    ]
    if clean_workspace == "administration":
        return assignable_users
    return [
        user
        for user in assignable_users
        if user.email.strip().lower() not in TASK_ADMIN_ONLY_ASSIGNMENT_EMAILS
    ]


def is_assignment_allowed_for_workspace(db, user_id: int | None, workspace: str) -> bool:
    if not user_id:
        return True
    user = db.get(User, user_id)
    if not user:
        return False
    if user.name.strip().lower() in TASK_NEVER_ASSIGNMENT_NAMES:
        return False
    if normalize_task_workspace(workspace) == "administration":
        return True
    return user.email.strip().lower() not in TASK_ADMIN_ONLY_ASSIGNMENT_EMAILS


def can_supervise_task(db, user: User | None, task: Task) -> bool:
    if not user:
        return False
    if task.assigned_to_id and task.assigned_to_id == user.id:
        return True
    permissions = get_user_permission_codes(db, user)
    return bool({"admin.manage", "users.manage", "settings.manage"} & permissions)


def task_update_error_url(task_id: int, error: str) -> RedirectResponse:
    return RedirectResponse(f"/task-board/{task_id}?error={error}", status_code=303)


def external_client_key(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()[:80]
    if request.client:
        return request.client.host[:80]
    return "unknown"


def external_portal_rate_limit_allows(client_key: str) -> bool:
    now = monotonic()
    window_start = now - EXTERNAL_PORTAL_RATE_LIMIT_WINDOW_SECONDS
    recent_requests = [
        timestamp for timestamp in EXTERNAL_PORTAL_RATE_LIMIT.get(client_key, []) if timestamp >= window_start
    ]
    if len(recent_requests) >= EXTERNAL_PORTAL_RATE_LIMIT_MAX_REQUESTS:
        EXTERNAL_PORTAL_RATE_LIMIT[client_key] = recent_requests
        return False
    recent_requests.append(now)
    EXTERNAL_PORTAL_RATE_LIMIT[client_key] = recent_requests
    return True


def build_external_portal_description(*, message: str, category: str, station: str) -> str:
    lines = [
        "Pedido recebido através do portal externo.",
        f"Tipo de pedido: {EXTERNAL_PORTAL_CATEGORY_LABELS.get(category, category)}",
    ]
    if station.strip():
        lines.append(f"Estação indicada: {station.strip()}")
    lines.extend(["", message.strip()])
    return "\n".join(lines)[:5000]


def default_document_type_for_area(area: str) -> str:
    return {
        "workshop": "workshop_evidence",
        "fleet": "maintenance_plan",
        "finance": "finance_other",
        "rentway_imports": "general_rentway",
        "general_archive": "general_archive",
    }.get(area, "workshop_other")


def normalize_document_type_for_area(document_type: str, area: str) -> str:
    if document_type not in DOCUMENT_TYPE_LABELS:
        return default_document_type_for_area(area)
    expected_area = DOCUMENT_TYPE_AREAS.get(document_type)
    if expected_area and expected_area != area:
        return default_document_type_for_area(area)
    return document_type


def document_folder_label(document_type: str | None) -> str:
    labels = {
        "workshop_photo": "Fotos",
        "workshop_diagnostic": "Diagnóstico",
        "workshop_bsi": "BSI - Dados técnicos",
        "workshop_work_order": "Folhas de obra",
        "workshop_quote": "Orçamentos",
        "workshop_supplier_invoice": "Faturas fornecedor",
        "workshop_evidence": "Evidências",
        "workshop_report": "Relatórios técnicos",
        "workshop_other": "Outros documentos de oficina",
        "maintenance_plan": "Planos de manutenção",
        "finance_supplier_invoice": "Faturas fornecedor",
        "finance_credit_note": "Notas de crédito",
        "finance_receipt": "Recibos",
        "finance_payment_proof": "Comprovativos pagamento",
        "finance_customer_document": "Documentos cliente",
        "finance_other": "Outros documentos financeiros",
        "general_fleet": "Geral Frota",
        "general_finance": "Geral Financeiro",
        "general_archive": "Geral Arquivo",
    }
    return labels.get(document_type or "", DOCUMENT_TYPE_LABELS.get(document_type or "", "Outros"))


def task_detail_error_message(error: str | None) -> str | None:
    if error == "missing_destination":
        return "Escolhe uma pessoa responsável ou uma equipa/fila."
    if error == "missing_document_fields":
        return "Indica título e pelo menos um link para associar o documento."
    if error == "delegation_required":
        return "Para colocar em execução delegada, seleciona primeiro quem executa por delegação."
    if error == "waiting_reason_required":
        return "Para colocar a tarefa a aguardar, seleciona o motivo."
    if error == "waiting_reason_detail_required":
        return "Quando o motivo é outro, descreve o motivo em texto."
    if error == "responsible_required":
        return "Este estado só pode ser colocado pelo responsável da tarefa ou por um perfil autorizado."
    if error == "delegation_not_allowed":
        return "Só o responsável da tarefa ou um perfil autorizado pode delegar a execução."
    if error == "assignment_not_allowed":
        return "Este utilizador só pode ser responsável ou delegado em tarefas de Administração."
    return None


def add_document_record(
    db,
    *,
    title: str,
    classification: str,
    document_type: str,
    status: str,
    document_date: date | None,
    source: str,
    entry_channel: str,
    source_sender: str,
    source_subject: str,
    url_original: str,
    url_archive: str,
    plate: str,
    vehicle_id: int | None,
    supplier_name: str,
    customer_name: str,
    task_id: int | None,
    workshop_process_id: int | None,
    notes: str,
    user_id: int,
    folder_path_override: str | None = None,
) -> Document:
    clean_title = title.strip()
    clean_original_url = url_original.strip()
    clean_archive_url = url_archive.strip()
    if not clean_title or not (clean_original_url or clean_archive_url):
        raise ValueError("title_and_link_required")
    if classification not in DOCUMENT_AREA_LABELS:
        classification = "workshop"
    document_type = normalize_document_type_for_area(document_type, classification)
    if status not in DOCUMENT_STATUS_LABELS:
        status = "received"

    clean_plate = plate.strip().upper()
    archived = status == "archived"
    linked_vehicle = db.get(Vehicle, vehicle_id) if vehicle_id else None
    linked_process = db.get(WorkshopProcess, workshop_process_id) if workshop_process_id else None
    if not linked_vehicle and linked_process and linked_process.vehicle_id:
        linked_vehicle = db.get(Vehicle, linked_process.vehicle_id)
    linked_vehicle_id = vehicle_id or (linked_vehicle.id if linked_vehicle else None)
    effective_plate = clean_plate or (linked_vehicle.plate if linked_vehicle and linked_vehicle.plate else "")
    process_folder_ref = linked_process.document_folder_path.split("/")[-1] if linked_process and linked_process.document_folder_path else None
    document = Document(
        title=clean_title,
        document_type=document_type,
        classification=classification,
        status=status,
        source=source.strip() or None,
        entry_channel=entry_channel.strip() or None,
        source_sender=source_sender.strip() or None,
        source_subject=source_subject.strip() or None,
        original_name=clean_title[:255],
        file_name=clean_title[:255],
        file_type=None,
        file_size=None,
        storage_provider="sharepoint",
        storage_path=clean_original_url or clean_archive_url,
        storage_key=clean_original_url or None,
        external_url=clean_archive_url or clean_original_url,
        folder_path=folder_path_override or suggest_document_folder_path(
            classification,
            document_date,
            effective_plate,
            document_type,
            supplier_name,
            customer_name,
            vin=linked_vehicle.vin if linked_vehicle else None,
            workshop_process_ref=process_folder_ref,
        ),
        vehicle_id=linked_vehicle_id,
        task_id=task_id,
        workshop_process_id=workshop_process_id,
        plate=effective_plate or None,
        customer_name=customer_name.strip() or None,
        supplier_name=supplier_name.strip() or None,
        document_date=document_date,
        uploaded_by_id=user_id,
        archived_by_id=user_id if archived else None,
        archived_at=datetime.now(UTC) if archived else None,
        archived=archived,
    )
    db.add(document)
    db.flush()
    if notes.strip():
        db.add(
            DocumentEvent(
                document_id=document.id,
                action="note",
                old_value=None,
                new_value=notes.strip(),
                user_id=user_id,
            )
        )
    db.add(
        DocumentEvent(
            document_id=document.id,
            action="created",
            old_value=None,
            new_value=f"Documento criado em {DOCUMENT_AREA_LABELS[classification]}",
            user_id=user_id,
        )
    )
    record_audit(
        db,
        action="document.created",
        entity_type="document",
        entity_id=document.id,
        detail=f"Documento registado: {document.title}",
        after_json={
            "classification": classification,
            "document_type": document_type,
            "status": status,
            "folder_path": document.folder_path,
            "task_id": task_id,
            "workshop_process_id": workshop_process_id,
            "vehicle_id": vehicle_id,
        },
        user_id=user_id,
    )
    return document


def suggest_document_folder_path(
    area: str,
    document_date: date | None,
    plate: str | None = None,
    document_type: str | None = None,
    supplier_name: str | None = None,
    customer_name: str | None = None,
    *,
    vin: str | None = None,
    workshop_process_ref: str | None = None,
) -> str:
    reference_date = document_date or date.today()
    year = f"{reference_date.year:04d}"
    clean_plate = (plate or "").strip().upper()
    base_vehicle_folder = vehicle_archive_base_folder(clean_plate, vin)
    process_ref = sanitize_archive_component(workshop_process_ref, "Sem_Processo")
    normalized_type = (document_type or "").strip().lower()

    if normalized_type in {"maintenance_plan", "service_plan", "plano_manutencao"}:
        return f"{base_vehicle_folder}/03_Documentacao_Base_Viatura/Plano_Manutencao"

    if normalized_type in {"finance_supplier_invoice", "workshop_supplier_invoice"}:
        return f"{base_vehicle_folder}/01_Documentacao_Financeira/Faturas"
    if normalized_type == "finance_credit_note":
        return f"{base_vehicle_folder}/01_Documentacao_Financeira/Notas_Credito"
    if normalized_type in {"finance_receipt", "finance_payment_proof", "workshop_evidence"}:
        return f"{base_vehicle_folder}/01_Documentacao_Financeira/Comprovativos"

    if normalized_type in {"workshop_diagnostic", "workshop_bsi", "workshop_report", "technical_report", "bsi", "lubrication", "telecharge"}:
        return f"{base_vehicle_folder}/02_Documentacao_Tecnica/Processos/{process_ref}/01_Diagnosticos"
    if normalized_type in {"service_box", "tsb"}:
        return f"{base_vehicle_folder}/02_Documentacao_Tecnica/Processos/{process_ref}/02_Service_Box_TSB"
    if normalized_type in {"workshop_photo"}:
        return f"{base_vehicle_folder}/02_Documentacao_Tecnica/Processos/{process_ref}/03_Fotos_Evidencias"
    if normalized_type in {"workshop_other", "workshop_quote"}:
        return f"{base_vehicle_folder}/02_Documentacao_Tecnica/Processos/{process_ref}/04_Outros_Processo"

    if area in {"workshop", "fleet"}:
        return f"{base_vehicle_folder}/03_Documentacao_Base_Viatura/Documentacao_Viatura"
    if area == "finance":
        if supplier_name and supplier_name.strip():
            return f"{base_vehicle_folder}/01_Documentacao_Financeira/Faturas"
        if customer_name and customer_name.strip():
            return f"{base_vehicle_folder}/03_Documentacao_Base_Viatura/Documentacao_Viatura"
        return f"{base_vehicle_folder}/01_Documentacao_Financeira/Comprovativos"
    if area == "rentway_imports":
        return "Importacoes_Estruturadas/Arquivo_Original_Importacoes"
    return f"{base_vehicle_folder}/99_Pendentes_Classificar"


def parse_optional_date(value: str | None) -> date | None:
    if not value or not value.strip():
        return None
    return date.fromisoformat(value.strip())


def parse_optional_int(value: str | None) -> int | None:
    if not value or not value.strip():
        return None
    return int(value.strip())


def add_query_flag(url: str, key: str, value: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{key}={value}"
