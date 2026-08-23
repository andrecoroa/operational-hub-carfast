from __future__ import annotations

import json
import socket

import pytest

from app.platform.anonymized_receive import validated_envelopes
from app.platform.anonymized_stream import UnsafePayload
from scripts.receive_anonymized_stream import install_ip_socket_blocker, require_local_socket


def test_destination_accepts_only_safe_envelope() -> None:
    line = json.dumps(
        {
            "schema": 2,
            "pilot": "eight-table",
            "table": "users",
            "data": {
                "id": "R-user-0123456789abcdef",
                "active": True,
                "email": "user-abcdef123456@invalid.example",
                "name": "Person-abcdef123456",
            },
        }
    ).encode()
    assert list(validated_envelopes([line]))[0]["table"] == "users"


def test_destination_rejects_raw_identifier() -> None:
    line = json.dumps(
        {
            "schema": 2,
            "pilot": "eight-table",
            "table": "users",
            "data": {"id": "R-user-0123456789abcdef", "active": True, "email": "real@example.pt"},
        }
    ).encode()
    with pytest.raises(UnsafePayload):
        list(validated_envelopes([line]))


def test_destination_rejects_unclassified_output_field() -> None:
    line = json.dumps(
        {
            "schema": 2,
            "pilot": "eight-table",
            "table": "users",
            "data": {"id": "R-user-0123456789abcdef", "active": True, "unexpected": "technical"},
        }
    ).encode()
    with pytest.raises(UnsafePayload):
        list(validated_envelopes([line]))


def test_destination_requires_loopback_or_unix_socket() -> None:
    require_local_socket("postgresql:///carfast_anonymized_test?host=/var/run/postgresql")
    with pytest.raises(ValueError):
        require_local_socket("postgresql://localhost/carfast_anonymized_test")
    with pytest.raises(ValueError):
        require_local_socket("postgresql://remote.example/carfast_anonymized_test")


def test_destination_rejects_nested_unicode_and_raw_id() -> None:
    probes = [
        {"id": 1, "active": True},
        {"id": "R-user-0123456789abcdef", "active": True, "name": {"nested": "x"}},
        {"id": "R-user-0123456789abcdef", "active": True, "name": "Nome livre ç"},
    ]
    for data in probes:
        line = json.dumps(
            {"schema": 2, "pilot": "eight-table", "table": "users", "data": data}
        ).encode()
        with pytest.raises(UnsafePayload):
            list(validated_envelopes([line]))


def test_process_socket_blocker_rejects_real_ip_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    original = socket.socket
    monkeypatch.setattr(socket, "socket", original)
    install_ip_socket_blocker()
    with pytest.raises(PermissionError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM)
