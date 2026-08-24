from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts import integral_render_entrypoint as entrypoint

ROOT = Path(__file__).parents[1]
CANONICAL = (
    "/bin/sh -c 'umask 077 && exec /opt/carfast-venv/bin/python "
    "-m scripts.integral_render_entrypoint'"
)


def test_render_contract_has_one_exact_entrypoint_and_external_postgres() -> None:
    blueprint = yaml.safe_load((ROOT / "render.integral.yaml").read_text())
    services = blueprint["services"]
    assert len(services) == 1
    service = services[0]
    assert service["type"] == "pserv"
    assert service["region"] == "frankfurt"
    assert service["plan"] == "starter"
    assert service["autoDeployTrigger"] == "off"
    assert service["runtime"] == "docker"
    assert service["dockerfilePath"] == "./deploy/integral/Dockerfile"
    assert service["dockerCommand"] == CANONICAL
    assert service["healthCheckPath"] == "/health"
    assert service["disk"] == {
        "name": "carfast-integral-spool", "mountPath": "/var/data", "sizeGB": 5
    }


def test_no_competing_render_entrypoint_or_local_postgres() -> None:
    legacy = (ROOT / "scripts/run_integral_render_rehearsal.sh").read_text()
    internal = (ROOT / "scripts/run_integral_e2e_rehearsal.sh").read_text()
    fixture = (ROOT / "scripts/run_integral_external_fixture.sh").read_text()
    assert "legacy_render_entrypoint_rejected=true" in legacy
    assert "initdb" not in legacy
    assert "pg_ctl" not in legacy
    assert "INTEGRAL_ENTRYPOINT_DELEGATED" in internal
    assert "external_postgres_required=true" in internal
    assert "build_integral_secret_envelope" not in internal
    assert "scripts.integral_render_entrypoint" in fixture


def test_docker_runtime_pins_pg17_user_and_canonical_entrypoint() -> None:
    dockerfile = (ROOT / "deploy/integral/Dockerfile").read_text()
    assert dockerfile.startswith("FROM postgres:17.10-bookworm@sha256:")
    assert len(dockerfile.splitlines()[0].rsplit("sha256:", 1)[1]) == 64
    assert "USER 10001:10001" in dockerfile
    assert 'ENTRYPOINT ["/usr/bin/tini", "--"]' in dockerfile
    assert "scripts.integral_render_entrypoint" in dockerfile


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1", "rehearsal-postgres"])
def test_local_database_hosts_are_rejected(monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("INTEGRAL_EXPECTED_DATABASE_HOST", host)
    monkeypatch.setenv("INTEGRAL_PRIVATE_DATABASE_SUFFIX", host)
    with pytest.raises(RuntimeError, match="external_private_database_host_rejected"):
        entrypoint.external_private_host(f"postgresql://u:p@{host}:5432/db")


def test_private_database_host_is_bound_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTEGRAL_EXPECTED_DATABASE_HOST", "dpg-fixture-a")
    monkeypatch.setenv("INTEGRAL_PRIVATE_DATABASE_SUFFIX", "-a")
    assert entrypoint.external_private_host(
        "postgresql+psycopg://u:p@dpg-fixture-a:5432/carfast_integral_staging_1_test"
    ) == "dpg-fixture-a"


def test_failure_output_contract_never_contains_exception_text() -> None:
    source = (ROOT / "scripts/integral_render_entrypoint.py").read_text()
    assert "hashlib.sha256(str(exc).encode())" in source
    assert 'print(f"{FAILURE_PREFIX}={type(exc).__name__}:{code}"' in source


def test_tombstone_blocks_before_preflight_or_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tombstone = tmp_path / "one-shot.json"
    tombstone.write_text("{}")
    monkeypatch.setenv("INTEGRAL_RUNTIME_ROLE", "synthetic_orchestrator")
    monkeypatch.setenv("INTEGRAL_MODE", "synthetic")
    monkeypatch.setenv("INTEGRAL_TOMBSTONE_PATH", str(tombstone))

    class Server:
        def shutdown(self) -> None:
            return
    monkeypatch.setattr(entrypoint, "health_server", lambda: Server())
    monkeypatch.setattr(
        entrypoint, "runtime_preflight", lambda _role: pytest.fail("preflight ran")
    )
    monkeypatch.setattr(entrypoint, "hold_restart_blocked", lambda: None)
    assert entrypoint.main() == 0


def test_tombstone_claim_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INTEGRAL_RELEASE_SHA", "a" * 40)
    path = tmp_path / "one-shot.json"
    assert entrypoint.reserve_tombstone(path) is True
    assert entrypoint.reserve_tombstone(path) is False
    assert __import__("json").loads(path.read_text())["result"] == "started"


def test_private_transfer_rejects_direct_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import integral_private_transfer
    monkeypatch.delenv("INTEGRAL_ENTRYPOINT_DELEGATED", raising=False)
    assert integral_private_transfer.main() == 64


def test_synthetic_spool_rejects_direct_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import synthetic_spool_rehearsal
    monkeypatch.delenv("INTEGRAL_ENTRYPOINT_DELEGATED", raising=False)
    with pytest.raises(SystemExit, match="direct_execution_rejected"):
        synthetic_spool_rehearsal.main()
