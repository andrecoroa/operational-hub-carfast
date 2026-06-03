import csv
import hashlib
import io
import json
import shutil
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.imports import ImportBatch, ImportError, ImportFile, ImportRawRow
from app.models.tasks import Task, TaskHistory
from app.services.audit import record_audit
from app.services.spreadsheets import (
    build_column_lookup,
    clean_text,
    excel_date_to_iso,
    first_row_value,
    iter_xlsx_rows,
    normalize_header,
)


TASK_BULK_IMPORT_TYPE = "task_bulk"
TASK_BULK_SOURCE_SYSTEM = "carfast_imports"
TASK_BULK_STORAGE_DIR = Path("data/imports/task_bulk")

TASK_BULK_FIELDS = [
    ("subject", "Assunto"),
    ("description", "Descrição"),
    ("category", "Classificação"),
    ("subcategory", "Subclassificação"),
    ("priority", "Prioridade"),
    ("responsible", "Responsável"),
    ("delegated_to", "Execução delegada a"),
    ("plate", "Matrícula"),
    ("customer", "Cliente"),
    ("contact", "Contacto"),
    ("email", "Email"),
    ("phone", "Telefone"),
    ("reservation", "Reserva"),
    ("contract", "Contrato"),
    ("station", "Estação"),
    ("due_on", "Data limite"),
    ("external_id", "ID externo"),
    ("observations", "Observações"),
]

FIELD_ALIASES = {
    "subject": ["assunto", "titulo", "título", "title", "subject", "tarefa"],
    "description": ["descricao", "descrição", "description", "detalhe"],
    "category": ["classificacao", "classificação", "categoria", "category"],
    "subcategory": ["subclassificacao", "subclassificação", "subcategoria", "subcategory"],
    "priority": ["prioridade", "priority"],
    "responsible": ["responsavel", "responsável", "assigned_to", "owner"],
    "delegated_to": ["execucao_delegada_a", "execução_delegada_a", "delegado", "delegated_to"],
    "plate": ["matricula", "matrícula", "plate", "platenr"],
    "customer": ["cliente", "customer", "customer_name"],
    "contact": ["contacto", "contato", "contact", "customer_contact"],
    "email": ["email", "e-mail", "customer_email"],
    "phone": ["telefone", "phone", "telemovel", "telemóvel"],
    "reservation": ["reserva", "reservation", "reservation_number"],
    "contract": ["contrato", "contract", "contract_number"],
    "station": ["estacao", "estação", "station"],
    "due_on": ["data_limite", "data limite", "due_on", "sla", "deadline"],
    "external_id": ["id_externo", "id externo", "external_id", "external_source_id", "cf_external_id"],
    "observations": ["observacoes", "observações", "notas", "notes", "observations"],
}

PRIORITY_ALIASES = {
    "normal": "normal",
    "media": "normal",
    "média": "normal",
    "alta": "high",
    "high": "high",
    "urgente": "urgent",
    "urgent": "urgent",
}

CATEGORY_ALIASES = {
    "suporte": "support",
    "support": "support",
    "operacoes": "operations",
    "operações": "operations",
    "operations": "operations",
    "oficina": "workshop",
    "workshop": "workshop",
    "outro": "other",
    "other": "other",
}


def task_bulk_storage_root() -> Path:
    TASK_BULK_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    return TASK_BULK_STORAGE_DIR


def store_task_bulk_upload(source_path: Path, original_name: str) -> Path:
    suffix = source_path.suffix.lower()
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in original_name)[:120]
    target = task_bulk_storage_root() / "pending" / f"{timestamp}_{safe_name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target)
    return target


def iter_task_import_rows(path: str | Path):
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


def detect_mapping(headers: list[str]) -> dict[str, str]:
    normalized = {normalize_header(header): header for header in headers if header}
    mapping: dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            matched = normalized.get(normalize_header(alias))
            if matched:
                mapping[field] = matched
                break
    return mapping


def mapped_value(row: tuple[Any, ...], col: dict[str, int], mapping: dict[str, str], field: str) -> str:
    header = mapping.get(field)
    if not header:
        return ""
    return clean_text(first_row_value(row, col, [header])) or ""


def parse_task_date(value: str) -> date | None:
    iso = excel_date_to_iso(value)
    if not iso:
        return None
    try:
        return date.fromisoformat(iso[:10])
    except ValueError:
        return None


def normalize_category(value: str, default_category: str) -> str:
    if not value.strip():
        return default_category
    return CATEGORY_ALIASES.get(value.strip().casefold(), default_category)


def normalize_priority(value: str, default_priority: str) -> str:
    if not value.strip():
        return default_priority
    return PRIORITY_ALIASES.get(value.strip().casefold(), default_priority)


def normalize_plate(value: str) -> str:
    return value.strip().upper().replace(" ", "")


def row_hash(raw: dict[str, Any]) -> str:
    raw_json = json.dumps(raw, ensure_ascii=False, default=str, sort_keys=True)
    return hashlib.sha1(raw_json.encode("utf-8")).hexdigest()


def duplicate_query(payload: dict[str, Any], parent_task_id: int | None):
    external_id = payload.get("external_id")
    if external_id:
        return select(Task).where(Task.external_source_id == external_id, Task.closed_at.is_(None))
    title = payload.get("title") or ""
    plate = payload.get("plate") or None
    contract = payload.get("contract_number") or None
    reservation = payload.get("reservation_number") or None
    conditions = [Task.title == title, Task.closed_at.is_(None)]
    if parent_task_id:
        conditions.append(Task.parent_task_id == parent_task_id)
    if plate:
        conditions.append(Task.plate == plate)
    if contract or reservation:
        conditions.append(or_(Task.contract_number == contract, Task.reservation_number == reservation))
    return select(Task).where(*conditions)


def build_task_payload(
    row: tuple[Any, ...],
    col: dict[str, int],
    mapping: dict[str, str],
    defaults: dict[str, Any],
) -> dict[str, Any]:
    description = mapped_value(row, col, mapping, "description")
    observations = mapped_value(row, col, mapping, "observations")
    category = normalize_category(mapped_value(row, col, mapping, "category"), defaults["category"])
    priority = normalize_priority(mapped_value(row, col, mapping, "priority"), defaults["priority"])
    due_on = parse_task_date(mapped_value(row, col, mapping, "due_on")) or defaults.get("due_on")
    title = mapped_value(row, col, mapping, "subject")
    return {
        "title": title,
        "description": description or observations,
        "category": category,
        "subcategory": mapped_value(row, col, mapping, "subcategory") or defaults["subcategory"],
        "priority": priority,
        "plate": normalize_plate(mapped_value(row, col, mapping, "plate")) or None,
        "customer_name": mapped_value(row, col, mapping, "customer") or None,
        "customer_contact": mapped_value(row, col, mapping, "contact") or None,
        "customer_email": (mapped_value(row, col, mapping, "email") or "").lower() or None,
        "customer_phone": mapped_value(row, col, mapping, "phone") or None,
        "reservation_number": mapped_value(row, col, mapping, "reservation") or None,
        "contract_number": mapped_value(row, col, mapping, "contract") or None,
        "station": mapped_value(row, col, mapping, "station") or None,
        "external_id": mapped_value(row, col, mapping, "external_id") or None,
        "responsible_label": mapped_value(row, col, mapping, "responsible") or defaults.get("responsible_label") or "",
        "due_on": due_on,
    }


def validate_task_payload(payload: dict[str, Any], valid_categories: set[str]) -> list[str]:
    errors = []
    if not payload["title"]:
        errors.append("Assunto em falta.")
    if not payload["description"]:
        errors.append("Descrição ou observações em falta.")
    if payload["category"] not in valid_categories:
        errors.append("Classificação inválida.")
    return errors


def preview_task_bulk_import(
    db: Session,
    path: str | Path,
    defaults: dict[str, Any],
    *,
    parent_task_id: int | None,
    valid_categories: set[str],
) -> dict[str, Any]:
    rows = []
    headers: list[str] = []
    sheet_name = ""
    mapping: dict[str, str] = {}
    seen_external_ids: set[str] = set()
    seen_combo_keys: set[tuple[str, str | None, str | None, str | None]] = set()
    groups = {"category": Counter(), "responsible": Counter(), "priority": Counter()}

    for sheet_name, headers, row_number, row, raw in iter_task_import_rows(path):
        if not mapping:
            mapping = detect_mapping(headers)
        col = build_column_lookup(headers)
        payload = build_task_payload(row, col, mapping, defaults)
        errors = validate_task_payload(payload, valid_categories)
        warnings = []
        duplicate = False
        external_id = payload.get("external_id")
        combo_key = (
            (payload.get("title") or "").casefold(),
            payload.get("plate"),
            payload.get("contract_number"),
            payload.get("reservation_number"),
        )
        if external_id and external_id in seen_external_ids:
            duplicate = True
            warnings.append("ID externo repetido no ficheiro.")
        elif combo_key in seen_combo_keys:
            duplicate = True
            warnings.append("Possível duplicado dentro do ficheiro.")
        elif db.scalar(duplicate_query(payload, parent_task_id)):
            duplicate = True
            warnings.append("Possível duplicado já existente.")
        if external_id:
            seen_external_ids.add(external_id)
        seen_combo_keys.add(combo_key)
        if errors:
            state = "error"
        elif duplicate:
            state = "duplicate"
        else:
            state = "valid"
        if state == "valid":
            groups["category"][payload["category"]] += 1
            groups["responsible"][payload.get("responsible_label") or "Por atribuir"] += 1
            groups["priority"][payload["priority"]] += 1
        rows.append(
            {
                "row_number": row_number,
                "raw": raw,
                "hash": row_hash(raw),
                "payload": payload,
                "state": state,
                "message": "; ".join(errors or warnings),
            }
        )

    total = len(rows)
    valid = sum(1 for item in rows if item["state"] == "valid")
    errors = sum(1 for item in rows if item["state"] == "error")
    duplicates = sum(1 for item in rows if item["state"] == "duplicate")
    return {
        "sheet_name": sheet_name,
        "headers": headers,
        "mapping": mapping,
        "rows": rows,
        "summary": {
            "total": total,
            "valid": valid,
            "errors": errors,
            "duplicates": duplicates,
            "subtasks": valid,
        },
        "groups": {
            "category": groups["category"].most_common(),
            "responsible": groups["responsible"].most_common(),
            "priority": groups["priority"].most_common(),
        },
    }


def create_tasks_from_bulk_import(
    db: Session,
    path: str | Path,
    original_name: str,
    defaults: dict[str, Any],
    *,
    mode: str,
    parent_task_id: int | None,
    parent_title: str,
    valid_categories: set[str],
    user_id: int | None,
) -> dict[str, Any]:
    preview = preview_task_bulk_import(
        db,
        path,
        defaults,
        parent_task_id=parent_task_id,
        valid_categories=valid_categories,
    )
    batch = ImportBatch(
        source_system=TASK_BULK_SOURCE_SYSTEM,
        import_type=TASK_BULK_IMPORT_TYPE,
        status="running",
        imported_by_id=user_id,
        total_rows=preview["summary"]["total"],
        detail="Importação de tarefas em massa.",
    )
    db.add(batch)
    db.flush()

    stored_path = task_bulk_storage_root() / f"batch_{batch.id}_{Path(path).name}"
    shutil.copyfile(path, stored_path)
    db.add(
        ImportFile(
            batch_id=batch.id,
            original_name=original_name,
            file_name=stored_path.name,
            storage_path=str(stored_path),
            sheet_name=preview["sheet_name"],
            columns_json=preview["headers"],
        )
    )

    parent_task = db.get(Task, parent_task_id) if parent_task_id else None
    if mode == "create":
        parent_task = Task(
            title=parent_title.strip(),
            description=f"Tarefa mãe criada por importação em massa. Lote #{batch.id}.",
            task_type=defaults["task_type"],
            source="external",
            category=defaults["category"],
            subcategory=defaults["subcategory"],
            status="new",
            priority=defaults["priority"],
            assigned_to_id=defaults.get("assigned_to_id"),
            delegated_to_user_id=defaults.get("delegated_to_user_id"),
            delegated_to_team_id=defaults.get("delegated_to_team_id"),
            created_by_id=user_id,
            due_on=defaults.get("due_on"),
            entity_type="import_batch",
            entity_id=str(batch.id),
            external_source_id=f"task_bulk_batch:{batch.id}:parent",
        )
        db.add(parent_task)
        db.flush()
        db.add(TaskHistory(task_id=parent_task.id, user_id=user_id, field_name="status", old_value=None, new_value="new"))
    if not parent_task:
        raise ValueError("Tarefa mãe não encontrada.")

    created_tasks: list[Task] = []
    skipped_rows = 0
    error_rows = 0
    for item in preview["rows"]:
        raw = item["raw"]
        payload = item["payload"]
        db.add(
            ImportRawRow(
                batch_id=batch.id,
                row_number=item["row_number"],
                external_reference=payload.get("external_id") or payload.get("plate"),
                raw_json=raw,
                row_hash=item["hash"],
            )
        )
        if item["state"] == "error":
            error_rows += 1
            db.add(
                ImportError(
                    batch_id=batch.id,
                    row_number=item["row_number"],
                    entity_type="task",
                    error_message=item["message"],
                    raw_json=raw,
                )
            )
            continue
        if item["state"] == "duplicate":
            skipped_rows += 1
            db.add(
                ImportError(
                    batch_id=batch.id,
                    row_number=item["row_number"],
                    entity_type="task_duplicate",
                    error_message=item["message"] or "Possível duplicado ignorado.",
                    raw_json=raw,
                )
            )
            continue
        task = Task(
            title=payload["title"],
            description=payload["description"],
            task_type=parent_task.task_type,
            source="external",
            category=payload["category"],
            subcategory=payload["subcategory"],
            status="new",
            priority=payload["priority"],
            customer_name=payload["customer_name"],
            customer_contact=payload["customer_contact"],
            customer_email=payload["customer_email"],
            customer_phone=payload["customer_phone"],
            plate=payload["plate"],
            reservation_number=payload["reservation_number"],
            contract_number=payload["contract_number"],
            station=payload["station"],
            external_source_id=payload["external_id"],
            parent_task_id=parent_task.id,
            assigned_to_id=defaults.get("assigned_to_id"),
            delegated_to_user_id=defaults.get("delegated_to_user_id"),
            delegated_to_team_id=defaults.get("delegated_to_team_id"),
            created_by_id=user_id,
            due_on=payload["due_on"],
            entity_type="import_batch",
            entity_id=str(batch.id),
        )
        db.add(task)
        db.flush()
        db.add(TaskHistory(task_id=task.id, user_id=user_id, field_name="status", old_value=None, new_value="new"))
        created_tasks.append(task)

    db.add(
        TaskHistory(
            task_id=parent_task.id,
            user_id=user_id,
            field_name="Importação em massa",
            old_value=None,
            new_value=f"Lote #{batch.id}: {len(created_tasks)} subtarefas criadas.",
        )
    )
    batch.status = "completed" if error_rows == 0 else "completed_with_errors"
    batch.created_rows = len(created_tasks)
    batch.updated_rows = 0
    batch.skipped_rows = skipped_rows
    batch.error_rows = error_rows
    batch.finished_at = datetime.now(UTC)
    batch.detail = f"Tarefa mãe CF-TASK-{parent_task.id:05d}; {len(created_tasks)} subtarefas criadas."
    record_audit(
        db,
        action="import.task_bulk.completed",
        entity_type="import_batch",
        entity_id=batch.id,
        detail=batch.detail,
        after_json={
            "parent_task_id": parent_task.id,
            "created_task_ids": [task.id for task in created_tasks],
            "skipped_rows": skipped_rows,
            "error_rows": error_rows,
        },
        user_id=user_id,
    )
    db.commit()
    return {
        "batch_id": batch.id,
        "parent_task_id": parent_task.id,
        "created_rows": len(created_tasks),
        "skipped_rows": skipped_rows,
        "error_rows": error_rows,
    }
