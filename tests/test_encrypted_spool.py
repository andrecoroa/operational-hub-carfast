from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

import pytest

from app.platform.encrypted_spool import (
    HEADER,
    MAGIC,
    SpoolRejected,
    destroy_spool,
    encrypt_to_spool,
    encrypt_verified_stream,
    iter_decrypted_spool,
    preflight_space,
    restore_verified_spool,
)


def _write(tmp_path: Path, payload: bytes):
    key = bytearray(b"k" * 32)
    path = tmp_path / "payload.spool"
    evidence = encrypt_to_spool(
        io.BytesIO(payload), path, key,
        declared_size=len(payload), declared_sha256=hashlib.sha256(payload).hexdigest(),
    )
    return path, key, evidence


def test_spool_roundtrip_and_key_cleanup(tmp_path: Path) -> None:
    payload = b"synthetic-carfast\x00" * 100_000
    path, key, evidence = _write(tmp_path, payload)
    assert path.read_bytes().find(payload[:128]) == -1
    assert b"".join(iter_decrypted_spool(path, key, evidence)) == payload
    destroy_spool(path, key)
    assert not path.exists()
    assert key == bytearray(32)


@pytest.mark.parametrize("mutation", ["ciphertext", "truncate", "reorder", "trailing"])
def test_spool_adversarial_cleanup(tmp_path: Path, mutation: str) -> None:
    path, key, evidence = _write(tmp_path, b"x" * (1024 * 1024 + 31))
    data = bytearray(path.read_bytes())
    if mutation == "ciphertext":
        data[len(MAGIC) + HEADER.size] ^= 1
    elif mutation == "truncate":
        del data[-10:]
    elif mutation == "reorder":
        data[len(MAGIC):len(MAGIC) + 8] = (2).to_bytes(8, "big")
    else:
        data.extend(b"trailing")
    path.write_bytes(data)
    with pytest.raises(SpoolRejected):
        b"".join(iter_decrypted_spool(path, key, evidence))
    destroy_spool(path, key)
    assert not path.exists() and key == bytearray(32)


@pytest.mark.parametrize("size_delta,digest", [(1, None), (0, "0" * 64)])
def test_size_and_digest_fail_before_decrypt(
    tmp_path: Path, size_delta: int, digest: str | None
) -> None:
    payload = b"synthetic"
    path = tmp_path / "bad.spool"
    key = bytearray(b"s" * 32)
    with pytest.raises(SpoolRejected, match="size or digest"):
        encrypt_to_spool(
            io.BytesIO(payload), path, key,
            declared_size=len(payload) + size_delta,
            declared_sha256=digest or hashlib.sha256(payload).hexdigest(),
        )
    assert not path.exists()


def test_disk_preflight_rejects_impossible_contract(tmp_path: Path) -> None:
    with pytest.raises(SpoolRejected):
        preflight_space(tmp_path / "x", 3 * 1024 * 1024 * 1024)


def test_restore_failure_is_deterministic_and_payload_free(tmp_path: Path) -> None:
    path, key, evidence = _write(tmp_path, b"secret-synthetic-payload")
    with pytest.raises(
        SpoolRejected, match=r"verified consumer failed rc=17 stderr_bytes=4"
    ) as failure:
        restore_verified_spool(
            path,
            key,
            evidence,
            [
                sys.executable,
                "-c",
                "import sys;sys.stdin.buffer.read();sys.stderr.write('safe');sys.exit(17)",
            ],
            timeout=5,
        )
    assert "secret-synthetic-payload" not in str(failure.value)
    destroy_spool(path, key)


def test_restore_timeout_is_fail_closed(tmp_path: Path) -> None:
    path, key, evidence = _write(tmp_path, b"x")
    with pytest.raises(SpoolRejected, match="timeout"):
        restore_verified_spool(
            path,
            key,
            evidence,
            [sys.executable, "-c", "import time;time.sleep(2)"],
            timeout=0.01,
        )
    destroy_spool(path, key)


def test_verified_stream_requires_final_evidence(tmp_path: Path) -> None:
    source = io.BytesIO(b"not-a-finalized-framed-reader")
    key = bytearray(b"v" * 32)
    path = tmp_path / "unverified.spool"
    with pytest.raises(SpoolRejected, match="missing final"):
        encrypt_verified_stream(source, path, key, max_bytes=1024)
    assert not path.exists()
