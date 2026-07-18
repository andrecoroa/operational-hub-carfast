from __future__ import annotations

import json
import os
from typing import Any

from sqlalchemy import MetaData, create_engine, func, select, text


def db_url(env_name: str) -> str:
    url = os.environ[env_name]
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def process_ids(conn: Any) -> list[int]:
    return [
        int(row[0])
        for row in conn.execute(select(text("id")).select_from(text("workshop_phased_processes"))).all()
    ]


def linked_tables(conn: Any) -> list[str]:
    rows = conn.execute(
        text(
            """
            select table_name
            from information_schema.columns
            where table_schema = 'public'
              and column_name = 'process_id'
            order by table_name
            """
        )
    ).all()
    return [str(row[0]) for row in rows]


def counts_for(conn: Any, metadata: MetaData, table_name: str, ids: list[int]) -> int:
    if table_name not in metadata.tables or not ids:
        return 0
    table = metadata.tables[table_name]
    return int(conn.scalar(select(func.count()).select_from(table).where(table.c.process_id.in_(ids))) or 0)


def main() -> None:
    source_engine = create_engine(db_url("SOURCE_DATABASE_URL"))
    target_engine = create_engine(db_url("TARGET_DATABASE_URL"))

    with source_engine.connect() as source_conn, target_engine.connect() as target_conn:
        table_names = sorted(set(linked_tables(source_conn)) | set(linked_tables(target_conn)))
        source_ids = process_ids(source_conn)
        target_ids = process_ids(target_conn)

        source_md = MetaData()
        target_md = MetaData()
        source_md.reflect(bind=source_engine, only=table_names)
        target_md.reflect(bind=target_engine, only=table_names)

        rows = []
        for table_name in table_names:
            source_count = counts_for(source_conn, source_md, table_name, source_ids)
            target_count = counts_for(target_conn, target_md, table_name, target_ids)
            rows.append(
                {
                    "table": table_name,
                    "source_rows": source_count,
                    "target_rows": target_count,
                    "diff_source_minus_target": source_count - target_count,
                }
            )

    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
