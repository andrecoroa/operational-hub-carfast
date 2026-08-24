"""Fail-closed loading of integral rehearsal secrets from a restricted file."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import stat
import tempfile
from collections.abc import MutableMapping
from pathlib import Path
from urllib.parse import unquote, urlsplit

MAX_ENVELOPE_BYTES = 16 * 1024
PASTE_MARKERS = ("[200~", "[201~", "\x1b[200~", "\x1b[201~")
SECRET_KEYS = {"database_url_b64", "role", "transfer_key_b64", "version"}
DEFAULT_MANAGED_ROOT = Path("/etc/secrets")
DEFAULT_PRIVATE_ROOT = Path("/dev/shm/carfast-integral")


def _decode(value: object, claim: str) -> str:
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"integral secret {claim} is empty")
    if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise RuntimeError(f"integral secret {claim} encoding is invalid")
    try:
        decoded = base64.b64decode(value, altchars=b"-_", validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(f"integral secret {claim} encoding is invalid") from exc
    if not decoded:
        raise RuntimeError(f"integral secret {claim} is empty")
    if any(marker in decoded for marker in PASTE_MARKERS):
        raise RuntimeError(f"integral secret {claim} contains a paste delimiter")
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        raise RuntimeError(f"integral secret {claim} contains control characters")
    if decoded != decoded.strip() or any(char.isspace() for char in decoded):
        raise RuntimeError(f"integral secret {claim} contains whitespace")
    return decoded


def validate_database_url(value: str, expected_host: str, expected_database: str) -> None:
    if any(character in value for character in ("'", '"', "\\", "`")):
        raise RuntimeError("integral secret database URL shape is invalid")
    parsed = urlsplit(value.replace("postgresql+psycopg", "postgresql", 1))
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise RuntimeError("integral secret database URL scheme is invalid")
    if parsed.hostname != expected_host or parsed.port not in {None, 5432}:
        raise RuntimeError("integral secret database URL host is outside allowlist")
    if unquote(parsed.path.lstrip("/")) != expected_database:
        raise RuntimeError("integral secret database URL database is outside allowlist")
    if not parsed.username or parsed.password is None or parsed.query or parsed.fragment:
        raise RuntimeError("integral secret database URL shape is invalid")


def sqlalchemy_database_url(value: str) -> str:
    """Pin SQLAlchemy to the installed psycopg v3 driver without changing the libpq URL."""
    if value.startswith("postgresql://"):
        return "postgresql+psycopg://" + value.removeprefix("postgresql://")
    if value.startswith("postgres://"):
        return "postgresql+psycopg://" + value.removeprefix("postgres://")
    return value


def load_secret_envelope(
    path: Path, *, expected_role: str, expected_host: str, expected_database: str
) -> tuple[dict[str, str], str]:
    resolved = path.resolve(strict=True)
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size <= 0 or info.st_size > MAX_ENVELOPE_BYTES:
        raise RuntimeError("integral secret envelope file is invalid")
    if os.name != "nt" and info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise RuntimeError("integral secret envelope permissions are too broad")
    raw = resolved.read_bytes()
    try:
        envelope = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("integral secret envelope JSON is invalid") from exc
    if not isinstance(envelope, dict) or set(envelope) != SECRET_KEYS:
        raise RuntimeError("integral secret envelope claims are not closed")
    if envelope["version"] != 1 or envelope["role"] != expected_role:
        raise RuntimeError("integral secret envelope role or version mismatch")
    database_url = _decode(envelope["database_url_b64"], "database_url")
    transfer_key = _decode(envelope["transfer_key_b64"], "transfer_key")
    if len(transfer_key.encode()) < 32:
        raise RuntimeError("integral secret transfer_key is too short")
    validate_database_url(database_url, expected_host, expected_database)
    fingerprint = hashlib.sha256(raw).hexdigest()
    return {
        "STAGING_DATABASE_URL": database_url,
        "INTEGRAL_TRANSFER_KEY": transfer_key,
    }, fingerprint


def _copy_managed_envelope_once(source: Path, private_root: Path) -> Path:
    """Copy a Render-managed secret to a process-owned 0600 ephemeral file.

    The managed mount may deliberately be readable beyond the process user.  It is
    accepted only as an immutable input owned by root or this process, never as the
    envelope consumed by the runtime.
    """
    source_info = source.lstat()
    if stat.S_ISLNK(source_info.st_mode) or not stat.S_ISREG(source_info.st_mode):
        raise RuntimeError("integral managed secret source is not a regular file")
    if source_info.st_uid not in {0, os.geteuid()}:
        raise RuntimeError("integral managed secret source owner mismatch")
    if source_info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError("integral managed secret source is externally writable")
    if source_info.st_size <= 0 or source_info.st_size > MAX_ENVELOPE_BYTES:
        raise RuntimeError("integral managed secret source size is invalid")

    private_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    private_info = private_root.lstat()
    if stat.S_ISLNK(private_info.st_mode) or not stat.S_ISDIR(private_info.st_mode):
        raise RuntimeError("integral private secret root is invalid")
    if private_info.st_uid != os.geteuid() or private_info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise RuntimeError("integral private secret root permissions are invalid")

    descriptor, name = tempfile.mkstemp(prefix="envelope-", dir=private_root)
    private_path = Path(name)
    try:
        os.fchmod(descriptor, 0o600)
        with source.open("rb") as managed, os.fdopen(descriptor, "wb", closefd=True) as private:
            descriptor = -1
            remaining = MAX_ENVELOPE_BYTES + 1
            while remaining:
                chunk = managed.read(min(8192, remaining))
                if not chunk:
                    break
                private.write(chunk)
                remaining -= len(chunk)
            private.flush()
            os.fsync(private.fileno())
        if private_path.stat().st_size != source_info.st_size:
            raise RuntimeError("integral managed secret changed during copy")
        return private_path
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        private_path.unlink(missing_ok=True)
        raise


def bootstrap_integral_secrets(environment: MutableMapping[str, str] | None = None) -> str:
    env = environment if environment is not None else os.environ
    path = env.get("INTEGRAL_SECRET_ENVELOPE_FILE", "")
    if not path:
        return "none"
    expected_role = env.get("INTEGRAL_SECRET_ENVELOPE_ROLE", "")
    expected_host = env.get("INTEGRAL_EXPECTED_DATABASE_HOST", "")
    expected_database = env.get("INTEGRAL_EXPECTED_DATABASE_NAME", "")
    if not expected_role or not expected_host or not expected_database:
        raise RuntimeError("integral secret envelope expectations are required")
    managed_root = Path(env.get("INTEGRAL_MANAGED_SECRET_ROOT", str(DEFAULT_MANAGED_ROOT)))
    private_root = Path(env.get("INTEGRAL_PRIVATE_SECRET_ROOT", str(DEFAULT_PRIVATE_ROOT)))
    source = Path(path)
    if os.name != "nt":
        if stat.S_ISLNK(source.lstat().st_mode):
            raise RuntimeError("integral managed secret source is not a regular file")
        resolved_source = source.resolve(strict=True)
        resolved_root = managed_root.resolve(strict=True)
        if not resolved_source.is_relative_to(resolved_root):
            raise RuntimeError("integral managed secret source is outside allowlist")
        private_path = _copy_managed_envelope_once(resolved_source, private_root)
    else:
        private_path = source
    try:
        secrets, fingerprint = load_secret_envelope(
            private_path, expected_role=expected_role, expected_host=expected_host,
            expected_database=expected_database,
        )
    finally:
        if os.name != "nt":
            private_path.unlink(missing_ok=True)
    expected_fingerprint = env.get("INTEGRAL_SECRET_ENVELOPE_SHA256", "")
    if not re.fullmatch(r"[0-9a-f]{64}", expected_fingerprint) or not hmac.compare_digest(
        fingerprint, expected_fingerprint
    ):
        raise RuntimeError("integral secret envelope fingerprint mismatch")
    database_url = secrets.pop("STAGING_DATABASE_URL")
    if expected_role == "receiver":
        env["STAGING_DATABASE_URL"] = database_url
    env["DATABASE_URL"] = sqlalchemy_database_url(database_url)
    env.update(secrets)
    return fingerprint
