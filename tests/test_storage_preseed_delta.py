from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.platform.integral_reconciliation import IntegralReconciliationError, StorageEvidence
from app.platform.storage_preseed_delta import (
    assert_secure_storage_exact,
    assert_storage_exact,
    build_secure_storage_manifest,
    build_stable_storage_manifest,
    calculate_delta,
    secure_sync_manifest,
    sync_manifest,
    validate_storage_manifest,
)

POSIX_SECURE = pytest.mark.skipif(os.name != "posix", reason="Linux dirfd contract")


def test_preseed_resume_and_final_delta_are_exact(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    (source / "a.bin").write_bytes(b"a" * 32)
    (source / "b.bin").write_bytes(b"b" * 64)
    preseed = build_stable_storage_manifest(source, synthetic_only=True)

    with pytest.raises(InterruptedError):
        sync_manifest(source, target, preseed, interrupt_after=1, synthetic_only=True)
    resumed = sync_manifest(source, target, preseed, synthetic_only=True)
    assert resumed.copied == 1
    assert resumed.skipped == 1
    assert_storage_exact(target, preseed)

    (source / "a.bin").write_bytes(b"changed")
    (source / "b.bin").rename(source / "renamed.bin")
    (source / "new.bin").write_bytes(b"new")
    final = build_stable_storage_manifest(source, synthetic_only=True)
    delta = calculate_delta(preseed, final)
    assert delta.remove == ("b.bin",)
    assert {item.path for item in delta.copy} == {"a.bin", "new.bin", "renamed.bin"}
    sync_manifest(source, target, delta.copy, remove=delta.remove, synthetic_only=True)
    assert_storage_exact(target, final)


def test_rename_is_delete_plus_copy_and_can_reuse_verified_content(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "old").write_bytes(b"same")
    before = build_stable_storage_manifest(source, synthetic_only=True)
    (source / "old").rename(source / "new")
    after = build_stable_storage_manifest(source, synthetic_only=True)
    delta = calculate_delta(before, after)
    assert delta.remove == ("old",)
    assert [item.path for item in delta.copy] == ["new"]
    assert delta.copy[0].sha256 == before[0].sha256


def test_unsafe_paths_and_symlinks_fail_closed(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    regular = source / "regular"
    regular.write_bytes(b"x")
    link = source / "link"
    try:
        link.symlink_to(regular)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(IntegralReconciliationError, match="symlink"):
        build_stable_storage_manifest(source, synthetic_only=True)


def test_tampered_source_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path = source / "object"
    path.write_bytes(b"before")
    manifest = build_stable_storage_manifest(source, synthetic_only=True)
    path.write_bytes(b"after")
    with pytest.raises(IntegralReconciliationError, match="closed manifest"):
        sync_manifest(source, tmp_path / "target", manifest, synthetic_only=True)


def test_manifest_path_traversal_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    item = StorageEvidence(
        "../escape", 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    with pytest.raises(IntegralReconciliationError, match="unsafe storage path"):
        sync_manifest(source, tmp_path / "target", (item,), synthetic_only=True)


def test_duplicate_and_invalid_manifest_entries_fail_closed() -> None:
    valid = StorageEvidence("a", 1, "a" * 64)
    with pytest.raises(IntegralReconciliationError, match="unique and sorted"):
        validate_storage_manifest((valid, valid))
    with pytest.raises(IntegralReconciliationError, match="invalid storage evidence"):
        validate_storage_manifest((StorageEvidence("a", -1, "bad"),))


def test_nested_manifest_is_globally_sorted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    (source / "a").mkdir(parents=True)
    (source / "a" / "object").write_bytes(b"nested")
    (source / "a-file").write_bytes(b"flat")
    manifest = build_stable_storage_manifest(source, synthetic_only=True)
    assert [item.path for item in manifest] == ["a-file", "a/object"]


def test_target_parent_symlink_cannot_escape(tmp_path: Path) -> None:
    source, target, outside = tmp_path / "source", tmp_path / "target", tmp_path / "outside"
    source.mkdir()
    target.mkdir()
    outside.mkdir()
    (source / "nested").mkdir()
    (source / "nested" / "object").write_bytes(b"safe")
    manifest = build_stable_storage_manifest(source, synthetic_only=True)
    try:
        (target / "nested").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    with pytest.raises(IntegralReconciliationError, match="unsafe storage parent"):
        sync_manifest(source, target, manifest, synthetic_only=True)
    assert not (outside / "object").exists()


@POSIX_SECURE
def test_secure_dirfd_preseed_resume_delta_and_exactness(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "a").write_bytes(b"a" * 1024)
    (source / "b").write_bytes(b"b" * 2048)
    target.mkdir(mode=0o700)
    preseed = build_secure_storage_manifest(source, synthetic_only=True)
    with pytest.raises(InterruptedError):
        secure_sync_manifest(source, target, preseed, interrupt_after=1, synthetic_only=True)
    secure_sync_manifest(source, target, preseed, synthetic_only=True)
    assert_secure_storage_exact(target, preseed, synthetic_only=True)
    (source / "b").unlink()
    (source / "nested" / "a").write_bytes(b"changed")
    (source / "new").write_bytes(b"new")
    final = build_secure_storage_manifest(source, synthetic_only=True)
    delta = calculate_delta(preseed, final)
    secure_sync_manifest(source, target, delta.copy, remove=delta.remove, synthetic_only=True)
    assert_secure_storage_exact(target, final, synthetic_only=True)


@POSIX_SECURE
def test_secure_scan_rejects_symlink_hardlink_and_fifo(tmp_path: Path) -> None:
    for kind in ("symlink", "hardlink", "fifo"):
        root = tmp_path / kind
        root.mkdir()
        regular = root / "regular"
        regular.write_bytes(b"fixture")
        if kind == "symlink":
            (root / "bad").symlink_to(regular)
        elif kind == "hardlink":
            os.link(regular, root / "bad")
        else:
            os.mkfifo(root / "bad")
        with pytest.raises(IntegralReconciliationError):
            build_secure_storage_manifest(root, synthetic_only=True)


@POSIX_SECURE
def test_secure_target_parent_symlink_is_never_followed(tmp_path: Path) -> None:
    source, target, outside = tmp_path / "source", tmp_path / "target", tmp_path / "outside"
    (source / "nested").mkdir(parents=True)
    (source / "nested" / "object").write_bytes(b"safe")
    target.mkdir()
    outside.mkdir()
    (target / "nested").symlink_to(outside, target_is_directory=True)
    manifest = build_secure_storage_manifest(source, synthetic_only=True)
    with pytest.raises(OSError):
        secure_sync_manifest(source, target, manifest, synthetic_only=True)
    assert not (outside / "object").exists()


def test_secure_operations_remain_locked_without_audit_flag(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(IntegralReconciliationError, match="synthetic-only"):
        build_secure_storage_manifest(root)
    with pytest.raises(IntegralReconciliationError, match="synthetic-only"):
        secure_sync_manifest(root, tmp_path / "target", ())


@POSIX_SECURE
def test_secure_failure_paths_do_not_leak_descriptors(tmp_path: Path, monkeypatch) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "object").write_bytes(b"fixture")
    manifest = build_secure_storage_manifest(source, synthetic_only=True)

    def descriptor_count() -> int:
        return len(tuple(Path("/proc/self/fd").iterdir()))

    before = descriptor_count()
    with pytest.raises(FileNotFoundError):
        secure_sync_manifest(source, tmp_path / "missing", manifest, synthetic_only=True)
    assert descriptor_count() == before

    target = tmp_path / "target"
    target.mkdir(mode=0o700)

    class FixedUuid:
        hex = "collision"

    monkeypatch.setattr("app.platform.storage_preseed_delta.uuid.uuid4", lambda: FixedUuid())
    (target / ".object.carfast-partial-collision").write_bytes(b"occupied")
    with pytest.raises(FileExistsError):
        secure_sync_manifest(source, target, manifest, synthetic_only=True)
    assert descriptor_count() == before


@POSIX_SECURE
def test_secure_copy_handles_partial_kernel_writes(tmp_path: Path, monkeypatch) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir(mode=0o700)
    (source / "object").write_bytes(b"x" * (2 * 1024 * 1024 + 7))
    manifest = build_secure_storage_manifest(source, synthetic_only=True)
    original_write = os.write

    def partial_write(descriptor: int, data) -> int:
        return original_write(descriptor, data[: max(1, len(data) // 3)])

    monkeypatch.setattr("app.platform.storage_preseed_delta.os.write", partial_write)
    secure_sync_manifest(source, target, manifest, synthetic_only=True)
    assert_secure_storage_exact(target, manifest, synthetic_only=True)
