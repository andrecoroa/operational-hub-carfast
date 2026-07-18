from __future__ import annotations

import argparse
import json
import os
from collections.abc import Iterable
from typing import Any

from sqlalchemy import MetaData, Table, create_engine, insert, select, text


V2_ENTITY_TYPES = {
    "workshop_phased_process",
    "workshop_phased_technical_report",
}


WORKSHOP_TABLES = [
    "workshop_phased_processes",
    "workshop_phased_process_services",
    "workshop_phased_process_phases",
    "workshop_phased_process_alerts",
    "workshop_phased_technical_reports",
    "workshop_phased_technical_checks",
    "workshop_phased_technical_incidents",
    "workshop_phased_closure_checks",
]


DOCUMENT_TABLES = [
    "documents",
    "document_events",
    "document_links",
    "vehicle_document_records",
    "vehicle_document_record_tags",
    "vehicle_document_alerts",
    "vehicle_document_pending_actions",
]


TASK_TABLES = [
    "tasks",
    "task_comments",
    "task_documents",
    "task_history",
    "task_guided_flow_runs",
    "task_guided_flow_step_runs",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recupera seletivamente dados v2-clean de uma base PITR para a base atual."
    )
    parser.add_argument("--source-url", default=os.environ.get("SOURCE_DATABASE_URL"))
    parser.add_argument("--target-url", default=os.environ.get("TARGET_DATABASE_URL"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--yes-i-understand", action="store_true")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Mostra apenas resumo de processos por origem/tipo na base fonte e alvo.",
    )
    parser.add_argument(
        "--process-scope",
        choices=["v2-clean", "non-v2-clean", "all"],
        default="v2-clean",
        help="Que processos recuperar da base PITR.",
    )
    return parser.parse_args()


def require_url(value: str | None, name: str) -> str:
    if not value:
        raise SystemExit(f"Falta {name}. Usa env var ou argumento.")
    if value.startswith("postgresql://"):
        return value.replace("postgresql://", "postgresql+psycopg://", 1)
    return value


def load_metadata(engine: Any) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata


def table_rows(conn: Any, table: Table, ids: Iterable[int]) -> list[dict[str, Any]]:
    ids = list(ids)
    if not ids:
        return []
    return [dict(row._mapping) for row in conn.execute(select(table).where(table.c.id.in_(ids))).all()]


def existing_ids(conn: Any, table: Table, ids: Iterable[int]) -> set[int]:
    ids = list(ids)
    if not ids:
        return set()
    return {int(row[0]) for row in conn.execute(select(table.c.id).where(table.c.id.in_(ids))).all()}


def ids_by_column(conn: Any, table: Table, column_name: str, values: Iterable[Any]) -> list[int]:
    values = list(values)
    if not values:
        return []
    return [
        int(row[0])
        for row in conn.execute(select(table.c.id).where(getattr(table.c, column_name).in_(values))).all()
    ]


def insert_missing(source_conn: Any, target_conn: Any, source_table: Table, target_table: Table, ids: list[int]) -> int:
    if not ids:
        return 0
    rows = table_rows(source_conn, source_table, ids)
    if not rows:
        return 0
    existing = existing_ids(target_conn, target_table, [row["id"] for row in rows])
    rows_to_insert = [row for row in rows if int(row["id"]) not in existing]
    if not rows_to_insert:
        return 0
    target_conn.execute(insert(target_table), rows_to_insert)
    return len(rows_to_insert)


def get_process_ids(conn: Any, table: Table, scope: str) -> list[int]:
    stmt = select(table.c.id).order_by(table.c.id)
    if scope == "v2-clean":
        stmt = stmt.where(table.c.origin == "v2_clean")
    elif scope == "non-v2-clean":
        stmt = stmt.where((table.c.origin.is_(None)) | (table.c.origin != "v2_clean"))
    return [
        int(row[0])
        for row in conn.execute(stmt).all()
    ]


def collect_document_ids(source_conn: Any, tables: dict[str, Table], process_ids: list[int]) -> set[int]:
    document_ids: set[int] = set()
    if not process_ids:
        return document_ids

    reports = tables["workshop_phased_technical_reports"]
    checks = tables["workshop_phased_technical_checks"]
    incidents = tables["workshop_phased_technical_incidents"]
    links = tables["document_links"]
    records = tables["vehicle_document_records"]

    for table, column_name in [
        (reports, "original_document_id"),
        (checks, "evidence_document_id"),
        (incidents, "evidence_document_id"),
    ]:
        if column_name in table.c:
            rows = source_conn.execute(
                select(getattr(table.c, column_name)).where(
                    table.c.process_id.in_(process_ids),
                    getattr(table.c, column_name).is_not(None),
                )
            ).all()
            document_ids.update(int(row[0]) for row in rows if row[0] is not None)

    entity_ids = [str(pid) for pid in process_ids]
    link_rows = source_conn.execute(
        select(links.c.document_id).where(
            links.c.entity_type.in_(V2_ENTITY_TYPES),
            links.c.entity_id.in_(entity_ids),
        )
    ).all()
    document_ids.update(int(row[0]) for row in link_rows if row[0] is not None)

    record_rows = source_conn.execute(
        select(records.c.document_id).where(
            records.c.document_id.is_not(None),
            records.c.process_reference.in_(entity_ids),
        )
    ).all()
    document_ids.update(int(row[0]) for row in record_rows if row[0] is not None)

    return document_ids


def collect_task_ids(source_conn: Any, tables: dict[str, Table], process_ids: list[int]) -> set[int]:
    task_ids: set[int] = set()
    if not process_ids:
        return task_ids
    tasks = tables["tasks"]
    entity_ids = [str(pid) for pid in process_ids]
    rows = source_conn.execute(
        select(tasks.c.id).where(
            tasks.c.entity_type.in_(V2_ENTITY_TYPES),
            tasks.c.entity_id.in_(entity_ids),
        )
    ).all()
    task_ids.update(int(row[0]) for row in rows)
    return task_ids


def count_rows_by_ids(conn: Any, table: Table, ids: Iterable[int]) -> int:
    ids = list(ids)
    if not ids:
        return 0
    return int(conn.scalar(select(text("count(*)")).select_from(table).where(table.c.id.in_(ids))) or 0)


def main() -> None:
    args = parse_args()
    source_url = require_url(args.source_url, "SOURCE_DATABASE_URL")
    target_url = require_url(args.target_url, "TARGET_DATABASE_URL")
    if args.execute and not args.yes_i_understand:
        raise SystemExit("Para executar, usa tambem --yes-i-understand.")

    source_engine = create_engine(source_url)
    target_engine = create_engine(target_url)
    source_md = load_metadata(source_engine)
    target_md = load_metadata(target_engine)
    source_tables = source_md.tables
    target_tables = target_md.tables

    missing_tables = sorted(
        name for name in set(WORKSHOP_TABLES + DOCUMENT_TABLES + TASK_TABLES) if name not in source_tables or name not in target_tables
    )
    if missing_tables:
        raise SystemExit(f"Tabelas em falta: {missing_tables}")

    with source_engine.connect() as source_conn, target_engine.begin() as target_conn:
        if args.summary_only:
            summary: dict[str, Any] = {}
            for label, conn in [("source", source_conn), ("target", target_conn)]:
                rows = conn.execute(
                    text(
                        """
                        select
                          coalesce(origin, '<null>') as origin,
                          coalesce(process_type, '<null>') as process_type,
                          coalesce(creation_mode, '<null>') as creation_mode,
                          count(*) as total
                        from workshop_phased_processes
                        group by 1, 2, 3
                        order by total desc, origin, process_type, creation_mode
                        """
                    )
                ).all()
                summary[label] = [dict(row._mapping) for row in rows]
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return

        source_process_ids = get_process_ids(
            source_conn, source_tables["workshop_phased_processes"], args.process_scope
        )
        target_process_ids = set(
            get_process_ids(target_conn, target_tables["workshop_phased_processes"], args.process_scope)
        )
        missing_process_ids = [pid for pid in source_process_ids if pid not in target_process_ids]

        document_ids = collect_document_ids(source_conn, source_tables, missing_process_ids)
        task_ids = collect_task_ids(source_conn, source_tables, missing_process_ids)

        plan: dict[str, Any] = {
            "mode": "execute" if args.execute else "dry_run",
            "process_scope": args.process_scope,
            "source_v2_processes": len(source_process_ids),
            "target_v2_processes": len(target_process_ids),
            "missing_processes": len(missing_process_ids),
            "missing_process_sample": missing_process_ids[:30],
            "linked_documents": len(document_ids),
            "linked_document_sample": sorted(document_ids)[:30],
            "linked_tasks": len(task_ids),
            "linked_task_sample": sorted(task_ids)[:30],
            "tables": {},
        }

        for table_name in WORKSHOP_TABLES:
            table = source_tables[table_name]
            if table_name == "workshop_phased_processes":
                ids = missing_process_ids
            else:
                ids = ids_by_column(source_conn, table, "process_id", missing_process_ids)
            plan["tables"][table_name] = {
                "source_rows": len(ids),
                "already_in_target": count_rows_by_ids(target_conn, target_tables[table_name], ids),
                "to_insert": len(set(ids) - existing_ids(target_conn, target_tables[table_name], ids)),
            }

        for table_name in ["documents"]:
            ids = sorted(document_ids)
            plan["tables"][table_name] = {
                "source_rows": len(ids),
                "already_in_target": count_rows_by_ids(target_conn, target_tables[table_name], ids),
                "to_insert": len(set(ids) - existing_ids(target_conn, target_tables[table_name], ids)),
            }

        for table_name in ["document_events", "document_links", "vehicle_document_records", "vehicle_document_record_tags", "vehicle_document_alerts", "vehicle_document_pending_actions"]:
            table = source_tables[table_name]
            ids = ids_by_column(source_conn, table, "document_id", document_ids)
            plan["tables"][table_name] = {
                "source_rows": len(ids),
                "already_in_target": count_rows_by_ids(target_conn, target_tables[table_name], ids),
                "to_insert": len(set(ids) - existing_ids(target_conn, target_tables[table_name], ids)),
            }

        for table_name in ["tasks"]:
            ids = sorted(task_ids)
            plan["tables"][table_name] = {
                "source_rows": len(ids),
                "already_in_target": count_rows_by_ids(target_conn, target_tables[table_name], ids),
                "to_insert": len(set(ids) - existing_ids(target_conn, target_tables[table_name], ids)),
            }

        for table_name in ["task_comments", "task_documents", "task_history", "task_guided_flow_runs", "task_guided_flow_step_runs"]:
            table = source_tables[table_name]
            ids = ids_by_column(source_conn, table, "task_id", task_ids)
            plan["tables"][table_name] = {
                "source_rows": len(ids),
                "already_in_target": count_rows_by_ids(target_conn, target_tables[table_name], ids),
                "to_insert": len(set(ids) - existing_ids(target_conn, target_tables[table_name], ids)),
            }

        print(json.dumps(plan, ensure_ascii=False, indent=2))

        if not args.execute:
            return

        inserted: dict[str, int] = {}
        for table_name in ["documents"]:
            inserted[table_name] = insert_missing(
                source_conn,
                target_conn,
                source_tables[table_name],
                target_tables[table_name],
                sorted(document_ids),
            )

        for table_name in ["tasks"]:
            inserted[table_name] = insert_missing(
                source_conn, target_conn, source_tables[table_name], target_tables[table_name], sorted(task_ids)
            )

        for table_name in ["workshop_phased_processes"]:
            inserted[table_name] = insert_missing(
                source_conn,
                target_conn,
                source_tables[table_name],
                target_tables[table_name],
                missing_process_ids,
            )

        for table_name in [
            "workshop_phased_process_services",
            "workshop_phased_process_phases",
            "workshop_phased_process_alerts",
            "workshop_phased_technical_reports",
            "workshop_phased_technical_checks",
            "workshop_phased_technical_incidents",
            "workshop_phased_closure_checks",
        ]:
            ids = ids_by_column(source_conn, source_tables[table_name], "process_id", missing_process_ids)
            inserted[table_name] = insert_missing(
                source_conn, target_conn, source_tables[table_name], target_tables[table_name], ids
            )

        for table_name in [
            "task_comments",
            "task_documents",
            "task_history",
            "task_guided_flow_runs",
            "task_guided_flow_step_runs",
        ]:
            ids = ids_by_column(source_conn, source_tables[table_name], "task_id", task_ids)
            inserted[table_name] = insert_missing(
                source_conn, target_conn, source_tables[table_name], target_tables[table_name], ids
            )

        for table_name in [
            "document_events",
            "document_links",
            "vehicle_document_records",
            "vehicle_document_record_tags",
            "vehicle_document_alerts",
            "vehicle_document_pending_actions",
        ]:
            ids = ids_by_column(source_conn, source_tables[table_name], "document_id", document_ids)
            inserted[table_name] = insert_missing(
                source_conn, target_conn, source_tables[table_name], target_tables[table_name], ids
            )

        print(json.dumps({"inserted": inserted}, ensure_ascii=False, indent=2))

        for table_name, total in inserted.items():
            if total <= 0:
                continue
            target_conn.execute(
                text(
                    f"""
                    select setval(
                      pg_get_serial_sequence('{table_name}', 'id'),
                      coalesce((select max(id) from {table_name}), 1),
                      true
                    )
                    """
                )
            )


if __name__ == "__main__":
    main()
