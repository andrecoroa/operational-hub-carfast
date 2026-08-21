from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.evolution_catalog_importer import import_evolution_catalog, load_catalog

DEFAULT_INPUT = Path(__file__).resolve().parents[1] / "data" / "evolution_catalog_2026-08-21.json"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Pré-visualiza ou importa, de modo idempotente, o catálogo da Evolução."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Confirma escrita; sem esta opção é dry-run.",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="URL SQLAlchemy explícita; omitida usa DATABASE_URL/configuração da aplicação.",
    )
    parser.add_argument("--report", type=Path, default=None, help="Guarda o relatório JSON.")
    args = parser.parse_args()

    items = load_catalog(args.input)
    if args.database_url:
        engine = create_engine(args.database_url, pool_pre_ping=True)
        session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    else:
        session_factory = SessionLocal

    with session_factory() as db:
        report = import_evolution_catalog(db, items, apply=args.apply)
        if args.apply:
            db.commit()
        else:
            db.rollback()

    payload = report.as_dict()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
