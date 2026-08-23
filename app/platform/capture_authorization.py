"""Signed, short-lived authorization for the eight-table capture pilot."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any

MAX_LIFETIME_SECONDS = 15 * 60
MAX_CLOCK_SKEW_SECONDS = 30
NONCE = re.compile(r"^[A-Za-z0-9_-]{22,64}$")
SCOPE = "pilot-eight-table"
_USED_NONCES: set[str] = set()


class AuthorizationRejected(ValueError):
    pass


@dataclass(frozen=True)
class CaptureClaims:
    issued_at: int
    expires_at: int
    source: str
    destination: str
    nonce: str


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_fixture_token(
    key: bytes,
    *,
    source: str,
    destination: str,
    nonce: str,
    issued_at: int,
    expires_at: int,
) -> str:
    """Fixture/test issuer. Production issuance remains an external approval gate."""
    payload = {
        "v": 1,
        "scope": SCOPE,
        "source": source,
        "destination": destination,
        "nonce": nonce,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    encoded = _encode(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    signature = _encode(hmac.new(key, encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_and_consume(
    token: str,
    key: bytes,
    *,
    expected_source: str,
    expected_destination: str,
    now: int | None = None,
) -> CaptureClaims:
    """Validate signature/scope/time and consume nonce for this process lifetime."""
    if len(key) < 32 or len(token) > 2048 or token.count(".") != 1:
        raise AuthorizationRejected("invalid capture authorization")
    encoded, supplied_signature = token.split(".", 1)
    expected_signature = _encode(hmac.new(key, encoded.encode("ascii"), hashlib.sha256).digest())
    if not hmac.compare_digest(supplied_signature, expected_signature):
        raise AuthorizationRejected("invalid capture authorization")
    try:
        payload: dict[str, Any] = json.loads(_decode(encoded))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorizationRejected("invalid capture authorization") from exc
    required = {"v", "scope", "source", "destination", "nonce", "issued_at", "expires_at"}
    if set(payload) != required or payload["v"] != 1 or payload["scope"] != SCOPE:
        raise AuthorizationRejected("invalid capture authorization scope")
    if payload["source"] != expected_source or payload["destination"] != expected_destination:
        raise AuthorizationRejected("capture authorization endpoint mismatch")
    if not isinstance(payload["nonce"], str) or not NONCE.fullmatch(payload["nonce"]):
        raise AuthorizationRejected("invalid capture authorization nonce")
    if type(payload["issued_at"]) is not int or type(payload["expires_at"]) is not int:
        raise AuthorizationRejected("invalid capture authorization time")
    current = int(time.time()) if now is None else now
    lifetime = payload["expires_at"] - payload["issued_at"]
    if not 0 < lifetime <= MAX_LIFETIME_SECONDS:
        raise AuthorizationRejected("capture authorization lifetime exceeds policy")
    if payload["issued_at"] > current + MAX_CLOCK_SKEW_SECONDS:
        raise AuthorizationRejected("capture authorization is from the future")
    if payload["expires_at"] <= current:
        raise AuthorizationRejected("capture authorization expired")
    if payload["nonce"] in _USED_NONCES:
        raise AuthorizationRejected("capture authorization replay rejected")
    _USED_NONCES.add(payload["nonce"])
    return CaptureClaims(
        issued_at=payload["issued_at"],
        expires_at=payload["expires_at"],
        source=payload["source"],
        destination=payload["destination"],
        nonce=payload["nonce"],
    )


def reset_fixture_replay_cache() -> None:
    """Tests only; production code must never clear the process replay cache."""
    _USED_NONCES.clear()
