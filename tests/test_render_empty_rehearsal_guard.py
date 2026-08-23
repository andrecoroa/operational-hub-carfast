from __future__ import annotations

import socket

import pytest

from app.core.egress_guard import EgressDenied, install_process_egress_guard
from scripts.validate_isolated_environment import validate_environment


def test_render_internal_database_is_accepted_only_for_explicit_empty_rehearsal() -> None:
    environment = {
        "APP_ENV": "test",
        "DATABASE_URL": "postgresql+psycopg://u:p@dpg-synthetic-a/rehearsal_test",
        "RENDER": "true",
        "RENDER_EMPTY_REHEARSAL": "true",
        "REHEARSAL_DATABASE_HOST": "dpg-synthetic-a",
        "DOCUMENT_FIXTURES_ONLY": "true",
        "REAL_DATA_ALLOWED": "false",
    }
    assert validate_environment(environment) == []
    environment["RENDER_EMPTY_REHEARSAL"] = "false"
    assert "database must be isolated on the runner" in validate_environment(environment)


def test_process_guard_denies_external_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RENDER_EMPTY_REHEARSAL", "true")
    original = socket.create_connection
    install_process_egress_guard()
    try:
        with pytest.raises(EgressDenied):
            socket.create_connection(("example.com", 443), timeout=0.01)
    finally:
        socket.create_connection = original
