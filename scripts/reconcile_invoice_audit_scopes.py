from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.invoice_audit_readonly_export import reconcile_scope_rows


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Reconcilia dois universos por document_id.")
    parser.add_argument("--old-csv", required=True, type=Path)
    parser.add_argument("--current-csv", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    rows, counts = reconcile_scope_rows(_read_csv(args.old_csv), _read_csv(args.current_csv))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with (args.output_dir / "scope_reconciliation.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]) if rows else ["document_id"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(rows)
    (args.output_dir / "scope_reconciliation_summary.json").write_text(
        json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
