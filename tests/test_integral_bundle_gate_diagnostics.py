from __future__ import annotations

import subprocess

import pytest

from scripts import integral_private_transfer as transfer


def _failed(stderr: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(["python"], 1, "", stderr)


def test_contract_gate_propagates_only_safe_structured_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = (
        "migration_contract_phase=staging valid=false "
        f"failure_code=relation_inventory_mismatch detail_sha256={'a' * 64}"
    )
    monkeypatch.setattr(
        transfer.subprocess,
        "run",
        lambda *args, **kwargs: _failed(f"sensitive database detail\n{diagnostic}\n"),
    )

    with pytest.raises(RuntimeError) as raised:
        transfer._run_bundle_gate(
            ["python", "-m", "scripts.validate_integral_migration_contract", "staging"], {}
        )

    message = str(raised.value)
    assert diagnostic in message
    assert "sensitive database detail" not in message


@pytest.mark.parametrize(
    "stderr",
    [
        "migration_contract_phase=staging valid=false failure_code=x detail_sha256=short",
        "migration_contract_phase=staging valid=false failure_code=x detail_sha256="
        + "b" * 64
        + " extra",
        "migration_contract_phase=staging valid=false failure_code=x detail_sha256="
        + "b" * 64
        + "\n" * 2
        + "migration_contract_phase=target valid=false failure_code=y detail_sha256="
        + "c" * 64,
    ],
)
def test_contract_gate_rejects_ambiguous_or_malformed_diagnostics(
    monkeypatch: pytest.MonkeyPatch, stderr: str
) -> None:
    monkeypatch.setattr(transfer.subprocess, "run", lambda *args, **kwargs: _failed(stderr))

    with pytest.raises(RuntimeError) as raised:
        transfer._run_bundle_gate(
            ["python", "-m", "scripts.validate_integral_migration_contract", "staging"], {}
        )

    assert " diagnostic=" not in str(raised.value)
    assert stderr not in str(raised.value)


def test_non_contract_gate_never_propagates_structured_looking_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diagnostic = (
        "migration_contract_phase=staging valid=false "
        f"failure_code=relation_inventory_mismatch detail_sha256={'d' * 64}"
    )
    monkeypatch.setattr(transfer.subprocess, "run", lambda *args, **kwargs: _failed(diagnostic))

    with pytest.raises(RuntimeError) as raised:
        transfer._run_bundle_gate(["alembic", "upgrade", "head"], {})

    assert diagnostic not in str(raised.value)
