"""Signed, versioned return destinations for deterministic post-action navigation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass
from urllib.parse import urlsplit

RETURN_CONTEXT_VERSION = 1


@dataclass(frozen=True, slots=True)
class ReturnContext:
    version: int
    path: str
    query: str
    anchor: str
    issued_at: int

    @property
    def url(self) -> str:
        target = self.path
        if self.query:
            target = f"{target}?{self.query}"
        if self.anchor:
            target = f"{target}#{self.anchor}"
        return target


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _valid_path(path: str, allowed_prefixes: tuple[str, ...]) -> bool:
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return False
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        return False
    if any(ord(character) < 32 for character in path):
        return False
    return any(
        prefix == "/" or path == prefix or path.startswith(f"{prefix}/")
        for prefix in allowed_prefixes
    )


def issue_return_context(
    secret: str,
    *,
    path: str,
    query: str = "",
    anchor: str = "",
    issued_at: int | None = None,
) -> str:
    if not _valid_path(path, ("/",)) or len(query) > 2000 or len(anchor) > 160:
        raise ValueError("Unsafe return context")
    if any(character in query + anchor for character in "\r\n"):
        raise ValueError("Unsafe return context")
    context = ReturnContext(
        version=RETURN_CONTEXT_VERSION,
        path=path,
        query=query.lstrip("?"),
        anchor=anchor.lstrip("#"),
        issued_at=int(time.time() if issued_at is None else issued_at),
    )
    payload = json.dumps(asdict(context), separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return f"{_encode(payload)}.{_encode(signature)}"


def resolve_return_context(
    secret: str,
    token: str,
    *,
    allowed_prefixes: tuple[str, ...],
    max_age_seconds: int = 7200,
    now: int | None = None,
) -> ReturnContext | None:
    try:
        payload_part, signature_part = token.split(".", 1)
        payload = _decode(payload_part)
        supplied_signature = _decode(signature_part)
        expected_signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        raw = json.loads(payload)
        context = ReturnContext(**raw)
    except (TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None
    current_time = int(time.time() if now is None else now)
    if context.version != RETURN_CONTEXT_VERSION:
        return None
    if context.issued_at > current_time + 60 or current_time - context.issued_at > max_age_seconds:
        return None
    if not _valid_path(context.path, allowed_prefixes):
        return None
    if len(context.query) > 2000 or len(context.anchor) > 160:
        return None
    if any(character in context.query + context.anchor for character in "\r\n"):
        return None
    return context
