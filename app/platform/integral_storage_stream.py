"""Streaming archive for exact, fail-closed storage rehearsals."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

MAGIC = b"CARFAST-INTEGRAL-STORAGE\x00\x01"
MAX_HEADER_BYTES = 16 * 1024
MAX_OBJECT_BYTES = 20 * 1024 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024


class StorageStreamError(RuntimeError):
    pass


def _objects(root: Path) -> Iterator[tuple[Path, str]]:
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise StorageStreamError("storage root must be a directory")
    for path in sorted(resolved.rglob("*")):
        if path.is_symlink():
            raise StorageStreamError("storage symlinks are forbidden")
        if path.is_dir():
            continue
        if not path.is_file():
            raise StorageStreamError("unsupported storage object")
        yield path, path.relative_to(resolved).as_posix()


def _file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def pack_storage(root: Path, output: BinaryIO) -> tuple[int, int]:
    output.write(MAGIC)
    object_count = 0
    total_bytes = 0
    for path, relative in _objects(root):
        size, sha256 = _file_digest(path)
        if size > MAX_OBJECT_BYTES:
            raise StorageStreamError("storage object exceeds maximum size")
        header = json.dumps(
            {"path": relative, "size": size, "sha256": sha256},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(header) > MAX_HEADER_BYTES:
            raise StorageStreamError("storage object header is too large")
        output.write(struct.pack(">I", len(header)))
        output.write(header)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
                output.write(chunk)
        object_count += 1
        total_bytes += size
    output.write(struct.pack(">I", 0))
    return object_count, total_bytes


def _read_exact(source: BinaryIO, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = source.read(min(remaining, CHUNK_BYTES))
        if not chunk:
            raise StorageStreamError("truncated storage stream")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _safe_relative(raw: Any) -> PurePosixPath:
    if not isinstance(raw, str) or not raw or "\\" in raw or "\x00" in raw:
        raise StorageStreamError("invalid storage object path")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise StorageStreamError("unsafe storage object path")
    return path


def unpack_storage(source: BinaryIO, staging_root: Path) -> tuple[int, int]:
    if source.read(len(MAGIC)) != MAGIC:
        raise StorageStreamError("invalid storage stream magic")
    root = staging_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise StorageStreamError("storage staging root must be empty")
    object_count = 0
    total_bytes = 0
    seen: set[str] = set()
    try:
        while True:
            header_size = struct.unpack(">I", _read_exact(source, 4))[0]
            if header_size == 0:
                if source.read(1):
                    raise StorageStreamError("trailing bytes after storage stream")
                return object_count, total_bytes
            if header_size > MAX_HEADER_BYTES:
                raise StorageStreamError("storage object header is too large")
            try:
                header = json.loads(_read_exact(source, header_size))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise StorageStreamError("invalid storage object header") from exc
            if not isinstance(header, dict) or set(header) != {"path", "size", "sha256"}:
                raise StorageStreamError("invalid storage object header shape")
            relative = _safe_relative(header["path"])
            relative_text = relative.as_posix()
            if relative_text in seen:
                raise StorageStreamError("duplicate storage object path")
            seen.add(relative_text)
            size = header["size"]
            sha256 = header["sha256"]
            if type(size) is not int or not 0 <= size <= MAX_OBJECT_BYTES:
                raise StorageStreamError("invalid storage object size")
            if not isinstance(sha256, str) or len(sha256) != 64:
                raise StorageStreamError("invalid storage object digest")
            target = root.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".incoming")
            digest = hashlib.sha256()
            remaining = size
            with temporary.open("xb") as handle:
                while remaining:
                    chunk = source.read(min(remaining, CHUNK_BYTES))
                    if not chunk:
                        raise StorageStreamError("truncated storage object")
                    handle.write(chunk)
                    digest.update(chunk)
                    remaining -= len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if digest.hexdigest() != sha256:
                raise StorageStreamError("storage object digest mismatch")
            os.replace(temporary, target)
            object_count += 1
            total_bytes += size
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True, exist_ok=True)
        raise
