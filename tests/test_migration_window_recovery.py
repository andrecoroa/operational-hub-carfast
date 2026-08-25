from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import migration_window_recovery as recovery

BUNDLE = "window-20260825-abcd"


def write_marker(root: Path, **overrides: object) -> Path:
    def identity(name: str) -> tuple[int, int]:
        try:
            info = (root / name).stat()
        except FileNotFoundError:
            return (1, 1)
        return (info.st_dev, info.st_ino)

    documents_source = identity(f".cutoff-{BUNDLE}-carfast_documents")
    documents_placeholder = identity("carfast_documents")
    email_source = identity(f".cutoff-{BUNDLE}-email")
    email_placeholder = identity("email")
    value = {
        "schema": recovery.MARKER_SCHEMA,
        "blue_release": recovery.BLUE_RELEASE,
        "bundle_id": BUNDLE,
        "parent_mode": 0o755,
        "documents_mode": 0o755,
        "email_mode": 0o750,
        "documents_source_dev": documents_source[0],
        "documents_source_inode": documents_source[1],
        "documents_placeholder_dev": documents_placeholder[0],
        "documents_placeholder_inode": documents_placeholder[1],
        "email_source_dev": email_source[0],
        "email_source_inode": email_source[1],
        "email_placeholder_dev": email_placeholder[0],
        "email_placeholder_inode": email_placeholder[1],
    }
    value.update(overrides)
    marker = root / recovery.MARKER_NAME
    marker.write_text(json.dumps(value), encoding="utf-8")
    marker.chmod(0o600)
    return marker


def interrupted_tree(tmp_path: Path, *, partial: bool = False) -> None:
    (tmp_path / f".cutoff-{BUNDLE}-carfast_documents").mkdir()
    (tmp_path / f".cutoff-{BUNDLE}-carfast_documents" / "document.bin").write_bytes(b"doc")
    (tmp_path / "carfast_documents").mkdir(mode=0o555)
    if partial:
        (tmp_path / "email").mkdir(mode=0o750)
        (tmp_path / "email" / "message.bin").write_bytes(b"mail")
    else:
        (tmp_path / f".cutoff-{BUNDLE}-email").mkdir()
        (tmp_path / f".cutoff-{BUNDLE}-email" / "message.bin").write_bytes(b"mail")
        (tmp_path / "email").mkdir(mode=0o555)


def writable_tree(tmp_path: Path) -> None:
    (tmp_path / "carfast_documents").mkdir(mode=0o755)
    (tmp_path / "carfast_documents" / "document.bin").write_bytes(b"doc")
    (tmp_path / "email").mkdir(mode=0o750)
    (tmp_path / "email" / "message.bin").write_bytes(b"mail")


def test_no_marker_is_absolute_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = Mock(side_effect=AssertionError("database must not be touched"))
    monkeypatch.setattr(recovery, "_restore_database", database)
    before = tmp_path.stat()
    assert recovery.recover_migration_window("not-used", data_root=tmp_path) is False
    after = tmp_path.stat()
    assert database.call_count == 0
    assert stat.S_IMODE(after.st_mode) == stat.S_IMODE(before.st_mode)


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.skipif(os.name != "posix", reason="dirfd recovery is Linux-specific")
def test_recovery_handles_crash_and_partial_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    interrupted_tree(tmp_path)
    marker = write_marker(tmp_path)
    if partial:
        (tmp_path / "email").rmdir()
        (tmp_path / f".cutoff-{BUNDLE}-email").rename(tmp_path / "email")
    database = Mock()
    monkeypatch.setattr(recovery, "_restore_database", database)

    assert recovery.recover_migration_window("postgresql://private", data_root=tmp_path)
    assert not marker.exists()
    assert (tmp_path / "carfast_documents" / "document.bin").read_bytes() == b"doc"
    assert (tmp_path / "email" / "message.bin").read_bytes() == b"mail"
    assert not (tmp_path / f".cutoff-{BUNDLE}-carfast_documents").exists()
    assert not (tmp_path / f".cutoff-{BUNDLE}-email").exists()
    if os.name == "posix":
        assert stat.S_IMODE((tmp_path / "carfast_documents").stat().st_mode) == 0o755
        assert stat.S_IMODE((tmp_path / "email").stat().st_mode) == 0o750
    database.assert_called_once_with("postgresql://private")
    assert recovery.recover_migration_window("not-used", data_root=tmp_path) is False


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema": "unknown"},
        {"blue_release": "0" * 40},
        {"bundle_id": "../escape"},
        {"parent_mode": 0o777},
        {"unknown": True},
    ],
)
def test_invalid_marker_fails_closed(tmp_path: Path, mutation: dict[str, object]) -> None:
    write_marker(tmp_path, **mutation)
    with pytest.raises(recovery.RecoveryError):
        recovery.recover_migration_window("not-used", data_root=tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="dirfd recovery is Linux-specific")
def test_symlink_marker_and_ambiguous_roots_fail_closed(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("{}", encoding="utf-8")
    try:
        (tmp_path / recovery.MARKER_NAME).symlink_to(target)
    except OSError:
        pass
    else:
        with pytest.raises(recovery.RecoveryError):
            recovery.recover_migration_window("not-used", data_root=tmp_path)
        (tmp_path / recovery.MARKER_NAME).unlink()
    interrupted_tree(tmp_path)
    (tmp_path / "carfast_documents" / "unexpected").write_text("x", encoding="utf-8")
    write_marker(tmp_path)
    with pytest.raises(recovery.RecoveryError):
        recovery.recover_migration_window("not-used", data_root=tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="dirfd recovery is Linux-specific")
def test_marker_is_retained_when_database_reset_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interrupted_tree(tmp_path)
    marker = write_marker(tmp_path)
    monkeypatch.setattr(
        recovery,
        "_restore_database",
        Mock(side_effect=recovery.RecoveryError("database reset failed")),
    )
    with pytest.raises(recovery.RecoveryError):
        recovery.recover_migration_window("postgresql://private", data_root=tmp_path)
    assert marker.exists()
    assert (tmp_path / "carfast_documents" / "document.bin").exists()
    assert (tmp_path / "email" / "message.bin").exists()


@pytest.mark.parametrize("boundary", range(4))
@pytest.mark.skipif(os.name != "posix", reason="dirfd recovery is Linux-specific")
def test_durable_arm_recovers_every_pre_barrier_crash_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: int
) -> None:
    writable_tree(tmp_path)
    recovery.arm_migration_window(BUNDLE, data_root=tmp_path)
    if boundary >= 1:
        (tmp_path / "carfast_documents").rename(
            tmp_path / f".cutoff-{BUNDLE}-carfast_documents"
        )
    if boundary >= 2:
        (tmp_path / f".placeholder-{BUNDLE}-carfast_documents").rename(
            tmp_path / "carfast_documents"
        )
    if boundary >= 3:
        (tmp_path / "email").rename(tmp_path / f".cutoff-{BUNDLE}-email")
    monkeypatch.setattr(recovery, "_restore_database", Mock())
    assert recovery.recover_migration_window("postgresql://private", data_root=tmp_path)
    assert (tmp_path / "carfast_documents" / "document.bin").read_bytes() == b"doc"
    assert (tmp_path / "email" / "message.bin").read_bytes() == b"mail"
    assert not list(tmp_path.glob(".placeholder-*"))
    assert not list(tmp_path.glob(".cutoff-*"))


@pytest.mark.skipif(os.name != "posix", reason="dirfd recovery is Linux-specific")
def test_armed_storage_barrier_and_recovery_are_one_closed_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writable_tree(tmp_path)
    recovery.arm_migration_window(BUNDLE, data_root=tmp_path)
    recovery.activate_storage_barrier(BUNDLE, data_root=tmp_path)
    assert not list((tmp_path / "carfast_documents").iterdir())
    assert not list((tmp_path / "email").iterdir())
    monkeypatch.setattr(recovery, "_restore_database", Mock())
    assert recovery.recover_migration_window("postgresql://private", data_root=tmp_path)


@pytest.mark.skipif(os.name != "posix", reason="dirfd recovery is Linux-specific")
def test_frozen_inode_replacement_and_marker_replacement_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    interrupted_tree(tmp_path)
    marker = write_marker(tmp_path)
    frozen = tmp_path / f".cutoff-{BUNDLE}-carfast_documents"
    frozen.rename(tmp_path / "displaced")
    frozen.mkdir()
    with pytest.raises(recovery.RecoveryError, match="frozen inode"):
        recovery.recover_migration_window("not-used", data_root=tmp_path)

    marker.unlink()
    frozen.rmdir()
    (tmp_path / "displaced").rename(frozen)
    marker = write_marker(tmp_path)

    def replace_marker(_database_url: str) -> None:
        marker.unlink()
        replacement = write_marker(tmp_path)
        replacement.chmod(0o600)

    monkeypatch.setattr(recovery, "_restore_database", replace_marker)
    with pytest.raises(recovery.RecoveryError, match="marker replacement"):
        recovery.recover_migration_window("not-used", data_root=tmp_path)
    assert marker.exists()


@pytest.mark.skipif(
    not os.environ.get("RECOVERY_TEST_DATABASE_URL"),
    reason="requires PostgreSQL 17 integration service",
)
def test_postgresql17_role_and_database_defaults_are_restored(tmp_path: Path) -> None:
    database_url = os.environ["RECOVERY_TEST_DATABASE_URL"]
    interrupted_tree(tmp_path)
    write_marker(tmp_path)
    with recovery.psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("ALTER ROLE CURRENT_USER SET default_transaction_read_only=on")
            cursor.execute("ALTER DATABASE postgres SET default_transaction_read_only=on")

    blocker = recovery.psycopg.connect(database_url, autocommit=True)
    assert recovery.recover_migration_window(database_url, data_root=tmp_path)
    with pytest.raises(recovery.psycopg.Error):
        blocker.execute("SELECT 1")
    blocker.close()
    with recovery.psycopg.connect(database_url, autocommit=True) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version_num")
            assert int(cursor.fetchone()[0]) // 10000 == 17
            cursor.execute("SHOW default_transaction_read_only")
            assert cursor.fetchone()[0] == "off"
