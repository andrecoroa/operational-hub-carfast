"""Process-level outbound guard for the disposable empty rehearsal only."""

from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Callable
from typing import Any


class EgressDenied(OSError):
    """Raised when the empty rehearsal attempts an external connection."""


def _allowed_host(host: str) -> bool:
    value = host.strip().lower().rstrip(".")
    if value in {"localhost", "127.0.0.1", "::1"}:
        return True
    db_host = os.environ.get("REHEARSAL_DATABASE_HOST", "").strip().lower().rstrip(".")
    if db_host and value == db_host:
        return True
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def install_process_egress_guard() -> Callable[..., Any]:
    """Deny application socket connections except loopback and the isolated DB."""
    if os.environ.get("RENDER_EMPTY_REHEARSAL", "").strip().lower() != "true":
        raise RuntimeError("egress guard is restricted to the empty rehearsal")
    original = socket.create_connection

    def guarded(address: tuple[str, int], *args: Any, **kwargs: Any) -> socket.socket:
        host = str(address[0])
        if not _allowed_host(host):
            raise EgressDenied("external network access denied for empty rehearsal")
        return original(address, *args, **kwargs)

    socket.create_connection = guarded
    return original
