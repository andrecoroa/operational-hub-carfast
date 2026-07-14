from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import sys

from sqlalchemy import delete, func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.documents import (
    Document,
    VehicleDocumentAlert,
    VehicleDocumentAuditField,
    VehicleDocumentPendingAction,
    VehicleDocumentRecord,
    VehicleDocumentRecordTag,
)
from app.models.vehicles import Vehicle


@dataclass
class ResetScope:
    vehicle_id: int | None = None


def _database_target_summary() -> dict[str, str]:
    raw_url = settings.database_url
    driver_url = settings.sqlalchemy_database_url
    target = {
        "app_env": settings.app_env,
        "driver": driver_url.split("://", 1)[0],
        "database": "(desconhecida)",
        "host": "(desconhecido)",
    }
    try:
        after_scheme = raw_url.split("://", 1)[1]
        if "@" in after_scheme:
            after_auth = after_scheme.split("@", 1)[1]
        else:
            after_auth = after_scheme
        host_part, _, path_part = after_auth.partition("/")
        target["host"] = host_part or "(desconhecido)"
        target["database"] = path_part.split("?", 1)[0] or "(desconhecida)"
    except Exception:
        pass
    return target


def _vehicle_label(db, vehicle_id: int | None) -> str:
    if vehicle_id is None:
        return "GLOBAL"
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle:
        return f"Viatura {vehicle_id} (nao encontrada)"
    plate = vehicle.plate or vehicle.license_plate or f"#{vehicle.id}"
    return f"{plate} [id={vehicle.id}]"


def _count_records(db, scope: ResetScope) -> dict[str, int]:
    filters = []
    if scope.vehicle_id is not None:
        filters.append(VehicleDocumentRecord.vehicle_id == scope.vehicle_id)
    stmt = select(
        func.count(VehicleDocumentRecord.id),
    )
    if filters:
        stmt = stmt.where(*filters)
    records_total = db.scalar(stmt) or 0

    table_counts: dict[str, int] = {"vehicle_document_records": records_total}

    tag_stmt = select(func.count(VehicleDocumentRecordTag.id))
    alert_stmt = select(func.count(VehicleDocumentAlert.id))
    pending_stmt = select(func.count(VehicleDocumentPendingAction.id))
    audit_stmt = select(func.count(VehicleDocumentAuditField.id))

    if scope.vehicle_id is not None:
        tag_stmt = tag_stmt.where(VehicleDocumentRecordTag.vehicle_id == scope.vehicle_id)
        alert_stmt = alert_stmt.where(VehicleDocumentAlert.vehicle_id == scope.vehicle_id)
        pending_stmt = pending_stmt.where(VehicleDocumentPendingAction.vehicle_id == scope.vehicle_id)
        audit_stmt = audit_stmt.where(VehicleDocumentAuditField.vehicle_id == scope.vehicle_id)

    table_counts["vehicle_document_record_tags"] = db.scalar(tag_stmt) or 0
    table_counts["vehicle_document_alerts"] = db.scalar(alert_stmt) or 0
    table_counts["vehicle_document_pending_actions"] = db.scalar(pending_stmt) or 0
    table_counts["vehicle_document_audit_fields"] = db.scalar(audit_stmt) or 0
    return table_counts


def _count_related_documents(db, scope: ResetScope) -> dict[str, int]:
    filters = []
    if scope.vehicle_id is not None:
        filters.append(Document.vehicle_id == scope.vehicle_id)

    stmt_all = select(func.count(Document.id))
    stmt_workshop = select(func.count(Document.id)).where(Document.source == "workshop_v2_clean")

    if scope.vehicle_id is not None:
        stmt_all = stmt_all.where(*filters)
        stmt_workshop = stmt_workshop.where(*filters)

    return {
        "documents_total": db.scalar(stmt_all) or 0,
        "documents_workshop_v2_clean": db.scalar(stmt_workshop) or 0,
    }


def _group_breakdown(db, scope: ResetScope) -> Counter:
    stmt = select(VehicleDocumentRecord.main_group, func.count(VehicleDocumentRecord.id)).group_by(
        VehicleDocumentRecord.main_group
    )
    if scope.vehicle_id is not None:
        stmt = stmt.where(VehicleDocumentRecord.vehicle_id == scope.vehicle_id)
    return Counter({group or "-": count for group, count in db.execute(stmt).all()})


def build_audit_payload(db, scope: ResetScope) -> dict[str, object]:
    return {
        "database_target": _database_target_summary(),
        "scope": {
            "vehicle_id": scope.vehicle_id,
            "label": _vehicle_label(db, scope.vehicle_id),
        },
        "structured_table_counts": _count_records(db, scope),
        "related_documents": _count_related_documents(db, scope),
        "group_breakdown": dict(_group_breakdown(db, scope)),
    }


def print_audit_payload(payload: dict[str, object]) -> None:
    print("=" * 72)
    print("AUDITORIA RESET DOCUMENTAL V2")
    target = payload["database_target"]
    print(
        "Base ativa: "
        f"env={target['app_env']} | driver={target['driver']} | host={target['host']} | db={target['database']}"
    )
    scope = payload["scope"]
    print(f"Ambito: {scope['label']}")
    print("=" * 72)

    table_counts = payload["structured_table_counts"]
    related_docs = payload["related_documents"]
    breakdown = payload["group_breakdown"]

    print("\nTabelas do modulo documental v2")
    for key, value in table_counts.items():  # type: ignore[union-attr]
        print(f"- {key}: {value}")

    print("\nDocumentos reais preservados fora do reset estrutural")
    for key, value in related_docs.items():  # type: ignore[union-attr]
        print(f"- {key}: {value}")

    print("\nDistribuicao por grupo estruturado")
    if breakdown:
        for key, value in sorted(breakdown.items()):  # type: ignore[union-attr]
            print(f"- {key}: {value}")
    else:
        print("- sem registos estruturados")

    print(
        "\nNota: o reset estrutural limpa apenas vehicle_document_* e nao remove "
        "documents nem ficheiros fisicos."
    )


def print_audit(db, scope: ResetScope) -> dict[str, object]:
    payload = build_audit_payload(db, scope)
    print_audit_payload(payload)
    return payload


def write_snapshot(snapshot_path: Path, payload: dict[str, object]) -> None:
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSnapshot gravado em: {snapshot_path}")


def apply_reset(db, scope: ResetScope) -> None:
    print("\nA aplicar reset estrutural...")

    if scope.vehicle_id is None:
        db.execute(delete(VehicleDocumentRecordTag))
        db.execute(delete(VehicleDocumentAlert))
        db.execute(delete(VehicleDocumentPendingAction))
        db.execute(delete(VehicleDocumentAuditField))
        db.execute(delete(VehicleDocumentRecord))
    else:
        db.execute(delete(VehicleDocumentRecordTag).where(VehicleDocumentRecordTag.vehicle_id == scope.vehicle_id))
        db.execute(delete(VehicleDocumentAlert).where(VehicleDocumentAlert.vehicle_id == scope.vehicle_id))
        db.execute(
            delete(VehicleDocumentPendingAction).where(VehicleDocumentPendingAction.vehicle_id == scope.vehicle_id)
        )
        db.execute(delete(VehicleDocumentAuditField).where(VehicleDocumentAuditField.vehicle_id == scope.vehicle_id))
        db.execute(delete(VehicleDocumentRecord).where(VehicleDocumentRecord.vehicle_id == scope.vehicle_id))

    db.commit()
    print("Reset estrutural concluido.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audita e limpa o modulo documental v2 sem tocar em documentos reais por defeito."
    )
    parser.add_argument("--vehicle-id", type=int, help="Limitar auditoria/reset a uma viatura.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Executar o reset estrutural. Sem esta flag, o script faz apenas auditoria.",
    )
    parser.add_argument(
        "--snapshot-file",
        type=str,
        help="Guardar auditoria em JSON antes/depois. Ex.: exports/document-reset-audit.json",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scope = ResetScope(vehicle_id=args.vehicle_id)
    snapshot_path = Path(args.snapshot_file) if args.snapshot_file else None
    with SessionLocal() as db:
        before = print_audit(db, scope)
        if snapshot_path:
            write_snapshot(snapshot_path, {"before": before})
        if args.apply:
            apply_reset(db, scope)
            after = print_audit(db, scope)
            if snapshot_path:
                write_snapshot(snapshot_path, {"before": before, "after": after})
        else:
            print("\nModo seguro: nenhuma alteracao aplicada.")


if __name__ == "__main__":
    main()
