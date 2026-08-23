from __future__ import annotations

import json

import pytest

from app.platform.anonymized_receive import validated_envelopes
from app.platform.anonymized_stream import UnsafePayload
from scripts.receive_anonymized_stream import require_local_socket


def test_destination_accepts_only_safe_envelope() -> None:
    line = json.dumps(
        {
            "schema": 1,
            "table": "users",
            "data": {
                "id": 1,
                "active": True,
                "email": "user-abcdef123456@invalid.example",
                "name": "Person-abcdef123456",
            },
        }
    ).encode()
    assert list(validated_envelopes([line]))[0]["table"] == "users"


def test_destination_rejects_raw_identifier() -> None:
    line = json.dumps(
        {"schema": 1, "table": "users", "data": {"id": 1, "email": "real@example.pt"}}
    ).encode()
    with pytest.raises(UnsafePayload):
        list(validated_envelopes([line]))


def test_destination_rejects_unclassified_output_field() -> None:
    line = json.dumps(
        {"schema": 1, "table": "users", "data": {"id": 1, "unexpected": "technical"}}
    ).encode()
    with pytest.raises(UnsafePayload):
        list(validated_envelopes([line]))


def test_destination_requires_loopback_or_unix_socket() -> None:
    require_local_socket("postgresql:///carfast_anonymized_test?host=/var/run/postgresql")
    require_local_socket("postgresql://localhost/carfast_anonymized_test")
    with pytest.raises(ValueError):
        require_local_socket("postgresql://remote.example/carfast_anonymized_test")
