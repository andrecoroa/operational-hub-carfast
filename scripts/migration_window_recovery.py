"""Startup recovery for an interrupted integral-migration capture window.

The hook is deliberately dormant unless a strictly validated marker exists on
the persistent disk.  It contains no credentials and never discovers paths
from untrusted input: the marker only binds a bundle identifier and the modes
needed to restore the two fixed CarFast storage roots.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg import sql

BLUE_RELEASE = "58a150c701221b64c43bd14fcb671683f3722ebe"
MARKER_NAME = ".carfast_migration_window.json"
MARKER_SCHEMA = "carfast.migration-window-recovery.v1"
_BUNDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{11,63}$")
_ALLOWED_MODES = {0o700, 0o750, 0o755, 0o770, 0o775}
_ALLOWED_PARENT_MODES = {0o700, 0o750, 0o755, 0o770, 0o775}
_MAX_MARKER_BYTES = 4096


class RecoveryError(RuntimeError):
    """Fail-closed recovery error safe to expose without operational data."""


def _owner_matches(info: os.stat_result) -> bool:
    """Enforce Unix ownership in Render; Windows has no effective-uid API."""

    get_euid = getattr(os, "geteuid", None)
    return get_euid is None or info.st_uid == get_euid()


@dataclass(frozen=True)
class RecoveryMarker:
    bundle_id: str
    parent_mode: int
    documents_mode: int
    email_mode: int
    documents_source_dev: int
    documents_source_inode: int
    documents_placeholder_dev: int
    documents_placeholder_inode: int
    email_source_dev: int
    email_source_inode: int
    email_placeholder_dev: int
    email_placeholder_inode: int


def _read_marker(marker_path: Path) -> tuple[RecoveryMarker, tuple[int, int]] | None:
    try:
        fd = os.open(marker_path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise RecoveryError("migration recovery marker cannot be opened safely") from exc

    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise RecoveryError("migration recovery marker is not a regular file")
        if not _owner_matches(info):
            raise RecoveryError("migration recovery marker owner mismatch")
        if os.name == "posix" and stat.S_IMODE(info.st_mode) != 0o600:
            raise RecoveryError("migration recovery marker mode mismatch")
        if info.st_size < 2 or info.st_size > _MAX_MARKER_BYTES:
            raise RecoveryError("migration recovery marker size is invalid")
        raw = os.read(fd, _MAX_MARKER_BYTES + 1)
        if os.read(fd, 1):
            raise RecoveryError("migration recovery marker changed while reading")
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_size) != (
            info.st_dev,
            info.st_ino,
            info.st_size,
        ):
            raise RecoveryError("migration recovery marker changed while reading")
    finally:
        os.close(fd)

    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RecoveryError("migration recovery marker is invalid JSON") from exc
    expected = {
        "schema",
        "blue_release",
        "bundle_id",
        "parent_mode",
        "documents_mode",
        "email_mode",
        "documents_source_dev",
        "documents_source_inode",
        "documents_placeholder_dev",
        "documents_placeholder_inode",
        "email_source_dev",
        "email_source_inode",
        "email_placeholder_dev",
        "email_placeholder_inode",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise RecoveryError("migration recovery marker shape mismatch")
    if value["schema"] != MARKER_SCHEMA or value["blue_release"] != BLUE_RELEASE:
        raise RecoveryError("migration recovery marker release mismatch")
    bundle_id = value["bundle_id"]
    if not isinstance(bundle_id, str) or not _BUNDLE_RE.fullmatch(bundle_id):
        raise RecoveryError("migration recovery marker bundle mismatch")
    modes = (value["parent_mode"], value["documents_mode"], value["email_mode"])
    if any(type(mode) is not int for mode in modes):
        raise RecoveryError("migration recovery marker mode type mismatch")
    roots_have_invalid_mode = any(mode not in _ALLOWED_MODES for mode in modes[1:])
    if modes[0] not in _ALLOWED_PARENT_MODES or roots_have_invalid_mode:
        raise RecoveryError("migration recovery marker mode value mismatch")
    identity_values = (
        value["documents_source_dev"],
        value["documents_source_inode"],
        value["documents_placeholder_dev"],
        value["documents_placeholder_inode"],
        value["email_source_dev"],
        value["email_source_inode"],
        value["email_placeholder_dev"],
        value["email_placeholder_inode"],
    )
    if any(type(item) is not int or item < 1 for item in identity_values):
        raise RecoveryError("migration recovery marker inode binding mismatch")
    return RecoveryMarker(bundle_id, *modes, *identity_values), (info.st_dev, info.st_ino)


def _directory_state_at(data_fd: int, name: str) -> os.stat_result | None:
    try:
        result = os.stat(name, dir_fd=data_fd, follow_symlinks=False)
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(result.st_mode):
        raise RecoveryError("migration recovery storage type mismatch")
    if not _owner_matches(result):
        raise RecoveryError("migration recovery storage owner mismatch")
    return result


def _is_empty_at(data_fd: int, name: str) -> bool:
    child_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=data_fd)
    try:
        return not os.listdir(child_fd)
    finally:
        os.close(child_fd)


def _same_inode(info: os.stat_result, expected: tuple[int, int]) -> bool:
    return (info.st_dev, info.st_ino) == expected


def _restore_root_at(
    data_fd: int,
    original: str,
    frozen: str,
    mode: int,
    *,
    source_identity: tuple[int, int],
    placeholder_identity: tuple[int, int],
) -> None:
    original_state = _directory_state_at(data_fd, original)
    frozen_state = _directory_state_at(data_fd, frozen)
    if frozen_state is None:
        if original_state is None or not _same_inode(original_state, source_identity):
            raise RecoveryError("migration recovery storage root is missing")
        os.chmod(original, mode, dir_fd=data_fd, follow_symlinks=False)
        return
    if not _same_inode(frozen_state, source_identity):
        raise RecoveryError("migration recovery frozen inode mismatch")
    if original_state is not None:
        placeholder_mode = stat.S_IMODE(original_state.st_mode)
        invalid_mode = os.name == "posix" and placeholder_mode not in {0o500, 0o550, 0o555}
        if (
            invalid_mode
            or not _same_inode(original_state, placeholder_identity)
            or not _is_empty_at(data_fd, original)
        ):
            raise RecoveryError("migration recovery storage state is ambiguous")
        os.rmdir(original, dir_fd=data_fd)
    os.rename(frozen, original, src_dir_fd=data_fd, dst_dir_fd=data_fd)
    restored = _directory_state_at(data_fd, original)
    if restored is None or not _same_inode(restored, source_identity):
        raise RecoveryError("migration recovery storage rename mismatch")
    os.chmod(original, mode, dir_fd=data_fd, follow_symlinks=False)


def _restore_database(database_url: str) -> None:
    if not database_url:
        raise RecoveryError("migration recovery database URL is missing")
    try:
        with psycopg.connect(
            database_url,
            autocommit=True,
            options="-c default_transaction_read_only=off",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT current_user, current_database()")
                role_name, database_name = cursor.fetchone()
                cursor.execute(
                    sql.SQL("ALTER ROLE {} RESET default_transaction_read_only").format(
                        sql.Identifier(role_name)
                    )
                )
                cursor.execute(
                    sql.SQL("ALTER DATABASE {} RESET default_transaction_read_only").format(
                        sql.Identifier(database_name)
                    )
                )
                cursor.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND usename=current_user "
                    "AND pid<>pg_backend_pid()"
                )
                if any(result is not True for (result,) in cursor.fetchall()):
                    raise RecoveryError("migration recovery could not terminate every session")
                cursor.execute(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname=current_database() AND usename=current_user "
                    "AND pid<>pg_backend_pid()"
                )
                if cursor.fetchone()[0] != 0:
                    raise RecoveryError("migration recovery concurrent sessions remain")
                cursor.execute(
                    "SELECT count(*) FROM pg_db_role_setting s "
                    "JOIN pg_database d ON d.datname=current_database() "
                    "WHERE (s.setrole=(SELECT oid FROM pg_roles WHERE rolname=current_user) "
                    "AND s.setdatabase=0 OR s.setrole=0 AND s.setdatabase=d.oid) "
                    "AND EXISTS (SELECT 1 FROM unnest(s.setconfig) c "
                    "WHERE c LIKE 'default_transaction_read_only=%')"
                )
                if cursor.fetchone()[0] != 0:
                    raise RecoveryError("migration recovery read-only defaults remain")
        with psycopg.connect(database_url, autocommit=True) as verification:
            with verification.cursor() as cursor:
                cursor.execute("SHOW default_transaction_read_only")
                if cursor.fetchone()[0] != "off":
                    raise RecoveryError("migration recovery database remains read-only")
    except RecoveryError:
        raise
    except Exception as exc:
        raise RecoveryError("migration recovery database reset failed") from exc


def recover_migration_window(
    database_url: str,
    *,
    data_root: Path = Path("/var/data"),
) -> bool:
    """Restore an interrupted window; return False without any side effect if absent."""

    marker_path = data_root / MARKER_NAME
    marker_result = _read_marker(marker_path)
    if marker_result is None:
        return False
    marker, marker_identity = marker_result

    root_state = data_root.lstat()
    if not stat.S_ISDIR(root_state.st_mode) or data_root.is_symlink():
        raise RecoveryError("migration recovery data root is missing")
    os.chmod(data_root, marker.parent_mode, follow_symlinks=False)
    data_fd = os.open(data_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _restore_root_at(
            data_fd,
            "carfast_documents",
            f".cutoff-{marker.bundle_id}-carfast_documents",
            marker.documents_mode,
            source_identity=(marker.documents_source_dev, marker.documents_source_inode),
            placeholder_identity=(
                marker.documents_placeholder_dev,
                marker.documents_placeholder_inode,
            ),
        )
        _restore_root_at(
            data_fd,
            "email",
            f".cutoff-{marker.bundle_id}-email",
            marker.email_mode,
            source_identity=(marker.email_source_dev, marker.email_source_inode),
            placeholder_identity=(marker.email_placeholder_dev, marker.email_placeholder_inode),
        )
        _restore_database(database_url)
        current_marker = os.stat(MARKER_NAME, dir_fd=data_fd, follow_symlinks=False)
        if (current_marker.st_dev, current_marker.st_ino) != marker_identity:
            raise RecoveryError("migration recovery marker replacement detected")
        os.unlink(MARKER_NAME, dir_fd=data_fd)
    finally:
        os.close(data_fd)
    return True
