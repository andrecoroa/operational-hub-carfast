from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

IMPORT_HEADERS = [
    "stable_key",
    "document_id",
    "service_text",
    "service_code",
    "service_date",
    "odometer_km",
    "axle",
    "supplier_name",
    "amount",
    "status",
    "evidence",
    "source_line_ids",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def write_csv(path: Path, rows: list[dict[str, Any]], headers: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter=";")
        writer.writeheader()
        writer.writerows({header: row.get(header, "") for header in headers} for row in rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "sim"}


def import_row(service: dict[str, Any]) -> dict[str, Any]:
    return {
        "stable_key": service["stable_key"],
        "document_id": int(service["document_id"]),
        "service_text": service.get("service_text") or service["service_code"],
        "service_code": service["service_code"],
        "service_date": service.get("service_date", ""),
        "odometer_km": service.get("odometer_km", ""),
        "axle": service.get("axle", ""),
        "supplier_name": service.get("supplier_name", ""),
        "amount": service.get("amount", ""),
        "status": "pending_validation",
        "evidence": service.get("evidence", ""),
        "source_line_ids": service.get("source_line_ids", ""),
    }


def build_package(
    dry_run_path: Path,
    documents_path: Path,
    legacy_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    dry_run = json.loads(dry_run_path.read_text(encoding="utf-8"))
    if dry_run.get("schema") != "carfast.invoice-service-remediation-dry-run.v2":
        raise ValueError("Unsupported remediation dry-run schema")
    documents = read_csv(documents_path)
    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
    allowlist = {
        int(row["document_id"]) for row in documents if is_true(row.get("eligible_for_counting"))
    }
    blocked_rows = [row for row in legacy if not is_true(row.get("eligible_for_counting"))]
    denylist = {
        int(row["document_id"]) for row in blocked_rows if row.get("document_id") not in (None, "")
    }
    if allowlist & denylist:
        raise ValueError("Allowlist and denylist overlap")
    if len(allowlist) != int(dry_run["summary"]["eligible_documents"]):
        raise ValueError("Eligible document count differs from the dry-run")
    if len(blocked_rows) != int(dry_run["blocked_ledger"]["count"]):
        raise ValueError("Blocked ledger count differs from the dry-run")

    by_vehicle: dict[int, list[dict[str, Any]]] = defaultdict(list)
    stable_keys: set[str] = set()
    proposal_documents: set[int] = set()
    for service in dry_run.get("services", []):
        document_id = int(service["document_id"])
        if document_id not in allowlist or document_id in denylist:
            raise ValueError(f"Service outside authorized scope: document {document_id}")
        stable_key = str(service["stable_key"])
        if stable_key in stable_keys:
            raise ValueError(f"Duplicate stable key: {stable_key}")
        stable_keys.add(stable_key)
        proposal_documents.add(document_id)
        by_vehicle[int(service["vehicle_id"])].append(import_row(service))

    reconciliations = dry_run.get("reconciliations", [])
    reconciliation_ids = {int(row["document_id"]) for row in reconciliations}
    if reconciliation_ids != allowlist:
        raise ValueError("Reconciliation scope differs from the eligible allowlist")
    review_rows = [
        {
            "document_id": int(row["document_id"]),
            "reconciliation_status": row.get("reconciliation_status", ""),
            "classification_blockers": row.get("classification_blockers", ""),
        }
        for row in reconciliations
        if row.get("document_projection") != "services_classified"
    ]
    review_ids = {row["document_id"] for row in review_rows}

    output_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for vehicle_id, rows in sorted(by_vehicle.items()):
        path = output_dir / "per_vehicle" / f"vehicle_{vehicle_id}.csv"
        write_csv(path, rows, IMPORT_HEADERS)
        files.append(
            {
                "vehicle_id": vehicle_id,
                "rows": len(rows),
                "sha256": sha256(path),
                "file": path.name,
            }
        )
    write_csv(
        output_dir / "review_queue.csv",
        sorted(review_rows, key=lambda row: row["document_id"]),
        ["document_id", "reconciliation_status", "classification_blockers"],
    )
    write_csv(
        output_dir / "allowlist.csv",
        [{"document_id": value} for value in sorted(allowlist)],
        ["document_id"],
    )
    write_csv(
        output_dir / "denylist.csv",
        [{"document_id": value} for value in sorted(denylist)],
        ["document_id"],
    )
    manifest = {
        "schema": "carfast.invoice-service-import-package.v1",
        "dry_run_sha256": sha256(dry_run_path),
        "allowlist_documents": len(allowlist),
        "blocked_rows": len(blocked_rows),
        "denylist_documents": len(denylist),
        "proposal_documents": len(proposal_documents),
        "review_documents": len(review_ids),
        "technically_classifiable_documents": len(allowlist - review_ids),
        "proposal_rows": sum(len(rows) for rows in by_vehicle.values()),
        "vehicle_batches": len(files),
        "forced_status": "pending_validation",
        "files": files,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Package a remediation dry-run into guarded per-vehicle files."
    )
    parser.add_argument("--dry-run", type=Path, required=True)
    parser.add_argument("--documents", type=Path, required=True)
    parser.add_argument("--legacy-canonical", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = build_package(args.dry_run, args.documents, args.legacy_canonical, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
