from __future__ import annotations

import hashlib
from types import SimpleNamespace

import pytest

import scripts.preflight_integral_runtime as preflight


def test_tool_major_returns_only_major_and_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda name: f"/safe/{name}")
    evidence = b"pg_restore (PostgreSQL) 17.6\n"
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=evidence, stderr=b""
        ),
    )
    assert preflight.tool_major("pg_restore") == (
        17,
        hashlib.sha256(evidence).hexdigest(),
    )


def test_missing_tool_fails_before_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.shutil, "which", lambda _name: None)
    with pytest.raises(RuntimeError, match="missing runtime tool"):
        preflight.tool_major("pg_restore")


def test_receiver_runtime_requires_staging_destination_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(preflight, "validate_integral_config", lambda _role: "sha")
    monkeypatch.setenv("INTEGRAL_DATABASE_DESTINATION_PHASE", "source-staging")
    with pytest.raises(RuntimeError, match="destination phase must be staging"):
        preflight.main()
