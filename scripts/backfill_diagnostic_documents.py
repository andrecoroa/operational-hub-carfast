from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.diagnostic_documents import backfill_legacy_diagnostics


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Classifica diagnósticos legados e tenta associá-los à viatura."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Confirma as alterações. Sem esta opção a transação é revertida.",
    )
    args = parser.parse_args()

    with SessionLocal() as db:
        stats = backfill_legacy_diagnostics(db)
        if args.apply:
            db.commit()
        else:
            db.rollback()
        print(json.dumps({**stats, "applied": args.apply}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
