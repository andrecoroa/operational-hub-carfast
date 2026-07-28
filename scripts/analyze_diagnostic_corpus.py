from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.diagnostic_ocr import extract_diagnostic_pdf, parse_diagnostic_filename


def selected_samples(
    files: list[Path],
    *,
    sample_per_family: int,
    process_all: bool,
) -> list[Path]:
    if process_all:
        return files
    selected: list[Path] = []
    counts: Counter[tuple[str | None, str | None]] = Counter()
    for path in files:
        metadata = parse_diagnostic_filename(path.name)
        key = (metadata.get("machine_prefix"), metadata.get("family"))
        if counts[key] >= sample_per_family:
            continue
        counts[key] += 1
        selected.append(path)
    return selected


def analyze_file(path: Path, *, enable_ocr: bool) -> dict[str, Any]:
    payload = extract_diagnostic_pdf(path, enable_ocr=enable_ocr)
    dynamic_fields = payload.get("dynamic_fields") or {}
    return {
        "path": str(path),
        "filename": path.name,
        "machine": payload["source_machine"],
        "family": payload.get("source_family"),
        "sha256": payload["source_sha256"],
        "pages": payload["source_page_count"],
        "native_characters": len(payload.get("native_text") or ""),
        "ocr_characters": len(payload.get("ocr_text") or ""),
        "confidence": payload.get("confidence"),
        "normalized": payload.get("normalized") or {},
        "observation_count": len(dynamic_fields.get("observations") or []),
        "observation_labels": [
            field.get("label") for field in dynamic_fields.get("observations") or []
        ],
        "dtc_count": len(dynamic_fields.get("dtcs") or []),
        "warnings": payload.get("warnings") or [],
    }


def corpus_summary(files: list[Path], analyses: list[dict[str, Any]]) -> dict[str, Any]:
    filename_groups: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    for path in files:
        metadata = parse_diagnostic_filename(path.name)
        machine = metadata.get("machine_prefix") or "?"
        family = metadata.get("family") or "?"
        filename_groups[machine] += 1
        family_counts[f"{machine}:{family}"] += 1

    field_labels: defaultdict[str, set[str]] = defaultdict(set)
    for result in analyses:
        key = f"{result['machine']}:{result.get('family') or '?'}"
        field_labels[key].update(
            label for label in result.get("observation_labels") or [] if label
        )
    return {
        "file_count": len(files),
        "total_bytes": sum(path.stat().st_size for path in files),
        "filename_machine_counts": dict(sorted(filename_groups.items())),
        "filename_family_counts": dict(sorted(family_counts.items())),
        "analyzed_count": len(analyses),
        "analysis_machine_counts": dict(
            sorted(Counter(result["machine"] for result in analyses).items())
        ),
        "files_without_native_text": sum(
            result["native_characters"] == 0 for result in analyses
        ),
        "files_with_warnings": sum(bool(result["warnings"]) for result in analyses),
        "field_labels_by_machine_family": {
            key: sorted(values) for key, values in sorted(field_labels.items())
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audita leitores Autel/Stellantis sem alterar os PDFs originais."
    )
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--sample-per-family", type=int, default=2)
    parser.add_argument("--all", action="store_true", dest="process_all")
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Executa Tesseract apenas nas páginas sem texto nativo suficiente.",
    )
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"Pasta não encontrada: {root}")

    files = sorted(root.rglob("*.pdf"), key=lambda path: str(path).casefold())
    samples = selected_samples(
        files,
        sample_per_family=max(args.sample_per_family, 1),
        process_all=args.process_all,
    )
    analyses: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for index, path in enumerate(samples, start=1):
        try:
            analyses.append(analyze_file(path, enable_ocr=args.ocr))
        except Exception as exc:
            errors.append({"path": str(path), "error": repr(exc)})
        if index % 25 == 0 or index == len(samples):
            print(f"analisados {index}/{len(samples)}", flush=True)

    report = {
        "root": str(root),
        "summary": corpus_summary(files, analyses),
        "files": analyses,
        "errors": errors,
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(f"RELATORIO={args.output}")
    else:
        print(rendered)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
