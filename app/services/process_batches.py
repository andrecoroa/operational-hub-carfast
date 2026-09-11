from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.case_workflow import ProcessPhaseInstance
from app.models.imports import (
    ProcessBatch,
    ProcessBatchRow,
    ProcessBatchRowComment,
    ProcessBatchTaskRow,
)
from app.models.task_templates import ProcessInstance, ProcessModelVersion
from app.models.tasks import Task, TaskCase, TaskComment, TaskHistory
from app.services.case_workflow import WorkflowError, audit, create_case, require_case_action

BATCH_PROCESS_DEFINITION = {
    "code": "batch-data-treatment",
    "name": "Tratamento de dados em lote",
    "kind": "batch_data_treatment",
    "phases": [
        {"key": "upload", "title": "Carregar ficheiro"},
        {"key": "mapping", "title": "Mapear campos"},
        {"key": "validation", "title": "Validar lote"},
        {"key": "execution", "title": "Criar e tratar tarefas"},
        {"key": "closure", "title": "Encerrar caso"},
    ],
}


def compose_description(source: dict[str, Any], mapping: dict[str, str]) -> str | None:
    """Compose description_1..N in declared order, ignoring blank source cells."""
    numbered: list[tuple[int, str]] = []
    for source_column, target in mapping.items():
        if not target.startswith("description_"):
            continue
        try:
            order = int(target.removeprefix("description_"))
        except ValueError:
            continue
        value = str(source.get(source_column) or "").strip()
        if value:
            numbered.append((order, value))
    numbered.sort(key=lambda item: item[0])
    return "\n\n".join(value for _, value in numbered) or None


def create_batch_process(
    db: Session,
    *,
    model_version: ProcessModelVersion,
    title: str,
    organizational_unit_id: int,
    actor_id: int,
    description: str | None = None,
) -> tuple[Any, ProcessInstance]:
    if model_version.status != "published":
        raise WorkflowError("A published batch process model is required")
    definition = model_version.definition_json or {}
    if definition.get("kind") != "batch_data_treatment":
        raise WorkflowError("Process model does not support batch treatment")
    case = create_case(
        db,
        title=title,
        description=description,
        organizational_unit_id=organizational_unit_id,
        actor_id=actor_id,
    )
    require_case_action(db, actor_id, case, "execute")
    process = ProcessInstance(
        case_id=case.id,
        model_version_id=model_version.id,
        model_snapshot_json=definition,
        model_snapshot_digest=model_version.definition_digest,
        title=title,
        status="active",
        source="manual",
        context_json={"batch_count": 0},
        created_by_id=actor_id,
        process_kind="batch_data_treatment",
        revision=1,
    )
    db.add(process)
    db.flush()
    for index, phase in enumerate(definition.get("phases", []), start=1):
        db.add(
            ProcessPhaseInstance(
                process_instance_id=process.id,
                phase_key=phase["key"],
                title=phase.get("title") or phase["key"],
                sort_order=phase.get("sort_order", index),
                definition_snapshot_json=phase,
                status="active" if index == 1 else "pending",
                execution_mode="direct",
                revision=1,
            )
        )
    audit(db, "process", process.id, "batch_process.created", actor_id, process.revision)
    return case, process


def add_batch(
    db: Session,
    *,
    process: ProcessInstance,
    name: str,
    mapping: dict[str, str],
    rows: Iterable[dict[str, Any]],
    actor_id: int,
    import_file_id: int | None = None,
) -> ProcessBatch:
    case = process.case_id and db.get(TaskCase, process.case_id)
    if not case:
        raise WorkflowError("Process case not found")
    require_case_action(db, actor_id, case, "execute")
    if process.process_kind != "batch_data_treatment" or process.status != "active":
        raise WorkflowError("Process does not accept batches")
    batch = ProcessBatch(
        case_id=case.id,
        process_instance_id=process.id,
        import_file_id=import_file_id,
        name=name.strip()[:200] or "Lote sem nome",
        status="validated",
        mapping_json=mapping,
        created_by_id=actor_id,
    )
    db.add(batch)
    db.flush()
    title_column = next((column for column, target in mapping.items() if target == "title"), None)
    key_column = next((column for column, target in mapping.items() if target == "row_key"), None)
    for row_number, source in enumerate(rows, start=2):
        title = str(source.get(title_column) or "").strip() if title_column else ""
        description = compose_description(source, mapping)
        status = "ready" if title else "error"
        db.add(
            ProcessBatchRow(
                batch_id=batch.id,
                row_number=row_number,
                row_key=(str(source.get(key_column) or "").strip() or None) if key_column else None,
                source_json=source,
                treatment_json={},
                title=title[:200] or f"Linha {row_number}",
                description=description,
                status=status,
                revision=1,
            )
        )
    process.context_json = {
        **(process.context_json or {}),
        "batch_count": int((process.context_json or {}).get("batch_count", 0)) + 1,
    }
    process.revision += 1
    audit(db, "process_batch", batch.id, "batch.created", actor_id)
    return batch


def create_task_for_rows(
    db: Session,
    *,
    batch_id: int,
    row_ids: list[int],
    title: str,
    actor_id: int,
    assigned_to_id: int | None = None,
    due_on: date | None = None,
    priority: str = "normal",
) -> Task:
    if not row_ids:
        raise WorkflowError("Select at least one batch row")
    batch = db.get(ProcessBatch, batch_id)
    if not batch or batch.status in {"completed", "cancelled"}:
        raise WorkflowError("Batch is not active")
    case = db.get(TaskCase, batch.case_id)
    require_case_action(db, actor_id, case, "execute")
    rows = db.scalars(
        select(ProcessBatchRow)
        .where(ProcessBatchRow.id.in_(set(row_ids)), ProcessBatchRow.batch_id == batch.id)
        .with_for_update()
    ).all()
    if len(rows) != len(set(row_ids)):
        raise WorkflowError("One or more rows do not belong to the batch")
    occupied = db.scalar(
        select(func.count(ProcessBatchTaskRow.id)).where(
            ProcessBatchTaskRow.batch_row_id.in_([row.id for row in rows])
        )
    )
    if occupied:
        raise WorkflowError("One or more rows already belong to a task")
    if any(row.status not in {"ready", "pending"} for row in rows):
        raise WorkflowError("Only pending or ready rows can be assigned")
    task = Task(
        case_id=case.id,
        title=title.strip()[:200] or f"Tratar {len(rows)} linhas",
        description=f"Tratamento de {len(rows)} linhas do lote {batch.name}.",
        task_type="process_task",
        source="process",
        status="new",
        priority=priority,
        assigned_to_id=assigned_to_id,
        created_by_id=actor_id,
        due_on=due_on,
        process_instance_id=batch.process_instance_id,
        process_step_code="execution",
        entity_type="process_batch",
        entity_id=str(batch.id),
    )
    db.add(task)
    db.flush()
    for row in rows:
        row.status = "in_progress"
        row.revision += 1
        db.add(ProcessBatchTaskRow(task_id=task.id, batch_row_id=row.id, linked_by_id=actor_id))
    db.flush()
    batch.status = "in_progress"
    db.add(
        TaskHistory(
            task_id=task.id, user_id=actor_id, field_name="status", old_value=None, new_value="new"
        )
    )
    audit(
        db,
        "process_batch",
        batch.id,
        "batch.task.created",
        actor_id,
        after={"task_id": task.id, "row_ids": row_ids},
    )
    return task


def update_batch_row(
    db: Session,
    *,
    row_id: int,
    expected_revision: int,
    actor_id: int,
    status: str,
    treatment: dict[str, Any] | None = None,
) -> ProcessBatchRow:
    row = db.scalar(select(ProcessBatchRow).where(ProcessBatchRow.id == row_id).with_for_update())
    if not row or row.revision != expected_revision:
        raise WorkflowError("Batch row is missing or stale")
    batch = db.get(ProcessBatch, row.batch_id)
    case = db.get(TaskCase, batch.case_id)
    require_case_action(db, actor_id, case, "execute")
    if status not in {"ready", "in_progress", "completed", "excluded", "error"}:
        raise WorkflowError("Invalid batch row status")
    row.status = status
    row.treatment_json = treatment or row.treatment_json or {}
    row.revision += 1
    db.flush()
    link = db.scalar(select(ProcessBatchTaskRow).where(ProcessBatchTaskRow.batch_row_id == row.id))
    if link:
        remaining = db.scalar(
            select(func.count(ProcessBatchRow.id))
            .join(ProcessBatchTaskRow, ProcessBatchTaskRow.batch_row_id == ProcessBatchRow.id)
            .where(
                ProcessBatchTaskRow.task_id == link.task_id,
                ~ProcessBatchRow.status.in_({"completed", "excluded"}),
            )
        )
        if not remaining:
            task = db.get(Task, link.task_id)
            task.status = "completed"
            task.resolved_at = datetime.now(UTC)
    batch_remaining = db.scalar(
        select(func.count(ProcessBatchRow.id)).where(
            ProcessBatchRow.batch_id == batch.id,
            ~ProcessBatchRow.status.in_({"completed", "excluded"}),
        )
    )
    if not batch_remaining:
        batch.status = "completed"
    return row


def add_row_comment(
    db: Session, *, row_id: int, actor_id: int, comment: str
) -> ProcessBatchRowComment:
    clean = comment.strip()
    if not clean:
        raise WorkflowError("Comment is required")
    row = db.get(ProcessBatchRow, row_id)
    if not row:
        raise WorkflowError("Batch row not found")
    batch = db.get(ProcessBatch, row.batch_id)
    case = db.get(TaskCase, batch.case_id)
    require_case_action(db, actor_id, case, "execute")
    link = db.scalar(select(ProcessBatchTaskRow).where(ProcessBatchTaskRow.batch_row_id == row.id))
    task_id = link.task_id if link else None
    row_comment = ProcessBatchRowComment(
        batch_row_id=row.id, task_id=task_id, user_id=actor_id, comment=clean
    )
    db.add(row_comment)
    if task_id:
        db.add(TaskComment(task_id=task_id, user_id=actor_id, comment=f"[{row.title}] {clean}"))
    return row_comment


def mirror_task_comment_to_rows(
    db: Session, *, task_id: int, actor_id: int, comment: str
) -> list[ProcessBatchRowComment]:
    """Expose a task-level comment in every row grouped by that task."""
    clean = comment.strip()
    if not clean:
        return []
    row_ids = list(
        db.scalars(
            select(ProcessBatchTaskRow.batch_row_id).where(ProcessBatchTaskRow.task_id == task_id)
        )
    )
    mirrored = [
        ProcessBatchRowComment(
            batch_row_id=row_id,
            task_id=task_id,
            user_id=actor_id,
            comment=clean,
        )
        for row_id in row_ids
    ]
    db.add_all(mirrored)
    return mirrored
