"""Startup recovery for an interrupted integral-migration capture window.

The hook is deliberately dormant unless a strictly validated marker exists on
the persistent disk.  It contains no credentials and never discovers paths
from untrusted input: the marker only binds a bundle identifier and the modes
needed to restore the two fixed CarFast storage roots.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

import psycopg
from psycopg import sql

BLUE_RELEASE = "58a150c701221b64c43bd14fcb671683f3722ebe"
MARKER_NAME = ".carfast_migration_window.json"
MARKER_SCHEMA = "carfast.migration-window-recovery.v1"
_BUNDLE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{11,63}$")
_ALLOWED_MODES = {0o700, 0o750, 0o755, 0o770, 0o775}
_ALLOWED_PARENT_MODES = {0o700, 0o750, 0o755, 0o770, 0o775}
_ALLOWED_SPECIAL_DIR_BITS = {0, stat.S_ISGID}
_MAX_MARKER_BYTES = 4096


class RecoveryError(RuntimeError):
    """Fail-closed recovery error safe to expose without operational data."""


def _owner_matches(info: os.stat_result) -> bool:
    """Enforce Unix ownership in Render; Windows has no effective-uid API."""

    get_euid = getattr(os, "geteuid", None)
    return get_euid is None or info.st_uid == get_euid()


def _safe_directory_mode(mode: int, allowed: set[int]) -> bool:
    """Accept allowlisted permissions and only the directory setgid special bit."""

    return (mode & 0o777) in allowed and (mode & 0o7000) in _ALLOWED_SPECIAL_DIR_BITS


def _same_owner_group(info: os.stat_result, uid: int, gid: int) -> bool:
    return os.name != "posix" or (info.st_uid, info.st_gid) == (uid, gid)


@dataclass(frozen=True)
class RecoveryMarker:
    bundle_id: str
    parent_mode: int
    documents_mode: int
    email_mode: int
    parent_uid: int
    parent_gid: int
    documents_uid: int
    documents_gid: int
    email_uid: int
    email_gid: int
    documents_placeholder_uid: int
    documents_placeholder_gid: int
    email_placeholder_uid: int
    email_placeholder_gid: int
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
        "parent_uid",
        "parent_gid",
        "documents_uid",
        "documents_gid",
        "email_uid",
        "email_gid",
        "documents_placeholder_uid",
        "documents_placeholder_gid",
        "email_placeholder_uid",
        "email_placeholder_gid",
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
    roots_have_invalid_mode = any(
        not _safe_directory_mode(mode, _ALLOWED_MODES) for mode in modes[1:]
    )
    if not _safe_directory_mode(modes[0], _ALLOWED_PARENT_MODES) or roots_have_invalid_mode:
        raise RecoveryError("migration recovery marker mode value mismatch")
    ownership = (
        value["parent_uid"],
        value["parent_gid"],
        value["documents_uid"],
        value["documents_gid"],
        value["email_uid"],
        value["email_gid"],
        value["documents_placeholder_uid"],
        value["documents_placeholder_gid"],
        value["email_placeholder_uid"],
        value["email_placeholder_gid"],
    )
    if any(type(item) is not int or item < 0 for item in ownership):
        raise RecoveryError("migration recovery marker ownership mismatch")
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
    return RecoveryMarker(bundle_id, *modes, *ownership, *identity_values), (
        info.st_dev,
        info.st_ino,
    )


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


def _placeholder_name(bundle_id: str, root_name: str) -> str:
    return f".placeholder-{bundle_id}-{root_name}"


def _remove_hidden_placeholder_at(
    data_fd: int,
    name: str,
    expected: tuple[int, int],
    owner_group: tuple[int, int],
) -> None:
    state = _directory_state_at(data_fd, name)
    if state is None:
        return
    if (
        not _same_inode(state, expected)
        or not _same_owner_group(state, *owner_group)
        or not _is_empty_at(data_fd, name)
    ):
        raise RecoveryError("migration recovery hidden placeholder mismatch")
    os.rmdir(name, dir_fd=data_fd)


def _restore_root_at(
    data_fd: int,
    bundle_id: str,
    original: str,
    frozen: str,
    mode: int,
    *,
    owner_group: tuple[int, int],
    placeholder_owner_group: tuple[int, int],
    source_identity: tuple[int, int],
    placeholder_identity: tuple[int, int],
) -> None:
    hidden = _placeholder_name(bundle_id, original)
    original_state = _directory_state_at(data_fd, original)
    frozen_state = _directory_state_at(data_fd, frozen)
    if frozen_state is None:
        if original_state is None or not _same_inode(original_state, source_identity):
            raise RecoveryError("migration recovery storage root is missing")
        if not _same_owner_group(original_state, *owner_group):
            raise RecoveryError("migration recovery storage ownership drift")
        if stat.S_IMODE(original_state.st_mode) != mode:
            raise RecoveryError("migration recovery storage mode drift")
        _remove_hidden_placeholder_at(
            data_fd, hidden, placeholder_identity, placeholder_owner_group
        )
        os.chmod(original, mode, dir_fd=data_fd, follow_symlinks=False)
        return
    if not _same_inode(frozen_state, source_identity):
        raise RecoveryError("migration recovery frozen inode mismatch")
    if not _same_owner_group(frozen_state, *owner_group):
        raise RecoveryError("migration recovery frozen ownership drift")
    if stat.S_IMODE(frozen_state.st_mode) != mode:
        raise RecoveryError("migration recovery frozen mode drift")
    if original_state is not None:
        placeholder_mode = stat.S_IMODE(original_state.st_mode)
        invalid_mode = os.name == "posix" and not _safe_directory_mode(
            placeholder_mode, {0o500, 0o550, 0o555}
        )
        if (
            invalid_mode
            or not _same_inode(original_state, placeholder_identity)
            or not _same_owner_group(original_state, *placeholder_owner_group)
            or not _is_empty_at(data_fd, original)
        ):
            raise RecoveryError("migration recovery storage state is ambiguous")
        os.rmdir(original, dir_fd=data_fd)
    else:
        _remove_hidden_placeholder_at(
            data_fd, hidden, placeholder_identity, placeholder_owner_group
        )
    os.rename(frozen, original, src_dir_fd=data_fd, dst_dir_fd=data_fd)
    restored = _directory_state_at(data_fd, original)
    if (
        restored is None
        or not _same_inode(restored, source_identity)
        or not _same_owner_group(restored, *owner_group)
    ):
        raise RecoveryError("migration recovery storage rename mismatch")
    os.chmod(original, mode, dir_fd=data_fd, follow_symlinks=False)


def arm_migration_window(bundle_id: str, *, data_root: Path = Path("/var/data")) -> RecoveryMarker:
    """Durably arm recovery before any database or storage mutation."""

    if not _BUNDLE_RE.fullmatch(bundle_id):
        raise RecoveryError("migration recovery marker bundle mismatch")
    data_fd = os.open(data_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    created: list[str] = []
    temporary = f"{MARKER_NAME}.{bundle_id}.tmp"
    try:
        try:
            os.stat(MARKER_NAME, dir_fd=data_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise RecoveryError("migration recovery marker already exists")
        parent = os.fstat(data_fd)
        if not _owner_matches(parent) or not _safe_directory_mode(
            stat.S_IMODE(parent.st_mode), _ALLOWED_PARENT_MODES
        ):
            raise RecoveryError("migration recovery data root permissions are unsafe")
        roots: dict[str, os.stat_result] = {}
        placeholders: dict[str, os.stat_result] = {}
        for root_name in ("carfast_documents", "email"):
            source = _directory_state_at(data_fd, root_name)
            if source is None:
                raise RecoveryError("migration recovery source root is missing")
            roots[root_name] = source
            if not _safe_directory_mode(stat.S_IMODE(source.st_mode), _ALLOWED_MODES):
                raise RecoveryError("migration recovery source permissions are unsafe")
            placeholder = _placeholder_name(bundle_id, root_name)
            os.mkdir(placeholder, 0o500, dir_fd=data_fd)
            created.append(placeholder)
            state = _directory_state_at(data_fd, placeholder)
            if state is None:
                raise RecoveryError("migration recovery placeholder creation failed")
            placeholders[root_name] = state
        marker = RecoveryMarker(
            bundle_id=bundle_id,
            parent_mode=stat.S_IMODE(parent.st_mode),
            documents_mode=stat.S_IMODE(roots["carfast_documents"].st_mode),
            email_mode=stat.S_IMODE(roots["email"].st_mode),
            parent_uid=parent.st_uid,
            parent_gid=parent.st_gid,
            documents_uid=roots["carfast_documents"].st_uid,
            documents_gid=roots["carfast_documents"].st_gid,
            email_uid=roots["email"].st_uid,
            email_gid=roots["email"].st_gid,
            documents_placeholder_uid=placeholders["carfast_documents"].st_uid,
            documents_placeholder_gid=placeholders["carfast_documents"].st_gid,
            email_placeholder_uid=placeholders["email"].st_uid,
            email_placeholder_gid=placeholders["email"].st_gid,
            documents_source_dev=roots["carfast_documents"].st_dev,
            documents_source_inode=roots["carfast_documents"].st_ino,
            documents_placeholder_dev=placeholders["carfast_documents"].st_dev,
            documents_placeholder_inode=placeholders["carfast_documents"].st_ino,
            email_source_dev=roots["email"].st_dev,
            email_source_inode=roots["email"].st_ino,
            email_placeholder_dev=placeholders["email"].st_dev,
            email_placeholder_inode=placeholders["email"].st_ino,
        )
        payload = {
            "schema": MARKER_SCHEMA,
            "blue_release": BLUE_RELEASE,
            **asdict(marker),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        marker_fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=data_fd,
        )
        try:
            os.write(marker_fd, encoded)
            os.fsync(marker_fd)
        finally:
            os.close(marker_fd)
        os.rename(temporary, MARKER_NAME, src_dir_fd=data_fd, dst_dir_fd=data_fd)
        os.fsync(data_fd)
        return marker
    except Exception:
        try:
            os.unlink(temporary, dir_fd=data_fd)
        except FileNotFoundError:
            pass
        try:
            os.stat(MARKER_NAME, dir_fd=data_fd, follow_symlinks=False)
            marker_exists = True
        except FileNotFoundError:
            marker_exists = False
        if not marker_exists:
            for name in reversed(created):
                try:
                    os.rmdir(name, dir_fd=data_fd)
                except FileNotFoundError:
                    pass
        raise
    finally:
        os.close(data_fd)


def activate_storage_barrier(bundle_id: str, *, data_root: Path = Path("/var/data")) -> None:
    """Atomically swap both roots only after the durable marker exists."""

    marker_result = _read_marker(data_root / MARKER_NAME)
    if marker_result is None or marker_result[0].bundle_id != bundle_id:
        raise RecoveryError("migration recovery marker is not armed")
    marker = marker_result[0]
    data_fd = os.open(data_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        parent = os.fstat(data_fd)
        if (
            not _same_owner_group(parent, marker.parent_uid, marker.parent_gid)
            or stat.S_IMODE(parent.st_mode) != marker.parent_mode
        ):
            raise RecoveryError("migration recovery data root drift")
        states = (
            (
                "carfast_documents",
                (marker.documents_source_dev, marker.documents_source_inode),
                (marker.documents_placeholder_dev, marker.documents_placeholder_inode),
                (marker.documents_uid, marker.documents_gid),
                (marker.documents_placeholder_uid, marker.documents_placeholder_gid),
            ),
            (
                "email",
                (marker.email_source_dev, marker.email_source_inode),
                (marker.email_placeholder_dev, marker.email_placeholder_inode),
                (marker.email_uid, marker.email_gid),
                (marker.email_placeholder_uid, marker.email_placeholder_gid),
            ),
        )
        for (
            root_name,
            source_identity,
            placeholder_identity,
            source_owner,
            placeholder_owner,
        ) in states:
            source = _directory_state_at(data_fd, root_name)
            placeholder_name = _placeholder_name(bundle_id, root_name)
            placeholder = _directory_state_at(data_fd, placeholder_name)
            if (
                source is None
                or not _same_inode(source, source_identity)
                or not _same_owner_group(source, *source_owner)
            ):
                raise RecoveryError("migration recovery source inode drift")
            expected_mode = marker.documents_mode
            if root_name == "email":
                expected_mode = marker.email_mode
            if stat.S_IMODE(source.st_mode) != expected_mode:
                raise RecoveryError("migration recovery source mode drift")
            if (
                placeholder is None
                or not _same_inode(placeholder, placeholder_identity)
                or not _same_owner_group(placeholder, *placeholder_owner)
            ):
                raise RecoveryError("migration recovery placeholder inode drift")
            if not _safe_directory_mode(
                stat.S_IMODE(placeholder.st_mode), {0o500, 0o550, 0o555}
            ):
                raise RecoveryError("migration recovery placeholder mode drift")
            frozen = f".cutoff-{bundle_id}-{root_name}"
            os.rename(root_name, frozen, src_dir_fd=data_fd, dst_dir_fd=data_fd)
            os.rename(placeholder_name, root_name, src_dir_fd=data_fd, dst_dir_fd=data_fd)
        os.chmod(data_root, 0o555, follow_symlinks=False)
        os.fsync(data_fd)
    finally:
        os.close(data_fd)


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
    if not _same_owner_group(root_state, marker.parent_uid, marker.parent_gid):
        raise RecoveryError("migration recovery data root ownership drift")
    if stat.S_IMODE(root_state.st_mode) not in {marker.parent_mode, 0o555}:
        raise RecoveryError("migration recovery data root mode drift")
    os.chmod(data_root, marker.parent_mode, follow_symlinks=False)
    data_fd = os.open(data_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        _restore_root_at(
            data_fd,
            marker.bundle_id,
            "carfast_documents",
            f".cutoff-{marker.bundle_id}-carfast_documents",
            marker.documents_mode,
            owner_group=(marker.documents_uid, marker.documents_gid),
            placeholder_owner_group=(
                marker.documents_placeholder_uid,
                marker.documents_placeholder_gid,
            ),
            source_identity=(marker.documents_source_dev, marker.documents_source_inode),
            placeholder_identity=(
                marker.documents_placeholder_dev,
                marker.documents_placeholder_inode,
            ),
        )
        _restore_root_at(
            data_fd,
            marker.bundle_id,
            "email",
            f".cutoff-{marker.bundle_id}-email",
            marker.email_mode,
            owner_group=(marker.email_uid, marker.email_gid),
            placeholder_owner_group=(
                marker.email_placeholder_uid,
                marker.email_placeholder_gid,
            ),
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("arm", "barrier", "recover"))
    parser.add_argument("--bundle-id")
    parser.add_argument("--data-root", type=Path, default=Path("/var/data"))
    args = parser.parse_args()
    if args.action in {"arm", "barrier"} and not args.bundle_id:
        parser.error("--bundle-id is required")
    if args.action == "arm":
        arm_migration_window(args.bundle_id, data_root=args.data_root)
        print("migration_window_arm=complete")
    elif args.action == "barrier":
        activate_storage_barrier(args.bundle_id, data_root=args.data_root)
        print("migration_window_barrier=complete")
    else:
        database_url = os.environ.get("DATABASE_URL", "")
        recovered = recover_migration_window(database_url, data_root=args.data_root)
        print(f"migration_window_recovery={'complete' if recovered else 'noop'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
