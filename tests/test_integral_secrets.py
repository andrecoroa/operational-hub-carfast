from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from app.platform.integral_secrets import (
    bootstrap_integral_secrets,
    load_secret_envelope,
    sqlalchemy_database_url,
)


def encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


def envelope(
    path: Path,
    *,
    url: str = "postgresql://role:secret@dpg-private:5432/carfast_integral_staging_final",
    key: str = "k" * 32,
) -> bytes:
    raw = json.dumps(
        {
            "version": 1,
            "role": "receiver",
            "database_url_b64": encoded(url),
            "transfer_key_b64": encoded(key),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return raw


def test_restricted_envelope_loads_and_bootstraps(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    raw = envelope(path)
    env = {
        "INTEGRAL_SECRET_ENVELOPE_FILE": str(path),
        "INTEGRAL_SECRET_ENVELOPE_ROLE": "receiver",
        "INTEGRAL_SECRET_ENVELOPE_SHA256": hashlib.sha256(raw).hexdigest(),
        "INTEGRAL_EXPECTED_DATABASE_HOST": "dpg-private",
        "INTEGRAL_EXPECTED_DATABASE_NAME": "carfast_integral_staging_final",
        "INTEGRAL_MANAGED_SECRET_ROOT": str(tmp_path),
        "INTEGRAL_PRIVATE_SECRET_ROOT": str(tmp_path / "private"),
    }
    assert bootstrap_integral_secrets(env) == hashlib.sha256(raw).hexdigest()
    assert env["STAGING_DATABASE_URL"].startswith("postgresql://")
    assert env["DATABASE_URL"].startswith("postgresql+psycopg://")
    assert env["DATABASE_URL"].removeprefix("postgresql+psycopg://") == env[
        "STAGING_DATABASE_URL"
    ].removeprefix("postgresql://")
    assert env["INTEGRAL_TRANSFER_KEY"] == "k" * 32


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ],
)
def test_sqlalchemy_url_is_pinned_to_installed_psycopg_driver(
    value: str, expected: str
) -> None:
    assert sqlalchemy_database_url(value) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "[200~postgresql://role:secret@dpg-private:5432/carfast_integral_staging_final",
        "postgresql://role:secret@dpg-private:5432/carfast_integral_staging_final[201~",
        "postgresql://role:secret@dpg-private:5432/carfast_integral_staging_final\n",
        " postgresql://role:secret@dpg-private:5432/carfast_integral_staging_final",
        "postgresql://role:secret@evil-private:5432/carfast_integral_staging_final",
        "postgresql://role:secret@dpg-private:5432/wrong_database",
        "https://role:secret@dpg-private:5432/carfast_integral_staging_final",
    ],
)
def test_database_url_adversarials_fail_closed(tmp_path: Path, bad: str) -> None:
    path = tmp_path / "bad.json"
    envelope(path, url=bad)
    with pytest.raises(RuntimeError):
        load_secret_envelope(
            path, expected_role="receiver", expected_host="dpg-private",
            expected_database="carfast_integral_staging_final",
        )


@pytest.mark.parametrize("value", ["", "%%%", encoded("short"), encoded("k\n" + "x" * 31)])
def test_empty_encoding_truncation_and_control_secret_fail_closed(
    tmp_path: Path, value: str
) -> None:
    path = tmp_path / "bad-key.json"
    raw = json.loads(envelope(path))
    raw["transfer_key_b64"] = value
    path.write_text(json.dumps(raw))
    path.chmod(0o600)
    with pytest.raises(RuntimeError):
        load_secret_envelope(
            path, expected_role="receiver", expected_host="dpg-private",
            expected_database="carfast_integral_staging_final",
        )


def test_unknown_claim_role_fingerprint_and_quoting_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "closed.json"
    raw = json.loads(envelope(path))
    raw["unknown"] = "no"
    path.write_text(json.dumps(raw))
    path.chmod(0o600)
    with pytest.raises(RuntimeError, match="claims are not closed"):
        load_secret_envelope(
            path,
            expected_role="receiver",
            expected_host="dpg-private",
            expected_database="carfast_integral_staging_final",
        )

    raw.pop("unknown")
    raw["database_url_b64"] = encoded("postgresql://role:'bad'@dpg-private:5432/carfast_integral_staging_final")
    path.write_text(json.dumps(raw))
    path.chmod(0o600)
    with pytest.raises(RuntimeError, match="shape is invalid"):
        load_secret_envelope(
            path,
            expected_role="receiver",
            expected_host="dpg-private",
            expected_database="carfast_integral_staging_final",
        )

    raw_bytes = envelope(path)
    env = {
        "INTEGRAL_SECRET_ENVELOPE_FILE": str(path),
        "INTEGRAL_SECRET_ENVELOPE_ROLE": "receiver",
        "INTEGRAL_SECRET_ENVELOPE_SHA256": "0" * 64,
        "INTEGRAL_EXPECTED_DATABASE_HOST": "dpg-private",
        "INTEGRAL_EXPECTED_DATABASE_NAME": "carfast_integral_staging_final",
        "INTEGRAL_MANAGED_SECRET_ROOT": str(tmp_path),
        "INTEGRAL_PRIVATE_SECRET_ROOT": str(tmp_path / "private"),
    }
    assert raw_bytes
    with pytest.raises(RuntimeError, match="fingerprint mismatch"):
        bootstrap_integral_secrets(env)


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX mount permissions")
def test_managed_mount_is_copied_to_private_file_and_removed(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    source = managed / "envelope.json"
    raw = envelope(source)
    source.chmod(0o444)  # Render-managed mounts need not themselves be mode 0600.
    private = tmp_path / "private"
    env = {
        "INTEGRAL_SECRET_ENVELOPE_FILE": str(source),
        "INTEGRAL_SECRET_ENVELOPE_ROLE": "receiver",
        "INTEGRAL_SECRET_ENVELOPE_SHA256": hashlib.sha256(raw).hexdigest(),
        "INTEGRAL_EXPECTED_DATABASE_HOST": "dpg-private",
        "INTEGRAL_EXPECTED_DATABASE_NAME": "carfast_integral_staging_final",
        "INTEGRAL_MANAGED_SECRET_ROOT": str(managed),
        "INTEGRAL_PRIVATE_SECRET_ROOT": str(private),
    }
    assert bootstrap_integral_secrets(env) == hashlib.sha256(raw).hexdigest()
    assert private.stat().st_mode & 0o777 == 0o700
    assert list(private.iterdir()) == []


@pytest.mark.skipif(__import__("os").name == "nt", reason="POSIX symlink contract")
def test_managed_secret_symlink_fails_before_copy(tmp_path: Path) -> None:
    managed = tmp_path / "managed"
    managed.mkdir()
    target = managed / "target.json"
    raw = envelope(target)
    source = managed / "envelope.json"
    source.symlink_to(target)
    env = {
        "INTEGRAL_SECRET_ENVELOPE_FILE": str(source),
        "INTEGRAL_SECRET_ENVELOPE_ROLE": "receiver",
        "INTEGRAL_SECRET_ENVELOPE_SHA256": hashlib.sha256(raw).hexdigest(),
        "INTEGRAL_EXPECTED_DATABASE_HOST": "dpg-private",
        "INTEGRAL_EXPECTED_DATABASE_NAME": "carfast_integral_staging_final",
        "INTEGRAL_MANAGED_SECRET_ROOT": str(managed),
        "INTEGRAL_PRIVATE_SECRET_ROOT": str(tmp_path / "private"),
    }
    with pytest.raises(RuntimeError, match="regular file"):
        bootstrap_integral_secrets(env)
