from __future__ import annotations

from pathlib import Path

import pytest

from app.platform.integral_reconciliation import IntegralReconciliationError, StorageEvidence
from app.platform.storage_preseed_delta import (
    assert_storage_exact,
    build_stable_storage_manifest,
    calculate_delta,
    sync_manifest,
    validate_storage_manifest,
)


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
    item = StorageEvidence("../escape", 0, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
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
