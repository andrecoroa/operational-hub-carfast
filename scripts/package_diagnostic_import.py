from __future__ import annotations

import argparse
import csv
import hashlib
import json
import zipfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceFile:
    path: Path
    source_root: Path
    sha256: str
    size: int


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_pdfs(source_roots: list[Path]) -> tuple[list[SourceFile], int]:
    unique: dict[str, SourceFile] = {}
    duplicate_count = 0
    for root in source_roots:
        for path in sorted(root.rglob("*.pdf")):
            digest = file_sha256(path)
            if digest in unique:
                duplicate_count += 1
                continue
            unique[digest] = SourceFile(
                path=path,
                source_root=root,
                sha256=digest,
                size=path.stat().st_size,
            )
    return list(unique.values()), duplicate_count


def archive_name(item: SourceFile, root_index: int) -> str:
    relative = item.path.relative_to(item.source_root)
    return str(Path(f"fonte_{root_index:02d}") / relative).replace("\\", "/")


def package_files(
    files: list[SourceFile],
    source_roots: list[Path],
    output_dir: Path,
    *,
    max_files: int,
    max_bytes: int,
) -> list[dict[str, object]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    packages: list[dict[str, object]] = []
    package_number = 0
    current_zip: zipfile.ZipFile | None = None
    current_row: dict[str, object] | None = None

    try:
        for item in files:
            needs_package = (
                current_row is None
                or int(current_row["file_count"]) >= max_files
                or int(current_row["source_bytes"]) + item.size > max_bytes
            )
            if needs_package:
                if current_zip:
                    current_zip.close()
                package_number += 1
                zip_path = output_dir / f"diagnosticos_historicos_{package_number:02d}.zip"
                current_zip = zipfile.ZipFile(
                    zip_path,
                    "w",
                    compression=zipfile.ZIP_DEFLATED,
                    compresslevel=6,
                )
                current_row = {
                    "package": zip_path.name,
                    "file_count": 0,
                    "source_bytes": 0,
                    "files": [],
                }
                packages.append(current_row)

            root_index = source_roots.index(item.source_root) + 1
            member_name = archive_name(item, root_index)
            current_zip.write(item.path, member_name)
            current_row["file_count"] = int(current_row["file_count"]) + 1
            current_row["source_bytes"] = int(current_row["source_bytes"]) + item.size
            current_row["files"].append(
                {
                    "archive_path": member_name,
                    "source_path": str(item.path),
                    "sha256": item.sha256,
                    "size": item.size,
                }
            )
    finally:
        if current_zip:
            current_zip.close()

    for package in packages:
        zip_path = output_dir / str(package["package"])
        package["archive_bytes"] = zip_path.stat().st_size
        package["archive_sha256"] = file_sha256(zip_path)
    return packages


def write_manifest(
    output_dir: Path,
    source_roots: list[Path],
    packages: list[dict[str, object]],
    duplicate_count: int,
) -> None:
    summary = {
        "schema": "carfast.diagnostic-import-packages.v1",
        "source_roots": [str(root) for root in source_roots],
        "unique_files": sum(int(package["file_count"]) for package in packages),
        "exact_duplicates_skipped": duplicate_count,
        "packages": packages,
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with (output_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "package",
                "archive_path",
                "source_path",
                "sha256",
                "size",
            ],
        )
        writer.writeheader()
        for package in packages:
            for item in package["files"]:
                writer.writerow({"package": package["package"], **item})


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cria ZIPs auditáveis e sem duplicados exatos para importar diagnósticos."
    )
    parser.add_argument("sources", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-files", type=int, default=250)
    parser.add_argument("--max-mb", type=int, default=70)
    args = parser.parse_args()

    source_roots = [path.resolve() for path in args.sources]
    missing = [str(path) for path in source_roots if not path.is_dir()]
    if missing:
        raise SystemExit(f"Pastas inexistentes: {', '.join(missing)}")
    if args.max_files < 1 or args.max_mb < 1:
        raise SystemExit("Os limites de ficheiros e tamanho têm de ser positivos.")

    files, duplicate_count = unique_pdfs(source_roots)
    packages = package_files(
        files,
        source_roots,
        args.output.resolve(),
        max_files=args.max_files,
        max_bytes=args.max_mb * 1024 * 1024,
    )
    write_manifest(
        args.output.resolve(),
        source_roots,
        packages,
        duplicate_count,
    )
    print(
        json.dumps(
            {
                "unique_files": len(files),
                "exact_duplicates_skipped": duplicate_count,
                "packages": [
                    {
                        key: value
                        for key, value in package.items()
                        if key != "files"
                    }
                    for package in packages
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
