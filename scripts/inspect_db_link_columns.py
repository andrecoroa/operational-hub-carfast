from __future__ import annotations

import json
import os

from sqlalchemy import create_engine, text


def main() -> None:
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url)
    query = text(
        """
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'public'
          and column_name in ('process_id', 'document_id', 'task_id', 'vehicle_id')
        order by table_name, column_name
        """
    )
    with engine.connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(query).all()]
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
