"""Bounded, authenticated encrypted spool for private integral transfers."""

from __future__ import annotations

import hashlib
import os
import shutil
import struct
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"CARFAST-SPOOL\x00\x01"
HEADER = struct.Struct(">QII12s")
CHUNK_BYTES = 1024 * 1024
TAG_BYTES = 16
MAX_SPOOL_BYTES = 2 * 1024 * 1024 * 1024
MIN_FREE_MARGIN = 128 * 1024 * 1024


class SpoolRejected(RuntimeError):
    """The encrypted spool failed a fail-closed contract check."""


@dataclass(frozen=True, slots=True)
class SpoolEvidence:
    bytes: int
    chunks: int
    sha256: str


def _aad(sequence: int, size: int) -> bytes:
    return MAGIC + struct.pack(">QI", sequence, size)


def preflight_space(path: Path, declared_size: int, *, margin: int = MIN_FREE_MARGIN) -> None:
    if not 0 <= declared_size <= MAX_SPOOL_BYTES:
        raise SpoolRejected("declared size outside spool limit")
    free = shutil.disk_usage(path.parent).free
    encrypted_overhead = ((declared_size + CHUNK_BYTES - 1) // CHUNK_BYTES) * (
        HEADER.size + TAG_BYTES
    )
    if free < declared_size + encrypted_overhead + margin:
        raise SpoolRejected("insufficient spool space")


def encrypt_to_spool(
    source: BinaryIO,
    path: Path,
    key: bytearray,
    *,
    declared_size: int,
    declared_sha256: str,
) -> SpoolEvidence:
    if len(key) != 32 or len(declared_sha256) != 64:
        raise SpoolRejected("invalid in-memory key or digest contract")
    path.parent.mkdir(parents=True, exist_ok=True)
    preflight_space(path, declared_size)
    aes = AESGCM(bytes(key))
    digest = hashlib.sha256()
    total = chunks = 0
    try:
        with path.open("xb") as target:
            target.write(MAGIC)
            while chunk := source.read(CHUNK_BYTES):
                total += len(chunk)
                if total > declared_size or total > MAX_SPOOL_BYTES:
                    raise SpoolRejected("stream exceeds declared or total limit")
                nonce = os.urandom(12)
                ciphertext = aes.encrypt(nonce, chunk, _aad(chunks, len(chunk)))
                target.write(HEADER.pack(chunks, len(chunk), len(ciphertext), nonce))
                target.write(ciphertext)
                digest.update(chunk)
                chunks += 1
            target.flush()
            os.fsync(target.fileno())
        observed = digest.hexdigest()
        if total != declared_size or observed != declared_sha256:
            raise SpoolRejected("stream size or digest mismatch")
        return SpoolEvidence(total, chunks, observed)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def iter_decrypted_spool(path: Path, key: bytearray, evidence: SpoolEvidence) -> Iterator[bytes]:
    if len(key) != 32:
        raise SpoolRejected("invalid in-memory key")
    aes = AESGCM(bytes(key))
    digest = hashlib.sha256()
    total = chunks = 0
    try:
        with path.open("rb") as source:
            if source.read(len(MAGIC)) != MAGIC:
                raise SpoolRejected("invalid encrypted spool magic")
            while total < evidence.bytes:
                raw = source.read(HEADER.size)
                if len(raw) != HEADER.size:
                    raise SpoolRejected("truncated encrypted spool")
                sequence, size, encrypted_size, nonce = HEADER.unpack(raw)
                if (
                    sequence != chunks
                    or not 0 < size <= CHUNK_BYTES
                    or encrypted_size != size + TAG_BYTES
                ):
                    raise SpoolRejected("invalid encrypted spool record")
                ciphertext = source.read(encrypted_size)
                if len(ciphertext) != encrypted_size:
                    raise SpoolRejected("truncated encrypted spool")
                try:
                    plaintext = aes.decrypt(nonce, ciphertext, _aad(sequence, size))
                except InvalidTag as exc:
                    raise SpoolRejected("encrypted spool authentication failed") from exc
                total += len(plaintext)
                if total > evidence.bytes:
                    raise SpoolRejected("encrypted spool exceeds verified size")
                digest.update(plaintext)
                chunks += 1
                yield plaintext
            if source.read(1):
                raise SpoolRejected("trailing encrypted spool bytes")
        if (
            chunks != evidence.chunks
            or total != evidence.bytes
            or digest.hexdigest() != evidence.sha256
        ):
            raise SpoolRejected("decrypted spool evidence mismatch")
    except BaseException:
        raise


def destroy_spool(path: Path, key: bytearray) -> None:
    path.unlink(missing_ok=True)
    for index in range(len(key)):
        key[index] = 0


def restore_verified_spool(
    path: Path,
    key: bytearray,
    evidence: SpoolEvidence,
    command: list[str],
    *,
    timeout: float,
) -> None:
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None
    try:
        for chunk in iter_decrypted_spool(path, key, evidence):
            process.stdin.write(chunk)
        process.stdin.close()
        process.stdin = None
        try:
            _stdout, stderr = process.communicate(timeout=timeout)
            returncode = process.returncode
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise SpoolRejected("verified consumer timeout") from exc
    except BrokenPipeError:
        process.stdin = None
        _stdout, stderr = process.communicate()
        returncode = process.returncode
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    if returncode:
        raise SpoolRejected(
            f"verified consumer failed rc={returncode} stderr_bytes={len(stderr)}"
        )
