from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, func, select, text


WORKSHOP_CHILD_TABLES = {
    "services": "workshop_phased_process_services",
    "phases": "workshop_phased_process_phases",
    "alerts": "workshop_phased_process_alerts",
    "reports": "workshop_phased_technical_reports",
    "checks": "workshop_phased_technical_checks",
    "incidents": "workshop_phased_technical_incidents",
    "closure_checks": "workshop_phased_closure_checks",
}

V2_ENTITY_TYPES = {
    "workshop_phased_process",
    "workshop_phased_technical_report",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compara o estado dos processos v2 entre a base PITR e a base atual."
    )
    parser.add_argument("--source-url", default=os.environ.get("SOURCE_DATABASE_URL"))
    parser.add_argument("--target-url", default=os.environ.get("TARGET_DATABASE_URL"))
    parser.add_argument("--output", default="tmp/v2_recovery_audit.csv")
    parser.add_argument("--json-output", default="tmp/v2_recovery_audit_summary.json")
    parser.add_argument(
        "--process-scope",
        choices=["v2-clean", "non-v2-clean", "all"],
        default="all",
    )
    return parser.parse_args()


def require_url(value: str | None, name: str) -> str:
    if not value:
        raise SystemExit(f"Falta {name}. Usa env var ou argumento.")
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    return value


TABLES_TO_REFLECT = sorted(
    {
        "workshop_phased_processes",
        *WORKSHOP_CHILD_TABLES.values(),
        "document_links",
        "vehicle_document_records",
        "tasks",
    }
)


def load_metadata(engine: Any) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=engine, only=TABLES_TO_REFLECT)
    return metadata


def process_scope_stmt(table: Table, scope: str) -> Any:
    stmt = select(table)
    if scope == "v2-clean":
        stmt = stmt.where(table.c.origin == "v2_clean")
    elif scope == "non-v2-clean":
        stmt = stmt.where((table.c.origin.is_(None)) | (table.c.origin != "v2_clean"))
    return stmt.order_by(table.c.id)


def count_by_process(conn: Any, table: Table, process_id: int) -> int:
    if "process_id" not in table.c:
        return 0
    return int(conn.scalar(select(func.count()).select_from(table).where(table.c.process_id == process_id)) or 0)


def document_ids_for_process(conn: Any, tables: dict[str, Table], process_id: int) -> set[int]:
    document_ids: set[int] = set()

    for table_name, column_name in [
        ("workshop_phased_technical_reports", "original_document_id"),
        ("workshop_phased_technical_checks", "evidence_document_id"),
        ("workshop_phased_technical_incidents", "evidence_document_id"),
    ]:
        table = tables.get(table_name)
        if table is None or column_name not in table.c:
            continue
        rows = conn.execute(
            select(getattr(table.c, column_name)).where(
                table.c.process_id == process_id,
                getattr(table.c, column_name).is_not(None),
            )
        ).all()
        document_ids.update(int(row[0]) for row in rows if row[0] is not None)

    links = tables.get("document_links")
    if links is not None:
        rows = conn.execute(
            select(links.c.document_id).where(
                links.c.entity_type.in_(V2_ENTITY_TYPES),
                links.c.entity_id == str(process_id),
            )
        ).all()
        document_ids.update(int(row[0]) for row in rows if row[0] is not None)

    records = tables.get("vehicle_document_records")
    if records is not None and "process_reference" in records.c and "document_id" in records.c:
        rows = conn.execute(
            select(records.c.document_id).where(
                records.c.process_reference == str(process_id),
                records.c.document_id.is_not(None),
            )
        ).all()
        document_ids.update(int(row[0]) for row in rows if row[0] is not None)

    return document_ids


def task_ids_for_process(conn: Any, tables: dict[str, Table], process_id: int) -> set[int]:
    tasks = tables.get("tasks")
    if tasks is None:
        return set()
    rows = conn.execute(
        select(tasks.c.id).where(
            tasks.c.entity_type.in_(V2_ENTITY_TYPES),
            tasks.c.entity_id == str(process_id),
        )
    ).all()
    return {int(row[0]) for row in rows}


def load_process_snapshot(conn: Any, tables: dict[str, Table], scope: str) -> dict[int, dict[str, Any]]:
    processes = tables["workshop_phased_processes"]
    snapshot: dict[int, dict[str, Any]] = {}
    for row in conn.execute(process_scope_stmt(processes, scope)).all():
        data = dict(row._mapping)
        process_id = int(data["id"])
        counts: dict[str, Any] = {
            "id": process_id,
            "code": data.get("code") or data.get("process_number") or f"#{process_id}",
            "plate": data.get("plate") or "",
            "origin": data.get("origin") or "",
            "process_type": data.get("process_type") or "",
            "creation_mode": data.get("creation_mode") or "",
            "current_phase": data.get("current_phase") or "",
            "status": data.get("status") or "",
        }
        for label, table_name in WORKSHOP_CHILD_TABLES.items():
            counts[label] = count_by_process(conn, tables[table_name], process_id)
        counts["documents"] = len(document_ids_for_process(conn, tables, process_id))
        counts["tasks"] = len(task_ids_for_process(conn, tables, process_id))
        snapshot[process_id] = counts
    return snapshot


def compare_snapshots(source: dict[int, dict[str, Any]], target: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    process_ids = sorted(set(source) | set(target))
    rows: list[dict[str, Any]] = []
    count_fields = [
        "services",
        "phases",
        "alerts",
        "reports",
        "checks",
        "incidents",
        "closure_checks",
        "documents",
        "tasks",
    ]
    for process_id in process_ids:
        source_row = source.get(process_id)
        target_row = target.get(process_id)
        base = source_row or target_row or {}
        result: dict[str, Any] = {
            "process_id": process_id,
            "code": base.get("code", f"#{process_id}"),
            "plate": base.get("plate", ""),
            "origin": base.get("origin", ""),
            "process_type": base.get("process_type", ""),
            "creation_mode": base.get("creation_mode", ""),
            "current_phase_source": (source_row or {}).get("current_phase", ""),
            "current_phase_target": (target_row or {}).get("current_phase", ""),
            "status_source": (source_row or {}).get("status", ""),
            "status_target": (target_row or {}).get("status", ""),
            "state": "ok",
        }
        if source_row and not target_row:
            result["state"] = "missing_in_target"
        elif target_row and not source_row:
            result["state"] = "only_in_target"
        for field in count_fields:
            source_count = int((source_row or {}).get(field, 0) or 0)
            target_count = int((target_row or {}).get(field, 0) or 0)
            result[f"{field}_source"] = source_count
            result[f"{field}_target"] = target_count
            result[f"{field}_diff"] = source_count - target_count
            if source_count != target_count and result["state"] == "ok":
                result["state"] = "different_counts"
        if (
            result["current_phase_source"] != result["current_phase_target"]
            or result["status_source"] != result["status_target"]
        ) and result["state"] == "ok":
            result["state"] = "different_metadata"
        rows.append(result)
    return rows


def main() -> None:
    args = parse_args()
    source_engine = create_engine(require_url(args.source_url, "SOURCE_DATABASE_URL"))
    target_engine = create_engine(require_url(args.target_url, "TARGET_DATABASE_URL"))
    source_md = load_metadata(source_engine)
    target_md = load_metadata(target_engine)

    needed = {"workshop_phased_processes", *WORKSHOP_CHILD_TABLES.values(), "document_links", "vehicle_document_records", "tasks"}
    missing = sorted(name for name in needed if name not in source_md.tables or name not in target_md.tables)
    if missing:
        raise SystemExit(f"Tabelas em falta: {missing}")

    with source_engine.connect() as source_conn, target_engine.connect() as target_conn:
        source = load_process_snapshot(source_conn, source_md.tables, args.process_scope)
        target = load_process_snapshot(target_conn, target_md.tables, args.process_scope)

    rows = compare_snapshots(source, target)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    summary = {
        "process_scope": args.process_scope,
        "source_processes": len(source),
        "target_processes": len(target),
        "rows_compared": len(rows),
        "states": {},
        "differences": [row for row in rows if row["state"] != "ok"],
        "csv": str(output),
    }
    for row in rows:
        summary["states"][row["state"]] = summary["states"].get(row["state"], 0) + 1

    json_output = Path(args.json_output)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
