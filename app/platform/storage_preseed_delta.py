"""Fail-closed storage preseed and final-delta primitives.

The transport is deliberately outside this module.  Every object delivered by a
standard encrypted transport is accepted only after its plaintext size and
SHA-256 match the closed manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath

from app.platform.integral_reconciliation import IntegralReconciliationError, StorageEvidence

CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class StorageDelta:
    copy: tuple[StorageEvidence, ...]
    remove: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CopyResult:
    copied: int
    skipped: int
    bytes_copied: int


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise IntegralReconciliationError(f"unsafe storage path: {value!r}")
    return path


def validate_storage_manifest(items: tuple[StorageEvidence, ...]) -> None:
    folded: dict[str, str] = {}
    previous = ""
    for item in items:
        _safe_relative(item.path)
        if unicodedata.normalize("NFC", item.path) != item.path:
            raise IntegralReconciliationError(f"storage path is not NFC: {item.path!r}")
        if item.path <= previous:
            raise IntegralReconciliationError("storage manifest paths must be unique and sorted")
        previous = item.path
        key = item.path.casefold()
        if key in folded and folded[key] != item.path:
            raise IntegralReconciliationError("storage manifest contains case-colliding paths")
        folded[key] = item.path
        if (
            item.size < 0
            or len(item.sha256) != 64
            or any(c not in "0123456789abcdef" for c in item.sha256)
        ):
            raise IntegralReconciliationError(f"invalid storage evidence: {item.path}")


def _digest_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _assert_confined_parent(root: Path, relative: PurePosixPath, *, create: bool) -> Path:
    current = root
    for component in relative.parts[:-1]:
        current = current / component
        if current.exists() and (current.is_symlink() or not current.is_dir()):
            raise IntegralReconciliationError(f"unsafe storage parent: {relative.as_posix()}")
        if not current.exists():
            if not create:
                raise IntegralReconciliationError(f"missing storage parent: {relative.as_posix()}")
            current.mkdir()
        if current.is_symlink() or not current.resolve().is_relative_to(root):
            raise IntegralReconciliationError(f"storage path escaped root: {relative.as_posix()}")
    return root.joinpath(*relative.parts)


def _open_source_regular(path: Path):
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    metadata = os.fstat(descriptor)
    if not stat.S_ISREG(metadata.st_mode) or (os.name != "nt" and metadata.st_nlink != 1):
        os.close(descriptor)
        raise IntegralReconciliationError(f"source is not a unique regular file: {path}")
    return os.fdopen(descriptor, "rb"), metadata


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _walk_regular(root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    root_device = root.stat(follow_symlinks=False).st_dev
    casefold_paths: dict[str, str] = {}

    def visit(directory: Path) -> None:
        for entry in sorted(os.scandir(directory), key=lambda item: item.name):
            mode = entry.stat(follow_symlinks=False).st_mode
            metadata = entry.stat(follow_symlinks=False)
            path = Path(entry.path)
            if os.name != "nt" and metadata.st_dev != root_device:
                raise IntegralReconciliationError(f"storage mount boundary is forbidden: {path}")
            if stat.S_ISLNK(mode):
                raise IntegralReconciliationError(f"storage symlink is forbidden: {path}")
            if stat.S_ISDIR(mode):
                visit(path)
            elif stat.S_ISREG(mode):
                if os.name != "nt" and metadata.st_nlink != 1:
                    raise IntegralReconciliationError(f"storage hardlink is forbidden: {path}")
                relative = path.relative_to(root).as_posix()
                folded = relative.casefold()
                if folded in casefold_paths and casefold_paths[folded] != relative:
                    raise IntegralReconciliationError(
                        f"case-colliding storage paths are forbidden: "
                        f"{casefold_paths[folded]!r}, {relative!r}"
                    )
                casefold_paths[folded] = relative
                result.append(path)
            else:
                raise IntegralReconciliationError(f"unsupported storage object: {path}")

    visit(root)
    return tuple(result)


def build_stable_storage_manifest(
    root: Path, *, synthetic_only: bool = False
) -> tuple[StorageEvidence, ...]:
    """Hash synthetic fixtures; the real Linux scanner must use dirfd/openat."""
    if not synthetic_only:
        raise IntegralReconciliationError(
            "pathname scanner is synthetic-only; real storage requires audited dirfd/openat"
        )
    resolved = root.resolve(strict=True)
    if not resolved.is_dir():
        raise IntegralReconciliationError("storage root must be a directory")
    evidence: list[StorageEvidence] = []
    for path in _walk_regular(resolved):
        before = path.stat(follow_symlinks=False)
        size, digest = _digest_file(path)
        after = path.stat(follow_symlinks=False)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if identity_before != identity_after or size != after.st_size:
            raise IntegralReconciliationError(
                f"storage object changed while hashing: {path.relative_to(resolved).as_posix()}"
            )
        evidence.append(StorageEvidence(path.relative_to(resolved).as_posix(), size, digest))
    result = tuple(sorted(evidence, key=lambda item: item.path))
    validate_storage_manifest(result)
    return result


def storage_manifest_digest(items: tuple[StorageEvidence, ...]) -> str:
    validate_storage_manifest(items)
    payload = [asdict(item) for item in items]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def calculate_delta(
    preseed: tuple[StorageEvidence, ...], final: tuple[StorageEvidence, ...]
) -> StorageDelta:
    validate_storage_manifest(preseed)
    validate_storage_manifest(final)
    before = {item.path: item for item in preseed}
    after = {item.path: item for item in final}
    return StorageDelta(
        copy=tuple(after[path] for path in sorted(after) if before.get(path) != after[path]),
        remove=tuple(sorted(set(before) - set(after))),
    )


def sync_manifest(
    source: Path,
    target: Path,
    desired: tuple[StorageEvidence, ...],
    *,
    remove: tuple[str, ...] = (),
    interrupt_after: int | None = None,
    synthetic_only: bool = False,
) -> CopyResult:
    """Idempotently materialize verified objects using temp+replace.

    ``interrupt_after`` exists solely to prove resumability in synthetic tests.
    """
    if not synthetic_only:
        raise IntegralReconciliationError(
            "pathname sync is synthetic-only; real storage requires audited dirfd/openat"
        )
    source = source.resolve(strict=True)
    target.mkdir(parents=True, exist_ok=True)
    target = target.resolve(strict=True)
    validate_storage_manifest(desired)
    if set(remove) & {item.path for item in desired}:
        raise IntegralReconciliationError("storage copy/remove sets overlap")
    if tuple(sorted(set(remove))) != remove:
        raise IntegralReconciliationError("storage remove paths must be unique and sorted")
    copied = skipped = bytes_copied = 0
    for item in desired:
        relative = _safe_relative(item.path)
        src = _assert_confined_parent(source, relative, create=False)
        dst = _assert_confined_parent(target, relative, create=True)
        if dst.is_symlink():
            raise IntegralReconciliationError(f"target symlink is forbidden: {item.path}")
        if dst.exists() and _digest_file(dst) == (item.size, item.sha256):
            skipped += 1
            continue
        if interrupt_after is not None and copied >= interrupt_after:
            raise InterruptedError("synthetic interruption")
        reader, before = _open_source_regular(src)
        temporary = dst.with_name(f".{dst.name}.carfast-partial-{uuid.uuid4().hex}")
        digest = hashlib.sha256()
        size = 0
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            descriptor = os.open(temporary, flags, 0o600)
            with reader, os.fdopen(descriptor, "wb") as writer:
                while chunk := reader.read(CHUNK_SIZE):
                    writer.write(chunk)
                    size += len(chunk)
                    digest.update(chunk)
                writer.flush()
                os.fsync(writer.fileno())
            after = src.stat(follow_symlinks=False)
            identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            if identity_before != identity_after:
                raise IntegralReconciliationError(f"source changed during copy: {item.path}")
            if (size, digest.hexdigest()) != (item.size, item.sha256):
                raise IntegralReconciliationError(
                    f"source differs from closed manifest: {item.path}"
                )
            os.replace(temporary, dst)
            _fsync_directory(dst.parent)
        finally:
            temporary.unlink(missing_ok=True)
        copied += 1
        bytes_copied += size
    for value in remove:
        relative = _safe_relative(value)
        raw_candidate = target.joinpath(*relative.parts)
        if not raw_candidate.parent.exists():
            continue
        candidate = _assert_confined_parent(target, relative, create=False)
        if candidate.is_symlink() or (candidate.exists() and not candidate.is_file()):
            raise IntegralReconciliationError(f"refusing to remove non-regular object: {value}")
        candidate.unlink(missing_ok=True)
        _fsync_directory(candidate.parent)
    return CopyResult(copied, skipped, bytes_copied)


def assert_storage_exact(root: Path, expected: tuple[StorageEvidence, ...]) -> None:
    actual = build_stable_storage_manifest(root, synthetic_only=True)
    if actual != expected:
        raise IntegralReconciliationError(
            "storage reconciliation mismatch: "
            f"expected={storage_manifest_digest(expected)} actual={storage_manifest_digest(actual)}"
        )


class _SecureLinuxRoot:
    """Descriptor-confined Linux tree; no operation re-resolves an accepted parent."""

    def __init__(self, root: Path) -> None:
        if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
            raise IntegralReconciliationError("secure storage operations require Linux/POSIX")
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        self.fd = os.open(root, flags)
        try:
            metadata = os.fstat(self.fd)
        except Exception:
            os.close(self.fd)
            raise
        if not stat.S_ISDIR(metadata.st_mode):
            os.close(self.fd)
            raise IntegralReconciliationError("secure storage root must be a directory")
        self.device = metadata.st_dev

    def close(self) -> None:
        os.close(self.fd)

    def _open_directory(self, parent_fd: int, name: str, *, create: bool) -> int:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        except FileNotFoundError:
            if not create:
                raise
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
            descriptor = os.open(name, flags, dir_fd=parent_fd)
        try:
            metadata = os.fstat(descriptor)
        except Exception:
            os.close(descriptor)
            raise
        if metadata.st_dev != self.device or not stat.S_ISDIR(metadata.st_mode):
            os.close(descriptor)
            raise IntegralReconciliationError("storage directory crosses mount or changed type")
        return descriptor

    def open_parent(self, relative: PurePosixPath, *, create: bool) -> tuple[int, str]:
        current = os.dup(self.fd)
        try:
            for component in relative.parts[:-1]:
                following = self._open_directory(current, component, create=create)
                os.close(current)
                current = following
            return current, relative.parts[-1]
        except Exception:
            os.close(current)
            raise

    def open_regular(self, parent_fd: int, name: str) -> tuple[int, os.stat_result]:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(name, flags, dir_fd=parent_fd)
        try:
            metadata = os.fstat(descriptor)
        except Exception:
            os.close(descriptor)
            raise
        if (
            metadata.st_dev != self.device
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
        ):
            os.close(descriptor)
            raise IntegralReconciliationError("storage object is not a unique regular file")
        return descriptor, metadata


def _digest_descriptor(descriptor: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, CHUNK_SIZE)
        if not chunk:
            break
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int]:
    return metadata.st_dev, metadata.st_ino, metadata.st_size, metadata.st_mtime_ns


def build_secure_storage_manifest(
    root: Path, *, synthetic_only: bool = False
) -> tuple[StorageEvidence, ...]:
    """Scan entirely through held dirfds, rejecting all namespace ambiguity."""
    if not synthetic_only:
        raise IntegralReconciliationError(
            "secure scanner remains synthetic-only pending audit PASS"
        )
    tree = _SecureLinuxRoot(root)
    evidence: list[StorageEvidence] = []
    folded: dict[str, str] = {}

    def visit(directory_fd: int, prefix: tuple[str, ...]) -> None:
        for name in sorted(os.listdir(directory_fd)):
            if not name or "/" in name or name in {".", ".."}:
                raise IntegralReconciliationError("invalid storage directory entry")
            relative = PurePosixPath(*prefix, name).as_posix()
            if unicodedata.normalize("NFC", relative) != relative:
                raise IntegralReconciliationError(f"storage path is not NFC: {relative!r}")
            key = relative.casefold()
            if key in folded and folded[key] != relative:
                raise IntegralReconciliationError("case-colliding storage paths are forbidden")
            folded[key] = relative
            metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if metadata.st_dev != tree.device:
                raise IntegralReconciliationError("storage mount boundary is forbidden")
            if stat.S_ISDIR(metadata.st_mode):
                child = tree._open_directory(directory_fd, name, create=False)
                try:
                    if _identity(os.fstat(child))[:2] != _identity(metadata)[:2]:
                        raise IntegralReconciliationError("directory changed during secure scan")
                    visit(child, (*prefix, name))
                finally:
                    os.close(child)
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise IntegralReconciliationError("symlink, hardlink, or special storage object")
            descriptor, opened = tree.open_regular(directory_fd, name)
            try:
                if _identity(opened) != _identity(metadata):
                    raise IntegralReconciliationError("storage object changed before open")
                size, digest = _digest_descriptor(descriptor)
                after = os.fstat(descriptor)
                if _identity(after) != _identity(opened) or size != after.st_size:
                    raise IntegralReconciliationError("storage object changed while hashing")
            finally:
                os.close(descriptor)
            evidence.append(StorageEvidence(relative, size, digest))

    try:
        visit(tree.fd, ())
    finally:
        tree.close()
    result = tuple(sorted(evidence, key=lambda item: item.path))
    validate_storage_manifest(result)
    return result


def _validate_remove(remove: tuple[str, ...]) -> None:
    if tuple(sorted(set(remove))) != remove:
        raise IntegralReconciliationError("storage remove paths must be unique and sorted")
    dummy = "0" * 64
    validate_storage_manifest(tuple(StorageEvidence(path, 0, dummy) for path in remove))


def secure_sync_manifest(
    source: Path,
    target: Path,
    desired: tuple[StorageEvidence, ...],
    *,
    remove: tuple[str, ...] = (),
    interrupt_after: int | None = None,
    synthetic_only: bool = False,
) -> CopyResult:
    """Materialize a manifest using only held dirfds and *at operations."""
    if not synthetic_only:
        raise IntegralReconciliationError("secure sync remains synthetic-only pending audit PASS")
    validate_storage_manifest(desired)
    _validate_remove(remove)
    if set(remove) & {item.path for item in desired}:
        raise IntegralReconciliationError("storage copy/remove sets overlap")
    source_tree = _SecureLinuxRoot(source)
    target_tree: _SecureLinuxRoot | None = None
    copied = skipped = bytes_copied = 0
    try:
        target_tree = _SecureLinuxRoot(target)
        for item in desired:
            relative = _safe_relative(item.path)
            source_parent, source_name = source_tree.open_parent(relative, create=False)
            try:
                target_parent, target_name = target_tree.open_parent(relative, create=True)
                try:
                    try:
                        existing_fd, _ = target_tree.open_regular(target_parent, target_name)
                    except FileNotFoundError:
                        existing_fd = None
                    if existing_fd is not None:
                        try:
                            if _digest_descriptor(existing_fd) == (item.size, item.sha256):
                                skipped += 1
                                continue
                        finally:
                            os.close(existing_fd)
                    if interrupt_after is not None and copied >= interrupt_after:
                        raise InterruptedError("synthetic interruption")
                    source_fd, before = source_tree.open_regular(source_parent, source_name)
                    try:
                        temporary = f".{target_name}.carfast-partial-{uuid.uuid4().hex}"
                        temp_fd = os.open(
                            temporary,
                            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                            0o600,
                            dir_fd=target_parent,
                        )
                        digest = hashlib.sha256()
                        size = 0
                        try:
                            while True:
                                chunk = os.read(source_fd, CHUNK_SIZE)
                                if not chunk:
                                    break
                                remaining = memoryview(chunk)
                                while remaining:
                                    written = os.write(temp_fd, remaining)
                                    if written <= 0:
                                        raise IntegralReconciliationError(
                                            "short write to storage staging"
                                        )
                                    remaining = remaining[written:]
                                size += len(chunk)
                                digest.update(chunk)
                            os.fsync(temp_fd)
                            if _identity(os.fstat(source_fd)) != _identity(before):
                                raise IntegralReconciliationError(
                                    "source changed during secure copy"
                                )
                            if (size, digest.hexdigest()) != (item.size, item.sha256):
                                raise IntegralReconciliationError(
                                    "source differs from closed manifest"
                                )
                            os.replace(
                                temporary,
                                target_name,
                                src_dir_fd=target_parent,
                                dst_dir_fd=target_parent,
                            )
                            os.fsync(target_parent)
                        finally:
                            os.close(temp_fd)
                            try:
                                os.unlink(temporary, dir_fd=target_parent)
                            except FileNotFoundError:
                                pass
                    finally:
                        os.close(source_fd)
                    copied += 1
                    bytes_copied += size
                finally:
                    os.close(target_parent)
            finally:
                os.close(source_parent)
        for value in remove:
            relative = _safe_relative(value)
            try:
                parent_fd, name = target_tree.open_parent(relative, create=False)
            except FileNotFoundError:
                continue
            try:
                try:
                    metadata = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise IntegralReconciliationError("refusing to remove non-regular object")
                os.unlink(name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    finally:
        source_tree.close()
        if target_tree is not None:
            target_tree.close()
    return CopyResult(copied, skipped, bytes_copied)


def assert_secure_storage_exact(
    root: Path, expected: tuple[StorageEvidence, ...], *, synthetic_only: bool = False
) -> None:
    actual = build_secure_storage_manifest(root, synthetic_only=synthetic_only)
    if actual != expected:
        raise IntegralReconciliationError(
            "secure storage reconciliation mismatch: "
            f"expected={storage_manifest_digest(expected)} actual={storage_manifest_digest(actual)}"
        )
