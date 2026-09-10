from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal
from app.services.invoice_audit_readonly_export import (
    DOCUMENT_COLUMNS,
    ISSUE_COLUMNS,
    LINE_COLUMNS,
    SERVICE_COLUMNS,
    build_readonly_export,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def _read_plates(path: Path | None) -> list[str]:
    if not path:
        return []
    return [
        line.strip() for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()
    ]


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter=";", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export nominal de auditoria; base de dados read-only."
    )
    parser.add_argument("--scope-csv", required=True, type=Path)
    parser.add_argument("--scope-sha256", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--historical-plates", type=Path)
    parser.add_argument("--source-revision", default="unknown")
    parser.add_argument("--taxonomy-version", default="1.1.0-draft")
    parser.add_argument("--expected-documents", type=int, default=1278)
    parser.add_argument("--expected-blockers", type=int, default=103)
    parser.add_argument("--expected-human-protected", type=int, default=9)
    parser.add_argument("--allow-count-mismatch", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _args()
    actual_scope_sha256 = _sha256(args.scope_csv)
    if actual_scope_sha256.lower() != args.scope_sha256.strip().lower():
        raise SystemExit(
            "scope CSV com SHA-256 divergente: "
            f"esperado={args.scope_sha256}; atual={actual_scope_sha256}"
        )
    scope_rows = _read_csv(args.scope_csv)
    required = {"document_id", "technical_blocker", "human_protected"}
    missing = required - set(scope_rows[0] if scope_rows else {})
    if missing:
        raise SystemExit(f"scope CSV sem colunas obrigatórias: {sorted(missing)}")

    with SessionLocal() as db:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        bundle = build_readonly_export(
            db,
            scope_rows,
            run_id=args.run_id,
            historical_plates=_read_plates(args.historical_plates),
            expected_documents=args.expected_documents,
            expected_blockers=args.expected_blockers,
            expected_human_protected=args.expected_human_protected,
            source_revision=args.source_revision,
            taxonomy_version=args.taxonomy_version,
        )
        db.rollback()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "manifest.json").write_text(
        json.dumps(bundle.manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not bundle.manifest["acceptance_passed"] and not args.allow_count_mismatch:
        print(json.dumps(bundle.manifest["count_mismatches"], ensure_ascii=False), file=sys.stderr)
        return 2
    _write_csv(args.output_dir / "documents.csv", DOCUMENT_COLUMNS, bundle.documents)
    _write_csv(args.output_dir / "lines.csv", LINE_COLUMNS, bundle.lines)
    _write_csv(args.output_dir / "services.csv", SERVICE_COLUMNS, bundle.services)
    _write_csv(args.output_dir / "issues.csv", ISSUE_COLUMNS, bundle.issues)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
