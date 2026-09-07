from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlalchemy import text

from app.core.database import SessionLocal
from app.services.invoice_audit import build_invoice_audit_dry_run


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inventaria faturas e simula a taxonomia sem escrever na base de dados."
    )
    parser.add_argument("--output", type=Path, help="Ficheiro JSON opcional para o relatório.")
    parser.add_argument("--skip-file-check", action="store_true")
    parser.add_argument("--hash-files", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as db:
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        report = build_invoice_audit_dry_run(
            db,
            verify_files=not args.skip_file_check,
            hash_files=args.hash_files,
        )
        db.rollback()

    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print(f"Relatório: {args.output}")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
