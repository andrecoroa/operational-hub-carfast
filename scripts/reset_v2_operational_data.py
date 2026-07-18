from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


V2_DOCUMENT_SOURCES = {"v2_clean_manual", "workshop_v2_clean"}
V2_DOCUMENT_ENTRY_CHANNELS = {"structured_import", "v2_clean", "upload"}
V2_TASK_SOURCES = {"v2_clean", "workshop_v2_clean"}
V2_TASK_ENTITY_TYPES = {"workshop_phased_process", "workshop_phased_technical_report"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Audita e limpa dados operacionais da experiencia v2. "
            "Por defeito faz apenas dry-run."
        )
    )
    parser.add_argument(
        "--database-url",
        help="DATABASE_URL alvo. Se omitido, usa a configuracao/env atual.",
    )
    parser.add_argument(
        "--snapshot-file",
        help="Caminho JSON para guardar auditoria antes/depois.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Executa o reset. Sem esta flag, nenhuma linha e apagada.",
    )
    parser.add_argument(
        "--yes-i-understand",
        action="store_true",
        help="Confirmacao obrigatoria quando usado com --execute.",
    )
    parser.add_argument(
        "--preserve-documents",
        action="store_true",
        help="Nao apaga documentos/anexos v2 da tabela documents.",
    )
    parser.add_argument(
        "--preserve-workshop",
        action="store_true",
        help="Nao apaga processos de oficina v2.",
    )
    parser.add_argument(
        "--preserve-tasks",
        action="store_true",
        help="Nao apaga tarefas/problemas v2.",
    )
    parser.add_argument(
        "--yes-production",
        action="store_true",
        help="Confirmacao adicional obrigatoria para executar contra Postgres remoto.",
    )
    return parser.parse_args()


def configure_database_url(database_url: str | None) -> None:
    if database_url:
        os.environ["DATABASE_URL"] = database_url


def import_models() -> dict[str, Any]:
    from sqlalchemy import func, or_, select

    from app.core.config import settings
    from app.core.database import SessionLocal
    from app.models.documents import (
        Document,
        DocumentEvent,
        DocumentLink,
        VehicleDocumentAlert,
        VehicleDocumentAuditField,
        VehicleDocumentPendingAction,
        VehicleDocumentRecord,
        VehicleDocumentRecordTag,
    )
    from app.models.tasks import (
        QuickRecord,
        Task,
        TaskComment,
        TaskDocument,
        TaskGuidedFlowRun,
        TaskGuidedFlowStepRun,
        TaskHistory,
    )
    from app.models.workshop_phased import (
        WorkshopPhasedClosureCheck,
        WorkshopPhasedProcess,
        WorkshopPhasedProcessAlert,
        WorkshopPhasedProcessPhase,
        WorkshopPhasedProcessService,
        WorkshopPhasedTechnicalCheck,
        WorkshopPhasedTechnicalIncident,
        WorkshopPhasedTechnicalReport,
    )

    return locals()


def database_target_summary(settings: Any) -> dict[str, str]:
    raw_url = settings.database_url
    driver_url = settings.sqlalchemy_database_url
    target = {
        "app_env": settings.app_env,
        "driver": driver_url.split("://", 1)[0],
        "host": "(local/ficheiro)",
        "database": "(desconhecida)",
    }
    try:
        after_scheme = raw_url.split("://", 1)[1]
        after_auth = after_scheme.split("@", 1)[1] if "@" in after_scheme else after_scheme
        host_part, _, path_part = after_auth.partition("/")
        target["host"] = host_part or "(local/ficheiro)"
        target["database"] = path_part.split("?", 1)[0] or "(desconhecida)"
    except Exception:
        target["database"] = raw_url
    return target


def count_query(db: Any, stmt: Any) -> int:
    return int(db.scalar(stmt) or 0)


def id_list(db: Any, stmt: Any) -> list[int]:
    return [int(value) for value in db.scalars(stmt).all()]


def build_scope(db: Any, m: dict[str, Any], *, include_documents: bool, include_workshop: bool, include_tasks: bool) -> dict[str, Any]:
    select = m["select"]
    or_ = m["or_"]
    Document = m["Document"]
    DocumentLink = m["DocumentLink"]
    Task = m["Task"]
    WorkshopPhasedProcess = m["WorkshopPhasedProcess"]
    WorkshopPhasedTechnicalReport = m["WorkshopPhasedTechnicalReport"]
    WorkshopPhasedTechnicalCheck = m["WorkshopPhasedTechnicalCheck"]
    WorkshopPhasedTechnicalIncident = m["WorkshopPhasedTechnicalIncident"]

    workshop_process_ids: list[int] = []
    if include_workshop:
        workshop_process_ids = id_list(
            db,
            select(WorkshopPhasedProcess.id).where(WorkshopPhasedProcess.origin == "v2_clean"),
        )

    v2_doc_ids: set[int] = set()
    if include_documents:
        v2_doc_ids.update(
            id_list(
                db,
                select(Document.id).where(
                    or_(
                        Document.source == "workshop_v2_clean",
                        (
                            Document.source == "v2_clean_manual"
                        )
                        & Document.entry_channel.in_(V2_DOCUMENT_ENTRY_CHANNELS),
                    )
                ),
            )
        )
        v2_doc_ids.update(
            id_list(
                db,
                select(DocumentLink.document_id).where(DocumentLink.entity_type.in_(V2_TASK_ENTITY_TYPES)),
            )
        )
        if workshop_process_ids:
            v2_doc_ids.update(
                id_list(
                    db,
                    select(WorkshopPhasedTechnicalReport.original_document_id).where(
                        WorkshopPhasedTechnicalReport.process_id.in_(workshop_process_ids),
                        WorkshopPhasedTechnicalReport.original_document_id.is_not(None),
                    ),
                )
            )
            v2_doc_ids.update(
                id_list(
                    db,
                    select(WorkshopPhasedTechnicalCheck.evidence_document_id).where(
                        WorkshopPhasedTechnicalCheck.process_id.in_(workshop_process_ids),
                        WorkshopPhasedTechnicalCheck.evidence_document_id.is_not(None),
                    ),
                )
            )
            v2_doc_ids.update(
                id_list(
                    db,
                    select(WorkshopPhasedTechnicalIncident.evidence_document_id).where(
                        WorkshopPhasedTechnicalIncident.process_id.in_(workshop_process_ids),
                        WorkshopPhasedTechnicalIncident.evidence_document_id.is_not(None),
                    ),
                )
            )

    task_ids: list[int] = []
    if include_tasks:
        task_ids = id_list(
            db,
            select(Task.id).where(
                or_(
                    Task.source.in_(V2_TASK_SOURCES),
                    Task.entity_type.in_(V2_TASK_ENTITY_TYPES),
                )
            ),
        )

    return {
        "workshop_process_ids": workshop_process_ids,
        "document_ids": sorted(v2_doc_ids),
        "task_ids": task_ids,
    }


def scope_summary(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "document_ids": len(scope["document_ids"]),
        "workshop_process_ids": len(scope["workshop_process_ids"]),
        "task_ids": len(scope["task_ids"]),
        "document_id_sample": scope["document_ids"][:100],
        "workshop_process_id_sample": scope["workshop_process_ids"][:100],
        "task_id_sample": scope["task_ids"][:100],
    }


def audit(db: Any, m: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    select = m["select"]
    func = m["func"]
    Document = m["Document"]
    DocumentEvent = m["DocumentEvent"]
    DocumentLink = m["DocumentLink"]
    VehicleDocumentRecord = m["VehicleDocumentRecord"]
    VehicleDocumentRecordTag = m["VehicleDocumentRecordTag"]
    VehicleDocumentAlert = m["VehicleDocumentAlert"]
    VehicleDocumentPendingAction = m["VehicleDocumentPendingAction"]
    VehicleDocumentAuditField = m["VehicleDocumentAuditField"]
    Task = m["Task"]
    TaskComment = m["TaskComment"]
    TaskDocument = m["TaskDocument"]
    TaskGuidedFlowRun = m["TaskGuidedFlowRun"]
    TaskGuidedFlowStepRun = m["TaskGuidedFlowStepRun"]
    TaskHistory = m["TaskHistory"]
    QuickRecord = m["QuickRecord"]
    WorkshopPhasedProcess = m["WorkshopPhasedProcess"]
    WorkshopPhasedProcessService = m["WorkshopPhasedProcessService"]
    WorkshopPhasedProcessPhase = m["WorkshopPhasedProcessPhase"]
    WorkshopPhasedProcessAlert = m["WorkshopPhasedProcessAlert"]
    WorkshopPhasedTechnicalReport = m["WorkshopPhasedTechnicalReport"]
    WorkshopPhasedTechnicalCheck = m["WorkshopPhasedTechnicalCheck"]
    WorkshopPhasedTechnicalIncident = m["WorkshopPhasedTechnicalIncident"]
    WorkshopPhasedClosureCheck = m["WorkshopPhasedClosureCheck"]

    doc_ids = scope["document_ids"]
    task_ids = scope["task_ids"]
    process_ids = scope["workshop_process_ids"]

    def ids_count(model: Any, column_name: str, values: list[int]) -> int:
        if not values:
            return 0
        return count_query(db, select(func.count(model.id)).where(getattr(model, column_name).in_(values)))

    return {
        "documents": {
            "selected_documents": len(doc_ids),
            "document_events": ids_count(DocumentEvent, "document_id", doc_ids),
            "document_links": ids_count(DocumentLink, "document_id", doc_ids),
            "vehicle_document_records_all": count_query(db, select(func.count(VehicleDocumentRecord.id))),
            "vehicle_document_records_structured": count_query(
                db,
                select(func.count(VehicleDocumentRecord.id)).where(
                    VehicleDocumentRecord.source_record_type == "structured"
                ),
            ),
            "vehicle_document_records_linked_to_v2_documents": ids_count(
                VehicleDocumentRecord, "document_id", doc_ids
            ),
            "vehicle_document_record_tags": count_query(db, select(func.count(VehicleDocumentRecordTag.id))),
            "vehicle_document_alerts": count_query(db, select(func.count(VehicleDocumentAlert.id))),
            "vehicle_document_pending_actions": count_query(
                db, select(func.count(VehicleDocumentPendingAction.id))
            ),
            "vehicle_document_audit_fields": count_query(db, select(func.count(VehicleDocumentAuditField.id))),
            "documents_total_all_sources": count_query(db, select(func.count(Document.id))),
        },
        "workshop": {
            "selected_processes": len(process_ids),
            "services": ids_count(WorkshopPhasedProcessService, "process_id", process_ids),
            "phases": ids_count(WorkshopPhasedProcessPhase, "process_id", process_ids),
            "alerts": ids_count(WorkshopPhasedProcessAlert, "process_id", process_ids),
            "reports": ids_count(WorkshopPhasedTechnicalReport, "process_id", process_ids),
            "checks": ids_count(WorkshopPhasedTechnicalCheck, "process_id", process_ids),
            "incidents": ids_count(WorkshopPhasedTechnicalIncident, "process_id", process_ids),
            "closure_checks": ids_count(WorkshopPhasedClosureCheck, "process_id", process_ids),
        },
        "tasks": {
            "selected_tasks": len(task_ids),
            "comments": ids_count(TaskComment, "task_id", task_ids),
            "documents": ids_count(TaskDocument, "task_id", task_ids),
            "history": ids_count(TaskHistory, "task_id", task_ids),
            "flow_runs": ids_count(TaskGuidedFlowRun, "task_id", task_ids),
            "flow_steps": ids_count(TaskGuidedFlowStepRun, "task_id", task_ids),
            "quick_records_v2": count_query(
                db,
                select(func.count(QuickRecord.id)).where(
                    QuickRecord.source.in_(V2_TASK_SOURCES)
                ),
            ),
        },
    }


def print_audit(title: str, payload: dict[str, Any]) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def delete_by_ids(db: Any, model: Any, column_name: str, values: list[int]) -> int:
    if not values:
        return 0
    delete = __import__("sqlalchemy").delete
    result = db.execute(delete(model).where(getattr(model, column_name).in_(values)))
    return int(result.rowcount or 0)


def execute_reset(db: Any, m: dict[str, Any], scope: dict[str, Any]) -> dict[str, int]:
    delete = __import__("sqlalchemy").delete

    Document = m["Document"]
    DocumentEvent = m["DocumentEvent"]
    DocumentLink = m["DocumentLink"]
    VehicleDocumentRecord = m["VehicleDocumentRecord"]
    VehicleDocumentRecordTag = m["VehicleDocumentRecordTag"]
    VehicleDocumentAlert = m["VehicleDocumentAlert"]
    VehicleDocumentPendingAction = m["VehicleDocumentPendingAction"]
    VehicleDocumentAuditField = m["VehicleDocumentAuditField"]
    Task = m["Task"]
    TaskComment = m["TaskComment"]
    TaskDocument = m["TaskDocument"]
    TaskGuidedFlowRun = m["TaskGuidedFlowRun"]
    TaskGuidedFlowStepRun = m["TaskGuidedFlowStepRun"]
    TaskHistory = m["TaskHistory"]
    QuickRecord = m["QuickRecord"]
    WorkshopPhasedProcess = m["WorkshopPhasedProcess"]
    WorkshopPhasedProcessService = m["WorkshopPhasedProcessService"]
    WorkshopPhasedProcessPhase = m["WorkshopPhasedProcessPhase"]
    WorkshopPhasedProcessAlert = m["WorkshopPhasedProcessAlert"]
    WorkshopPhasedTechnicalReport = m["WorkshopPhasedTechnicalReport"]
    WorkshopPhasedTechnicalCheck = m["WorkshopPhasedTechnicalCheck"]
    WorkshopPhasedTechnicalIncident = m["WorkshopPhasedTechnicalIncident"]
    WorkshopPhasedClosureCheck = m["WorkshopPhasedClosureCheck"]

    doc_ids = scope["document_ids"]
    task_ids = scope["task_ids"]
    process_ids = scope["workshop_process_ids"]

    deleted: dict[str, int] = {}

    if task_ids:
        deleted["task_guided_flow_step_runs"] = delete_by_ids(db, TaskGuidedFlowStepRun, "task_id", task_ids)
        deleted["task_guided_flow_runs"] = delete_by_ids(db, TaskGuidedFlowRun, "task_id", task_ids)
        deleted["task_history"] = delete_by_ids(db, TaskHistory, "task_id", task_ids)
        deleted["task_documents"] = delete_by_ids(db, TaskDocument, "task_id", task_ids)
        deleted["task_comments"] = delete_by_ids(db, TaskComment, "task_id", task_ids)
        deleted["tasks"] = delete_by_ids(db, Task, "id", task_ids)

    quick_records = db.execute(delete(QuickRecord).where(QuickRecord.source.in_(V2_TASK_SOURCES)))
    deleted["quick_records"] = int(quick_records.rowcount or 0)

    if process_ids:
        deleted["workshop_phased_closure_checks"] = delete_by_ids(
            db, WorkshopPhasedClosureCheck, "process_id", process_ids
        )
        deleted["workshop_phased_technical_incidents"] = delete_by_ids(
            db, WorkshopPhasedTechnicalIncident, "process_id", process_ids
        )
        deleted["workshop_phased_technical_checks"] = delete_by_ids(
            db, WorkshopPhasedTechnicalCheck, "process_id", process_ids
        )
        deleted["workshop_phased_technical_reports"] = delete_by_ids(
            db, WorkshopPhasedTechnicalReport, "process_id", process_ids
        )
        deleted["workshop_phased_process_alerts"] = delete_by_ids(
            db, WorkshopPhasedProcessAlert, "process_id", process_ids
        )
        deleted["workshop_phased_process_phases"] = delete_by_ids(
            db, WorkshopPhasedProcessPhase, "process_id", process_ids
        )
        deleted["workshop_phased_process_services"] = delete_by_ids(
            db, WorkshopPhasedProcessService, "process_id", process_ids
        )
        deleted["workshop_phased_processes"] = delete_by_ids(db, WorkshopPhasedProcess, "id", process_ids)

    if doc_ids:
        deleted["vehicle_document_record_tags_by_document"] = delete_by_ids(
            db, VehicleDocumentRecordTag, "document_id", doc_ids
        )
        deleted["vehicle_document_alerts_by_document"] = delete_by_ids(db, VehicleDocumentAlert, "document_id", doc_ids)
        deleted["vehicle_document_pending_actions_by_document"] = delete_by_ids(
            db, VehicleDocumentPendingAction, "document_id", doc_ids
        )
        deleted["vehicle_document_records_by_document"] = delete_by_ids(
            db, VehicleDocumentRecord, "document_id", doc_ids
        )
        deleted["document_events"] = delete_by_ids(db, DocumentEvent, "document_id", doc_ids)
        deleted["document_links"] = delete_by_ids(db, DocumentLink, "document_id", doc_ids)
        deleted["documents"] = delete_by_ids(db, Document, "id", doc_ids)

    db.commit()
    return deleted


def write_snapshot(path: str | None, payload: dict[str, Any]) -> None:
    if not path:
        return
    snapshot_path = Path(path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSnapshot: {snapshot_path}")


def main() -> None:
    args = parse_args()
    if args.execute and not args.yes_i_understand:
        raise SystemExit("Para executar, usar tambem --yes-i-understand.")

    configure_database_url(args.database_url)
    m = import_models()

    SessionLocal = m["SessionLocal"]
    settings = m["settings"]
    target = database_target_summary(settings)
    is_remote_postgres = target["driver"].startswith("postgresql") and target["host"] not in {
        "localhost:5432",
        "127.0.0.1:5432",
        "(local/ficheiro)",
    }
    if args.execute and is_remote_postgres and not args.yes_production:
        raise SystemExit("Para executar contra Postgres remoto, usar tambem --yes-production.")

    include_documents = not args.preserve_documents
    include_workshop = not args.preserve_workshop
    include_tasks = not args.preserve_tasks

    with SessionLocal() as db:
        scope = build_scope(
            db,
            m,
            include_documents=include_documents,
            include_workshop=include_workshop,
            include_tasks=include_tasks,
        )
        before = {
            "target": database_target_summary(settings),
            "mode": "execute" if args.execute else "dry_run",
            "scope": {
                "include_documents": include_documents,
                "include_workshop": include_workshop,
                "include_tasks": include_tasks,
                **scope_summary(scope),
            },
            "counts": audit(db, m, scope),
        }
        print_audit("V2 OPERATIONAL RESET - BEFORE", before)

        payload: dict[str, Any] = {"before": before}
        if args.execute:
            payload["deleted"] = execute_reset(db, m, scope)
            after_scope = build_scope(
                db,
                m,
                include_documents=include_documents,
                include_workshop=include_workshop,
                include_tasks=include_tasks,
            )
            payload["after"] = {
                "target": database_target_summary(settings),
                "counts": audit(db, m, after_scope),
            }
            print_audit("V2 OPERATIONAL RESET - AFTER", payload["after"])
        else:
            print("\nDRY-RUN: nenhuma alteracao aplicada.")

        write_snapshot(args.snapshot_file, payload)


if __name__ == "__main__":
    main()
