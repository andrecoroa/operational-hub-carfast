"""Authenticated, framed TCP transport for the integral Green rehearsal."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import socket
import struct
import time
from dataclasses import dataclass
from typing import BinaryIO

MAGIC = b"CARFAST-INTEGRAL-TCP\x00\x01"
PROTOCOL_VERSION = 1
MAX_HANDSHAKE = 16 * 1024
MAX_FRAME = 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024 * 1024
MAX_LIFETIME = 15 * 60
STREAM_TYPES = {"database", "storage", "manifest"}
SERVICE_ID_PREFIX = "srv-"
FRAME_DATA = 1
FRAME_FINAL = 2
FRAME_CONTROL = 3
CONTROL_BUNDLE_SPOOL_ACCEPTED = 1
CONTROL_SPOOL_ACCEPTED = CONTROL_BUNDLE_SPOOL_ACCEPTED
CONTROL_CONSUMER_RESULT = 2
CONTROL_OK = 1
CONTROL_FAILED = 0
DATA_HEADER = struct.Struct(">BQI32s32s")
FINAL_HEADER = struct.Struct(">BQQQ32s32s")
CONTROL_HEADER = struct.Struct(">BBBQQ32s32s")


class TcpTransferRejected(RuntimeError):
    pass


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_tcp_token(
    key: bytes,
    *,
    source: str,
    destination: str,
    release: str,
    cutoff: str,
    bundle_id: str,
    stream_type: str,
    lifetime: int = 10 * 60,
) -> str:
    if len(key) < 32 or not 0 < lifetime <= MAX_LIFETIME:
        raise ValueError("invalid TCP transfer key or lifetime")
    now = int(time.time())
    payload = {
        "cutoff": cutoff,
        "bundle_id": bundle_id,
        "destination": destination,
        "expires_at": now + lifetime,
        "issued_at": now,
        "nonce": secrets.token_urlsafe(24),
        "release": release,
        "scope": "integral-green-tcp-v1",
        "source": source,
        "stream_type": stream_type,
        "v": PROTOCOL_VERSION,
    }
    encoded = _b64(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return f"{encoded}.{_b64(hmac.new(key, encoded.encode(), hashlib.sha256).digest())}"


def verify_tcp_token(
    token: str,
    key: bytes,
    *,
    source: str,
    destination: str,
    release: str,
    cutoff: str,
    bundle_id: str,
    stream_type: str,
    used_nonces: set[str],
) -> str:
    if len(key) < 32 or token.count(".") != 1 or len(token) > 4096:
        raise TcpTransferRejected("invalid authorization")
    encoded, supplied = token.split(".", 1)
    expected = _b64(hmac.new(key, encoded.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied, expected):
        raise TcpTransferRejected("invalid authorization")
    try:
        payload = json.loads(_unb64(encoded))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TcpTransferRejected("invalid authorization") from exc
    required = {
        "cutoff",
        "bundle_id",
        "destination",
        "expires_at",
        "issued_at",
        "nonce",
        "release",
        "scope",
        "source",
        "stream_type",
        "v",
    }
    if set(payload) != required or payload["v"] != PROTOCOL_VERSION:
        raise TcpTransferRejected("invalid authorization contract")
    if (
        payload["scope"] != "integral-green-tcp-v1"
        or payload["source"] != source
        or payload["destination"] != destination
        or payload["release"] != release
        or payload["cutoff"] != cutoff
        or payload["bundle_id"] != bundle_id
        or payload["stream_type"] != stream_type
        or stream_type not in STREAM_TYPES
        or not source.startswith(SERVICE_ID_PREFIX)
        or not destination.startswith(SERVICE_ID_PREFIX)
    ):
        raise TcpTransferRejected("authorization endpoint mismatch")
    now = int(time.time())
    lifetime = payload["expires_at"] - payload["issued_at"]
    if not 0 < lifetime <= MAX_LIFETIME or payload["expires_at"] <= now:
        raise TcpTransferRejected("authorization expired")
    nonce = payload["nonce"]
    if not isinstance(nonce, str) or not 22 <= len(nonce) <= 64 or nonce in used_nonces:
        raise TcpTransferRejected("authorization replay")
    used_nonces.add(nonce)
    return nonce


def _read_exact(source: BinaryIO, size: int) -> bytes:
    result = bytearray()
    while len(result) < size:
        chunk = source.read(size - len(result))
        if not chunk:
            raise TcpTransferRejected("premature stream close")
        result.extend(chunk)
    return bytes(result)


def ensure_no_trailing(source: BinaryIO) -> None:
    if source.read(1):
        raise TcpTransferRejected("trailing bytes after final frame")


def _frame_mac(key: bytes, session: str, fields: bytes) -> bytes:
    return hmac.new(key, session.encode() + fields, hashlib.sha256).digest()


def write_control(
    target: BinaryIO,
    key: bytes,
    session: str,
    *,
    phase: int,
    ok: bool,
    frames: int,
    total: int,
    digest: bytes,
) -> None:
    """Write an authenticated two-phase acknowledgement without payload details."""
    if phase not in {CONTROL_BUNDLE_SPOOL_ACCEPTED, CONTROL_CONSUMER_RESULT} or len(digest) != 32:
        raise TcpTransferRejected("invalid control frame")
    fields = struct.pack(">BBBQQ32s", FRAME_CONTROL, phase, int(ok), frames, total, digest)
    _write_all(target, fields + _frame_mac(key, session, fields))
    target.flush()


def read_control(
    source: BinaryIO,
    key: bytes,
    session: str,
    *,
    expected_phase: int,
    frames: int,
    total: int,
    digest: bytes,
) -> None:
    raw = _read_exact(source, CONTROL_HEADER.size)
    kind, phase, ok, observed_frames, observed_total, observed_digest, supplied_mac = (
        CONTROL_HEADER.unpack(raw)
    )
    fields = raw[:-32]
    if (
        kind != FRAME_CONTROL
        or phase != expected_phase
        or ok != CONTROL_OK
        or observed_frames != frames
        or observed_total != total
        or observed_digest != digest
        or not hmac.compare_digest(supplied_mac, _frame_mac(key, session, fields))
    ):
        raise TcpTransferRejected("invalid or failed control acknowledgement")


def _write_all(target: BinaryIO, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = target.write(view)
        if written is None:
            written = len(view)
        if written <= 0:
            raise TcpTransferRejected("premature stream write close")
        view = view[written:]


@dataclass(slots=True)
class FramedReader:
    source: BinaryIO
    key: bytes
    session: str
    expected_sequence: int = 0
    total: int = 0
    final_digest: object = None
    finished: bool = False
    pending: bytes = b""

    def __post_init__(self) -> None:
        self.final_digest = hashlib.sha256()

    def _next(self) -> None:
        kind = _read_exact(self.source, 1)[0]
        if kind == FRAME_DATA:
            rest = _read_exact(self.source, DATA_HEADER.size - 1)
            _kind, sequence, size, digest, supplied_mac = DATA_HEADER.unpack(bytes([kind]) + rest)
            fields = struct.pack(">BQI32s", kind, sequence, size, digest)
            if sequence != self.expected_sequence or not 0 < size <= MAX_FRAME:
                raise TcpTransferRejected("invalid frame sequence or size")
            if not hmac.compare_digest(supplied_mac, _frame_mac(self.key, self.session, fields)):
                raise TcpTransferRejected("invalid frame authentication")
            payload = _read_exact(self.source, size)
            if hashlib.sha256(payload).digest() != digest:
                raise TcpTransferRejected("invalid frame digest")
            self.total += size
            if self.total > MAX_TOTAL:
                raise TcpTransferRejected("stream exceeds total limit")
            self.final_digest.update(payload)
            self.expected_sequence += 1
            self.pending = payload
            return
        if kind == FRAME_FINAL:
            rest = _read_exact(self.source, FINAL_HEADER.size - 1)
            _kind, sequence, frames, total, digest, supplied_mac = FINAL_HEADER.unpack(
                bytes([kind]) + rest
            )
            fields = struct.pack(">BQQQ32s", kind, sequence, frames, total, digest)
            if (
                sequence != self.expected_sequence
                or frames != self.expected_sequence
                or total != self.total
                or digest != self.final_digest.digest()
                or not hmac.compare_digest(supplied_mac, _frame_mac(self.key, self.session, fields))
            ):
                raise TcpTransferRejected("invalid final frame")
            self.finished = True
            return
        raise TcpTransferRejected("unknown frame type")

    def read(self, size: int = -1) -> bytes:
        requested = MAX_FRAME if size < 0 else size
        while not self.pending and not self.finished:
            self._next()
        if not self.pending:
            return b""
        result, self.pending = self.pending[:requested], self.pending[requested:]
        return result


def write_framed(
    source: BinaryIO, target: BinaryIO, key: bytes, session: str
) -> tuple[int, int, str]:
    sequence = 0
    total = 0
    final = hashlib.sha256()
    while chunk := source.read(MAX_FRAME):
        digest = hashlib.sha256(chunk).digest()
        fields = struct.pack(">BQI32s", FRAME_DATA, sequence, len(chunk), digest)
        _write_all(target, fields + _frame_mac(key, session, fields) + chunk)
        target.flush()
        final.update(chunk)
        total += len(chunk)
        if total > MAX_TOTAL:
            raise TcpTransferRejected("stream exceeds total limit")
        sequence += 1
    digest = final.digest()
    fields = struct.pack(">BQQQ32s", FRAME_FINAL, sequence, sequence, total, digest)
    _write_all(target, fields + _frame_mac(key, session, fields))
    target.flush()
    return sequence, total, digest.hex()


def client_handshake(sock: socket.socket, token: str, stream_type: str) -> tuple[BinaryIO, str]:
    session = secrets.token_urlsafe(24)
    payload = json.dumps(
        {"session": session, "stream_type": stream_type, "token": token, "v": PROTOCOL_VERSION},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    if len(payload) > MAX_HANDSHAKE:
        raise TcpTransferRejected("handshake too large")
    sock.sendall(MAGIC + struct.pack(">I", len(payload)) + payload)
    if sock.recv(1) != b"\x01":
        raise TcpTransferRejected("handshake rejected")
    return sock.makefile("rwb", buffering=0), session


def server_handshake(
    sock: socket.socket,
    key: bytes,
    *,
    source: str,
    destination: str,
    release: str,
    cutoff: str,
    bundle_id: str,
    stream_type: str | None,
    used_nonces: set[str],
) -> tuple[BinaryIO, str, str]:
    handle = sock.makefile("rwb", buffering=0)
    if _read_exact(handle, len(MAGIC)) != MAGIC:
        raise TcpTransferRejected("invalid protocol magic")
    size = struct.unpack(">I", _read_exact(handle, 4))[0]
    if not 0 < size <= MAX_HANDSHAKE:
        raise TcpTransferRejected("invalid handshake size")
    payload = json.loads(_read_exact(handle, size))
    if set(payload) != {"session", "stream_type", "token", "v"}:
        raise TcpTransferRejected("invalid handshake contract")
    actual_stream_type = payload["stream_type"]
    if (
        payload["v"] != PROTOCOL_VERSION
        or actual_stream_type not in STREAM_TYPES
        or (stream_type is not None and actual_stream_type != stream_type)
    ):
        raise TcpTransferRejected("invalid handshake endpoint")
    verify_tcp_token(
        payload["token"],
        key,
        source=source,
        destination=destination,
        release=release,
        cutoff=cutoff,
        bundle_id=bundle_id,
        stream_type=actual_stream_type,
        used_nonces=used_nonces,
    )
    session = payload["session"]
    if not isinstance(session, str) or not 22 <= len(session) <= 64:
        raise TcpTransferRejected("invalid session")
    handle.write(b"\x01")
    handle.flush()
    return handle, session, actual_stream_type
