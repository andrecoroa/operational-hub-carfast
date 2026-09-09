from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from app.services.invoice_service_remediation import build_document_service_proposals


ACCEPTANCE_DOCUMENTS = {688, 756, 816, 1122}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    headers = list(rows[0])
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, delimiter=";")
        writer.writeheader()
        writer.writerows({header: row.get(header, "") for header in headers} for row in rows)


def decimal(value: Any) -> Decimal:
    return Decimal(str(value or "0").replace(",", "."))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a read-only invoice-service remediation dry-run.")
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--legacy-canonical", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--base-url", default="https://carfast-green.onrender.com")
    args = parser.parse_args()

    documents = read_csv(args.source_dir / "documents.csv")
    lines = read_csv(args.source_dir / "lines.csv")
    legacy_rows = json.loads(args.legacy_canonical.read_text(encoding="utf-8"))
    blocked_rows = [row for row in legacy_rows if not row.get("eligible_for_counting")]
    if len(blocked_rows) != 716:
        raise RuntimeError(f"Formal exclusion invariant failed: expected 716, found {len(blocked_rows)}")

    lines_by_document: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in lines:
        lines_by_document[row["document_id"]].append(row)

    eligible_documents = [
        row for row in documents if row.get("eligible_for_counting", "").casefold() == "true"
    ]
    generated: list[dict[str, Any]] = []
    reconciliations: list[dict[str, Any]] = []
    missing_rows: list[dict[str, Any]] = []
    projections: Counter[str] = Counter()
    for document in eligible_documents:
        document_id = document["document_id"]
        result = build_document_service_proposals(document, lines_by_document.get(document_id, []))
        projections[result["document_projection"]] += 1
        document_link = (
            f"{args.base_url}/v2-clean/fleet/{document['vehicle_id_associated']}/documents"
            f"?classified=1&main_group=invoices&open_item=document%3A{document_id}"
        )
        for service in result["services"]:
            generated.append(
                {
                    "stable_key": service["stable_key"],
                    "vehicle_id": int(document["vehicle_id_associated"]),
                    "plate": document.get("vehicle_plate_associated") or document.get("plate_extracted") or "",
                    "vin": document.get("vehicle_vin_associated") or document.get("vin_extracted") or document.get("vin_source") or "",
                    "document_id": int(document_id),
                    "document_number": document.get("document_number_extracted") or document.get("document_number_record") or "",
                    "document_date": document.get("document_date_extracted") or document.get("document_date_record") or "",
                    "odometer_km": document.get("km_source") or "",
                    "category": service["service_code"].split(".", 1)[0],
                    "service_code": service["service_code"],
                    "subcategory": service["subcategory"],
                    "axle": service["axle"],
                    "source_line_ids": service["source_line_ids"],
                    "source_descriptions": service["service_text"],
                    "parts": service["parts"],
                    "labor": service["labor"],
                    "service_amount": decimal(service["amount"]),
                    "confidence": decimal(service["confidence"]),
                    "confidence_reason": service["confidence_reason"],
                    "document_projection": result["document_projection"],
                    "invoice_link": document_link,
                    "approve": "",
                    "correct": "",
                    "exclude": "",
                }
            )
        for line in result["unassigned_lines"]:
            if line["role"] != "ancillary" and decimal(line["amount"]) != 0:
                missing_rows.append(
                    {
                        "document_id": int(document_id),
                        "document_number": document.get("document_number_extracted") or "",
                        "source_line_id": line["source_line_id"],
                        "description": line["description"],
                        "amount": decimal(line["amount"]),
                        "reason": line["reason"],
                    }
                )
        reconciliation = result["reconciliation"]
        reconciliations.append(
            {
                "document_id": int(document_id),
                "document_number": document.get("document_number_extracted") or "",
                "invoice_total": decimal(reconciliation["invoice_total"]),
                "source_line_total": decimal(reconciliation["source_line_total"]),
                "service_total": decimal(reconciliation["service_total"]),
                "excluded_or_unassigned_total": decimal(reconciliation["excluded_or_unassigned_total"]),
                "invoice_minus_source_lines": decimal(reconciliation["invoice_minus_source_lines"]),
                "allocation_check": decimal(reconciliation["service_plus_excluded_minus_source_lines"]),
                "document_projection": result["document_projection"],
            }
        )

    stable_counts = Counter(row["stable_key"] for row in generated)
    duplicate_keys = sorted(key for key, count in stable_counts.items() if count > 1)
    frequencies = Counter((row["service_code"], row["axle"] or "unspecified") for row in generated)
    frequency_rows = [
        {"service_code": code, "axle": axle, "count": count}
        for (code, axle), count in sorted(frequencies.items())
    ]
    acceptance = {
        str(document_id): {
            "present": any(row["document_id"] == document_id for row in generated),
            "service_count": sum(row["document_id"] == document_id for row in generated),
            "codes": sorted({row["service_code"] for row in generated if row["document_id"] == document_id}),
            "allocated_amount": str(sum((row["service_amount"] for row in generated if row["document_id"] == document_id), Decimal("0"))),
        }
        for document_id in sorted(ACCEPTANCE_DOCUMENTS)
    }
    if not all(item["present"] for item in acceptance.values()):
        raise RuntimeError(f"Acceptance documents missing proposals: {acceptance}")
    if duplicate_keys:
        raise RuntimeError(f"Duplicate stable keys: {duplicate_keys[:10]}")
    if any(row["allocation_check"] != 0 for row in reconciliations):
        raise RuntimeError("A source line amount was duplicated or omitted from invoice reconciliation")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_json = args.output_dir / "invoice_service_remediation_dry_run.json"
    output_json.write_text(
        json.dumps(
            {
                "schema": "carfast.invoice-service-remediation-dry-run.v2",
                "read_only": True,
                "write_operations": 0,
                "source_manifest_sha256": sha256(args.source_dir / "manifest.json"),
                "legacy_canonical_sha256": sha256(args.legacy_canonical),
                "blocked_ledger": {
                    "count": len(blocked_rows),
                    "document_count": len({row["document_id"] for row in blocked_rows}),
                    "rows_sha256": hashlib.sha256(
                        json.dumps(blocked_rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
                    ).hexdigest(),
                    "policy": "formally excluded; no correction or association attempted",
                },
                "summary": {
                    "eligible_documents": len(eligible_documents),
                    "service_rows": len(generated),
                    "documents_with_services": len({row["document_id"] for row in generated}),
                    "duplicate_stable_keys": duplicate_keys,
                    "unassigned_relevant_lines": len(missing_rows),
                    "document_projections": dict(projections),
                    "service_amount_total": str(sum((row["service_amount"] for row in generated), Decimal("0"))),
                    "invoice_total": str(sum((row["invoice_total"] for row in reconciliations), Decimal("0"))),
                    "source_line_total": str(sum((row["source_line_total"] for row in reconciliations), Decimal("0"))),
                },
                "acceptance_documents": acceptance,
                "services": [{**row, "service_amount": str(row["service_amount"]), "confidence": str(row["confidence"])} for row in generated],
                "reconciliations": [{**row, **{key: str(value) for key, value in row.items() if isinstance(value, Decimal)}} for row in reconciliations],
                "frequencies": frequency_rows,
                "missing_lines": [{**row, "amount": str(row["amount"])} for row in missing_rows],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_csv(args.output_dir / "invoice_service_validation_rows.csv", generated)
    write_csv(args.output_dir / "invoice_service_reconciliation.csv", reconciliations)
    write_csv(args.output_dir / "invoice_service_missing_lines.csv", missing_rows)
    write_csv(args.output_dir / "invoice_service_frequency.csv", frequency_rows)
    report = [
        "# Dry-run global de remediação de serviços",
        "",
        "- Execução apenas sobre o snapshot local; `write_operations = 0`.",
        f"- Documentos elegíveis: {len(eligible_documents)}.",
        f"- Linhas de serviço propostas: {len(generated)}.",
        f"- Documentos com serviços: {len({row['document_id'] for row in generated})}.",
        f"- Linhas bloqueadas formalmente excluídas: {len(blocked_rows)}.",
        f"- Chaves duplicadas: {len(duplicate_keys)}.",
        f"- Linhas relevantes sem classificação: {len(missing_rows)}.",
        f"- Projeções documentais: {dict(projections)}.",
        "",
        "## Casos de aceitação",
        "",
    ]
    report.extend(f"- Documento {doc}: {value}" for doc, value in acceptance.items())
    (args.output_dir / "DRY_RUN_REMEDIATION_REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output_json), "summary": json.loads(output_json.read_text(encoding="utf-8"))["summary"], "acceptance": acceptance}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
