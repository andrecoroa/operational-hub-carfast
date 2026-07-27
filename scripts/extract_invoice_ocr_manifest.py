from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import sys
import time
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.web.router import (
    BATCH_DOCUMENT_EXTENSIONS,
    _batch_document_pdf_text,
    _batch_invoice_payload,
    _invoice_payload_was_extracted,
)


SCHEMA = "carfast.invoice-ocr-manifest.v1"


def _write_manifest(path: Path, manifest: dict) -> None:
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def _load_manifest(path: Path, source: Path) -> dict:
    if path.exists():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema") != SCHEMA:
            raise ValueError("O manifesto existente tem um formato incompatível.")
        return manifest
    return {
        "schema": SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "source_archive": source.name,
        "documents": [],
    }


def extract_archive(source: Path, output: Path) -> dict:
    manifest = _load_manifest(output, source)
    completed = {
        item.get("file_hash")
        for item in manifest.get("documents", [])
        if item.get("file_hash")
    }
    with zipfile.ZipFile(source) as archive:
        entries = [
            entry
            for entry in archive.infolist()
            if not entry.is_dir()
            and Path(entry.filename).suffix.lower() in BATCH_DOCUMENT_EXTENSIONS
        ]
        for index, entry in enumerate(entries, start=1):
            content = archive.read(entry)
            digest = hashlib.sha256(content).hexdigest()
            if digest in completed:
                print(f"[{index}/{len(entries)}] já extraído: {entry.filename}", flush=True)
                continue
            started = time.monotonic()
            result = {
                "file_hash": digest,
                "archive_name": entry.filename.replace("\\", "/"),
                "original_name": Path(entry.filename).name,
                "status": "failed",
                "payload": {},
                "error": "",
            }
            try:
                suffix = Path(entry.filename).suffix.lower()
                text = _batch_document_pdf_text(content, suffix)
                payload = _batch_invoice_payload(
                    content,
                    suffix,
                    result["original_name"],
                    existing_text=text,
                )
                extracted = _invoice_payload_was_extracted(payload)
                result["status"] = "extracted" if extracted else "failed"
                result["payload"] = payload
                if not extracted:
                    result["error"] = "no_structured_ocr_result"
            except Exception as exc:  # noqa: BLE001
                result["error"] = f"{exc.__class__.__name__}: {exc}"
            result["elapsed_seconds"] = round(time.monotonic() - started, 3)
            manifest["documents"].append(result)
            completed.add(digest)
            manifest["updated_at"] = datetime.now(UTC).isoformat()
            _write_manifest(output, manifest)
            print(
                f"[{index}/{len(entries)}] {result['status']}: "
                f"{entry.filename} ({result['elapsed_seconds']}s)",
                flush=True,
            )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extrai OCR de faturas localmente e cria um manifesto retomável.",
    )
    parser.add_argument("archive", type=Path, help="Arquivo ZIP com as faturas")
    parser.add_argument("output", type=Path, help="Ficheiro JSON de saída")
    args = parser.parse_args()
    manifest = extract_archive(args.archive.resolve(), args.output.resolve())
    extracted = sum(item.get("status") == "extracted" for item in manifest["documents"])
    failed = len(manifest["documents"]) - extracted
    print(f"Concluído: {extracted} extraídos; {failed} falharam.", flush=True)


if __name__ == "__main__":
    main()
