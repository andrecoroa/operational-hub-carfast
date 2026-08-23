"""One-shot authenticated transport for a private integral Green rehearsal."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, BinaryIO

MAX_LIFETIME_SECONDS = 15 * 60
SERVICE_ID = re.compile(r"^srv-[a-z0-9]+$")
KINDS = {"database", "storage"}


class IntegralTransferRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TransferClaims:
    source: str
    destination: str
    kind: str
    issued_at: int
    expires_at: int
    nonce: str


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_token(key: bytes, *, source: str, destination: str, kind: str) -> str:
    now = int(time.time())
    payload = {
        "destination": destination,
        "expires_at": now + 10 * 60,
        "issued_at": now,
        "kind": kind,
        "nonce": secrets.token_urlsafe(24),
        "scope": "integral-green-rehearsal",
        "source": source,
        "v": 1,
    }
    encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _encode(hmac.new(key, encoded.encode(), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_token(
    token: str,
    key: bytes,
    *,
    expected_source: str,
    expected_destination: str,
    expected_kind: str,
) -> TransferClaims:
    if len(key) < 32 or token.count(".") != 1 or len(token) > 2048:
        raise IntegralTransferRejected("invalid integral transfer authorization")
    encoded, supplied = token.split(".", 1)
    expected = _encode(hmac.new(key, encoded.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied, expected):
        raise IntegralTransferRejected("invalid integral transfer authorization")
    try:
        payload: dict[str, Any] = json.loads(_decode(encoded))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegralTransferRejected("invalid integral transfer authorization") from exc
    required = {
        "destination",
        "expires_at",
        "issued_at",
        "kind",
        "nonce",
        "scope",
        "source",
        "v",
    }
    if set(payload) != required or payload["v"] != 1:
        raise IntegralTransferRejected("invalid integral transfer authorization")
    if payload["scope"] != "integral-green-rehearsal" or payload["kind"] not in KINDS:
        raise IntegralTransferRejected("invalid integral transfer scope")
    if (
        payload["source"] != expected_source
        or payload["destination"] != expected_destination
        or payload["kind"] != expected_kind
    ):
        raise IntegralTransferRejected("integral transfer endpoint mismatch")
    if not SERVICE_ID.fullmatch(payload["source"]) or not SERVICE_ID.fullmatch(
        payload["destination"]
    ):
        raise IntegralTransferRejected("invalid integral transfer service")
    if type(payload["issued_at"]) is not int or type(payload["expires_at"]) is not int:
        raise IntegralTransferRejected("invalid integral transfer time")
    now = int(time.time())
    lifetime = payload["expires_at"] - payload["issued_at"]
    if not 0 < lifetime <= MAX_LIFETIME_SECONDS or payload["expires_at"] <= now:
        raise IntegralTransferRejected("integral transfer authorization expired")
    if payload["issued_at"] > now + 30:
        raise IntegralTransferRejected("integral transfer authorization is from the future")
    nonce = payload["nonce"]
    if not isinstance(nonce, str) or not 22 <= len(nonce) <= 64:
        raise IntegralTransferRejected("invalid integral transfer nonce")
    return TransferClaims(
        source=payload["source"],
        destination=payload["destination"],
        kind=payload["kind"],
        issued_at=payload["issued_at"],
        expires_at=payload["expires_at"],
        nonce=nonce,
    )


class ChunkedReader:
    """Decode one HTTP/1.1 chunked request body without buffering it."""

    def __init__(self, source: BinaryIO):
        self.source = source
        self.remaining = 0
        self.finished = False

    def _next_chunk(self) -> None:
        line = self.source.readline(128)
        if not line.endswith(b"\r\n"):
            raise IntegralTransferRejected("invalid chunk framing")
        try:
            self.remaining = int(line[:-2].split(b";", 1)[0], 16)
        except ValueError as exc:
            raise IntegralTransferRejected("invalid chunk size") from exc
        if self.remaining == 0:
            while True:
                trailer = self.source.readline(8192)
                if trailer == b"\r\n":
                    break
                if not trailer or not trailer.endswith(b"\r\n"):
                    raise IntegralTransferRejected("invalid chunk trailer")
            self.finished = True

    def read(self, size: int = -1) -> bytes:
        if self.finished:
            return b""
        requested = 1024 * 1024 if size < 0 else size
        output = bytearray()
        while len(output) < requested and not self.finished:
            if self.remaining == 0:
                self._next_chunk()
                if self.finished:
                    break
            take = min(requested - len(output), self.remaining)
            chunk = self.source.read(take)
            if len(chunk) != take:
                raise IntegralTransferRejected("truncated chunk")
            output.extend(chunk)
            self.remaining -= take
            if self.remaining == 0 and self.source.read(2) != b"\r\n":
                raise IntegralTransferRejected("invalid chunk terminator")
        return bytes(output)
